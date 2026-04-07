"""Integration tests for Phase 3b: Hook Dispatch + Delegation Round-Trip.

Tests run in-process via FastAPI TestClient and pytest-asyncio.
No Docker required.

Run with:
    PYTHONPATH=services/svc-hooks-approval/src:services/svc-hooks-routing/src:\
services/svc-hooks-async/src:services/svc-hooks-shell/src:\
services/svc-delegation/src:services/svc-orchestrator/src:\
amplifier-service-sdk/src python -m pytest \
tests/integration/test_phase3b_integration.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from amplifier_service_sdk.models import RoutingTable
from svc_delegation.app import create_delegation_app
from svc_hooks_approval.app import create_approval_hook_app
from svc_hooks_async.app import create_async_hooks_app
from svc_hooks_routing.app import create_routing_hook_app
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.hook_dispatcher import HookDispatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_MATRIX = {
    "name": "balanced",
    "roles": {
        "general": {"description": "General purpose tasks"},
        "fast": {"description": "Quick utility tasks"},
    },
}


def _make_dapr() -> DaprClient:
    """Return a DaprClient with mocked invoke/publish methods."""
    dapr = DaprClient(dapr_url="http://localhost:3500")
    dapr.invoke = AsyncMock()  # type: ignore[method-assign]
    dapr.publish = AsyncMock()  # type: ignore[method-assign]
    return dapr


def _routing_table(
    hooks: dict | None = None,
    hook_priorities: dict | None = None,
    hook_endpoints: dict | None = None,
) -> RoutingTable:
    return RoutingTable(
        hooks=hooks or {},
        hook_priorities=hook_priorities or {},
        hook_endpoints=hook_endpoints or {},
    )


# ---------------------------------------------------------------------------
# TestApprovalHookService
# ---------------------------------------------------------------------------


class TestApprovalHookService:
    """Tests for the svc-hooks-approval FastAPI service."""

    @pytest.fixture
    def client(self):
        """TestClient with an empty deny list."""
        app = create_approval_hook_app(config={"deny_tools": []})
        return TestClient(app)

    @pytest.fixture
    def client_with_deny(self):
        """TestClient with 'bash' in the deny list."""
        app = create_approval_hook_app(config={"deny_tools": ["bash"]})
        return TestClient(app)

    def test_approval_describe(self, client: TestClient) -> None:
        """GET /describe response includes an 'approval' hook."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        hook_names = [h["name"] for h in data.get("hooks", [])]
        assert "approval" in hook_names

    def test_approval_allows_safe_tool(self, client: TestClient) -> None:
        """POST /hooks/approval/invoke with a safe tool returns CONTINUE."""
        payload = {"event": "tool:pre", "data": {"tool_name": "web_search"}}
        response = client.post("/hooks/approval/invoke", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "CONTINUE"

    def test_approval_denies_configured_tool(
        self, client_with_deny: TestClient
    ) -> None:
        """POST /hooks/approval/invoke with a denied tool returns DENY with tool name in reason."""
        payload = {"event": "tool:pre", "data": {"tool_name": "bash"}}
        response = client_with_deny.post("/hooks/approval/invoke", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "DENY"
        assert data["reason"] is not None
        assert "bash" in data["reason"]

    def test_approval_dapr_subscribe_is_empty(self, client: TestClient) -> None:
        """GET /dapr/subscribe returns an empty list (sync hook, no pub/sub)."""
        response = client.get("/dapr/subscribe")
        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# TestRoutingHookService
# ---------------------------------------------------------------------------


class TestRoutingHookService:
    """Tests for the svc-hooks-routing FastAPI service."""

    @pytest.fixture
    def client(self):
        """TestClient with no routing matrix."""
        app = create_routing_hook_app(matrix={})
        return TestClient(app)

    @pytest.fixture
    def client_with_matrix(self):
        """TestClient with a populated routing matrix."""
        app = create_routing_hook_app(matrix=SAMPLE_MATRIX)
        return TestClient(app)

    def test_routing_describe(self, client: TestClient) -> None:
        """GET /describe response includes a 'routing' hook."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        hook_names = [h["name"] for h in data.get("hooks", [])]
        assert "routing" in hook_names

    def test_routing_no_matrix_continues(self, client: TestClient) -> None:
        """Invoke with no matrix configured returns CONTINUE."""
        payload = {"event": "provider:request", "data": {}}
        response = client.post("/hooks/routing/invoke", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "CONTINUE"

    def test_routing_with_matrix_injects_context(
        self, client_with_matrix: TestClient
    ) -> None:
        """Invoke with a matrix configured returns INJECT_CONTEXT with role names."""
        payload = {"event": "provider:request", "data": {}}
        response = client_with_matrix.post("/hooks/routing/invoke", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "INJECT_CONTEXT"
        assert data["data"] is not None
        context_injection = data["data"]["context_injection"]
        # Both role names should appear in the injected context
        assert "general" in context_injection
        assert "fast" in context_injection


# ---------------------------------------------------------------------------
# TestAsyncHookService
# ---------------------------------------------------------------------------


class TestAsyncHookService:
    """Tests for the svc-hooks-async FastAPI service."""

    @pytest.fixture
    def client(self, tmp_path):
        """TestClient with a temp log directory."""
        template = str(tmp_path / "{session_id}" / "events.jsonl")
        app = create_async_hooks_app(log_template=template)
        return TestClient(app)

    def test_async_describe(self, client: TestClient) -> None:
        """GET /describe response includes a 'logging' hook."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        hook_names = [h["name"] for h in data.get("hooks", [])]
        assert "logging" in hook_names

    def test_async_dapr_subscribe_has_topics(self, client: TestClient) -> None:
        """GET /dapr/subscribe returns subscriptions that include tool.post, session.start, session.end."""
        response = client.get("/dapr/subscribe")
        assert response.status_code == 200
        subscriptions = response.json()
        assert isinstance(subscriptions, list)
        assert len(subscriptions) > 0
        topics = [sub["topic"] for sub in subscriptions]
        assert "tool.post" in topics, f"'tool.post' not found in topics: {topics}"
        assert "session.start" in topics, (
            f"'session.start' not found in topics: {topics}"
        )
        assert "session.end" in topics, f"'session.end' not found in topics: {topics}"

    def test_async_event_endpoint_accepts_tool_post(self, client: TestClient) -> None:
        """POST /events/tool.post with a valid CloudEvents envelope returns SUCCESS."""
        envelope = {
            "specversion": "1.0",
            "type": "tool.post",
            "source": "amplifier",
            "id": "abc-123",
            "datacontenttype": "application/json",
            "data": {"session_id": "test-session-42", "tool": "bash"},
        }
        response = client.post("/events/tool.post", json=envelope)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# TestHookDispatcher
# ---------------------------------------------------------------------------


class TestHookDispatcher:
    """Async unit tests for HookDispatcher using a mocked DaprClient."""

    @pytest.mark.asyncio
    async def test_dispatcher_approves_safe_tool(self) -> None:
        """When the hook service returns CONTINUE, dispatcher returns CONTINUE."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {  # type: ignore[union-attr]
            "action": "CONTINUE",
            "data": None,
            "reason": None,
        }

        routing = _routing_table(
            hooks={"tool:pre": ["svc-hooks-approval"]},
            hook_endpoints={"svc-hooks-approval": "hooks/approval/invoke"},
        )
        dispatcher = HookDispatcher(dapr)

        result = await dispatcher.dispatch_pre(
            "tool:pre", {"tool_name": "web_search"}, routing
        )

        assert result.action == "CONTINUE"
        dapr.invoke.assert_called_once()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_dispatcher_blocks_denied_tool(self) -> None:
        """When the hook service returns DENY, dispatcher propagates DENY immediately."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {  # type: ignore[union-attr]
            "action": "DENY",
            "data": None,
            "reason": "Tool 'bash' is denied by pattern 'bash'",
        }

        routing = _routing_table(
            hooks={"tool:pre": ["svc-hooks-approval"]},
            hook_endpoints={"svc-hooks-approval": "hooks/approval/invoke"},
        )
        dispatcher = HookDispatcher(dapr)

        result = await dispatcher.dispatch_pre(
            "tool:pre", {"tool_name": "bash"}, routing
        )

        assert result.action == "DENY"
        assert result.reason is not None


# ---------------------------------------------------------------------------
# TestDelegationService
# ---------------------------------------------------------------------------


class TestDelegationService:
    """Tests for the svc-delegation FastAPI service."""

    @pytest.fixture
    def client(self):
        """TestClient pointing at a fake orchestrator URL (no real HTTP calls)."""
        app = create_delegation_app(orchestrator_base_url="http://localhost:9999/fake")
        return TestClient(app)

    def test_delegation_describe(self, client: TestClient) -> None:
        """GET /describe response includes a 'delegate' tool."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "delegate" in tool_names

    def test_delegation_tool_missing_instruction_returns_error(
        self, client: TestClient
    ) -> None:
        """POST /tools/delegate/execute with empty input returns success=False."""
        payload = {"name": "delegate", "input": {}}
        response = client.post("/tools/delegate/execute", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] is not None
        assert "instruction" in data["error"]["message"]
