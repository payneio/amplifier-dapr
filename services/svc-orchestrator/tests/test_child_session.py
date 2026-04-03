"""Tests for ChildSessionSpawner."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from svc_orchestrator.child_session import ChildSessionRequest, ChildSessionSpawner
from svc_orchestrator.dapr_client import DaprClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dapr() -> DaprClient:
    """Return a DaprClient instance with mocked methods."""
    dapr = DaprClient(dapr_url="http://localhost:3500")
    dapr.invoke = AsyncMock()  # type: ignore[method-assign]
    return dapr


# ---------------------------------------------------------------------------
# TestChildSessionSpawner
# ---------------------------------------------------------------------------


class TestChildSessionSpawner:
    """Tests for ChildSessionSpawner.spawn()."""

    @pytest.mark.asyncio
    async def test_spawn_calls_session_service_via_dapr(self) -> None:
        """spawn() invokes the session-service via Dapr with the correct app_id."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "ok", "messages": []}  # type: ignore[union-attr]

        spawner = ChildSessionSpawner(dapr=dapr)
        request = ChildSessionRequest(
            prompt="Hello, world!",
            child_session_id="test-session",
        )

        await spawner.spawn(request)

        # Must have called dapr.invoke with session-service app_id
        dapr.invoke.assert_called_once()  # type: ignore[union-attr]
        call_args = dapr.invoke.call_args  # type: ignore[union-attr]
        assert call_args[0][0] == "session-service"
        assert "test-session" in call_args[0][1]  # method contains session_id

    @pytest.mark.asyncio
    async def test_spawn_generates_session_id_if_missing(self) -> None:
        """spawn() generates a session_id when child_session_id is empty."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "ok", "messages": []}  # type: ignore[union-attr]

        spawner = ChildSessionSpawner(dapr=dapr)
        request = ChildSessionRequest(
            prompt="Generate a session ID for me",
            child_session_id="",  # empty → should auto-generate
        )

        result = await spawner.spawn(request)

        # invoke must have been called
        dapr.invoke.assert_called_once()  # type: ignore[union-attr]
        call_args = dapr.invoke.call_args  # type: ignore[union-attr]
        method: str = call_args[0][1]
        # The method should be sessions/<generated_id>/turn with a non-empty id
        assert method.startswith("sessions/")
        assert method.endswith("/turn")
        session_part = method[len("sessions/") : -len("/turn")]
        assert len(session_part) > 0, "session_id should have been generated"

        # result must include the generated session_id merged with dapr response
        assert result["result"] == "ok"
        assert result["messages"] == []
        assert result["session_id"] == session_part

    @pytest.mark.asyncio
    async def test_spawn_passes_workspace_content(self) -> None:
        """spawn() includes workspace_content in the payload sent to session-service."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "done", "messages": []}  # type: ignore[union-attr]

        spawner = ChildSessionSpawner(dapr=dapr)
        workspace = {"file.py": "print('hello')", "README.md": "# Test"}
        request = ChildSessionRequest(
            prompt="Use the workspace",
            child_session_id="ws-session",
            workspace_content=workspace,
        )

        await spawner.spawn(request)

        dapr.invoke.assert_called_once()  # type: ignore[union-attr]
        call_args = dapr.invoke.call_args  # type: ignore[union-attr]
        payload: dict = call_args[0][2]
        assert "workspace_content" in payload
        assert payload["workspace_content"] == workspace

    @pytest.mark.asyncio
    async def test_spawn_returns_session_id_in_result(self) -> None:
        """spawn() includes the session_id used in the returned dict."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "ok", "messages": []}  # type: ignore[union-attr]

        spawner = ChildSessionSpawner(dapr=dapr)
        result = await spawner.spawn(
            ChildSessionRequest(prompt="hi", child_session_id="")
        )

        assert "session_id" in result
        assert len(result["session_id"]) == 8


# ---------------------------------------------------------------------------
# TestEnrichedDelegation
# ---------------------------------------------------------------------------


class TestEnrichedDelegation:
    """Tests for enriched delegation parameters (depth, context, model_role)."""

    @pytest.mark.asyncio
    async def test_spawn_forwards_delegation_depth(self) -> None:
        """spawn() includes delegation_depth in the payload sent to session-service."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "ok", "messages": []}  # type: ignore[union-attr]

        spawner = ChildSessionSpawner(dapr=dapr)
        request = ChildSessionRequest(
            prompt="Deep delegation",
            child_session_id="test-session",
            delegation_depth=3,
        )

        await spawner.spawn(request)

        call_args = dapr.invoke.call_args  # type: ignore[union-attr]
        payload: dict = call_args[0][2]
        assert payload["delegation_depth"] == 3

    @pytest.mark.asyncio
    async def test_spawn_forwards_agent_ref(self) -> None:
        """spawn() includes agent_ref in the payload sent to session-service."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "ok", "messages": []}  # type: ignore[union-attr]

        spawner = ChildSessionSpawner(dapr=dapr)
        request = ChildSessionRequest(
            prompt="Agent ref test",
            child_session_id="test-session",
            agent_ref="foundation:explorer",
        )

        await spawner.spawn(request)

        call_args = dapr.invoke.call_args  # type: ignore[union-attr]
        payload: dict = call_args[0][2]
        assert payload["agent_ref"] == "foundation:explorer"

    @pytest.mark.asyncio
    async def test_spawn_forwards_context_messages(self) -> None:
        """spawn() includes context_messages in payload when non-empty."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "ok", "messages": []}  # type: ignore[union-attr]

        spawner = ChildSessionSpawner(dapr=dapr)
        messages = [{"role": "user", "content": "hello"}]
        request = ChildSessionRequest(
            prompt="Context messages test",
            child_session_id="test-session",
            context_messages=messages,
        )

        await spawner.spawn(request)

        call_args = dapr.invoke.call_args  # type: ignore[union-attr]
        payload: dict = call_args[0][2]
        assert payload["context_messages"] == messages
