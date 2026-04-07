# Phase 2: Session Lifecycle & Integration Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Wire the machine instance lifecycle through session-service, orchestrator, and CLI so that creating a session provisions a machine instance, turns forward `machine_instance_id` to the orchestrator, tool dispatches include the instance ID, and session end cleans up the instance.

**Architecture:** The session-service gains a `POST /sessions/create` endpoint that resolves agent config, provisions a machine instance via Dapr invocation to the machine service, and stores the `machine_instance_id` in session state. Each turn payload to the orchestrator includes `machine_instance_id` as a top-level field. The orchestrator passes it through to every tool dispatch body. The CLI adds a `create_session()` method that calls the new endpoint before the first turn, defaulting to `{type: "ssh", host: "localhost", working_dir: <cwd>}`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, httpx, pytest, pytest-asyncio

**Design document:** `docs/design/machine-service-consolidation-design.md`
**Phase 1 plan:** `docs/plans/phase1-machine-service-consolidation.md`

---

## Task 1: Add CreateSessionRequest and CreateSessionResponse models to session-service

**Files:**
- Modify: `services/session-service/src/session_service/app.py` (lines 29-55, the Request/Response models section)
- Test: `services/session-service/tests/test_session_create.py` (new file)

**Step 1: Write the failing test**

Create `services/session-service/tests/test_session_create.py`:

```python
"""Tests for session creation with machine provisioning."""

from __future__ import annotations

from session_service.app import CreateSessionRequest, CreateSessionResponse


class TestCreateSessionModels:
    """Verify CreateSessionRequest and CreateSessionResponse exist and validate."""

    def test_create_session_request_defaults(self) -> None:
        """CreateSessionRequest has sensible defaults."""
        req = CreateSessionRequest(agent_ref="foundation")
        assert req.agent_ref == "foundation"
        assert req.machine_config is None

    def test_create_session_request_with_machine_config(self) -> None:
        """CreateSessionRequest accepts machine_config dict."""
        req = CreateSessionRequest(
            agent_ref="foundation",
            machine_config={"type": "ssh", "host": "localhost", "working_dir": "/home/user"},
        )
        assert req.machine_config == {"type": "ssh", "host": "localhost", "working_dir": "/home/user"}

    def test_create_session_response_fields(self) -> None:
        """CreateSessionResponse includes session_id and optional machine_instance_id."""
        resp = CreateSessionResponse(session_id="s1", machine_instance_id="inst-abc")
        assert resp.session_id == "s1"
        assert resp.machine_instance_id == "inst-abc"

    def test_create_session_response_no_machine(self) -> None:
        """CreateSessionResponse allows None machine_instance_id."""
        resp = CreateSessionResponse(session_id="s2")
        assert resp.session_id == "s2"
        assert resp.machine_instance_id is None
```

**Step 2: Run the test to verify it fails**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py::TestCreateSessionModels -v
```

Expected: FAIL — `ImportError: cannot import name 'CreateSessionRequest' from 'session_service.app'`

**Step 3: Write the implementation**

In `services/session-service/src/session_service/app.py`, add these two models after the existing `SessionInfo` model (after line 55):

```python
class CreateSessionRequest(BaseModel):
    """Request model for POST /sessions/create."""

    agent_ref: str = "default"
    machine_config: dict[str, Any] | None = None


class CreateSessionResponse(BaseModel):
    """Response model for POST /sessions/create."""

    session_id: str
    machine_instance_id: str | None = None
```

**Step 4: Run the test to verify it passes**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py::TestCreateSessionModels -v
```

Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add services/session-service/src/session_service/app.py services/session-service/tests/test_session_create.py && git commit -m "feat(session): add CreateSessionRequest and CreateSessionResponse models"
```

---

## Task 2: Add POST /sessions/create endpoint to session-service

**Files:**
- Modify: `services/session-service/src/session_service/app.py` (inside `create_session_app()`, after the `session_clear` endpoint around line 434)
- Modify: `services/session-service/tests/test_session_create.py` (append new test class)

**Step 1: Write the failing test**

Append to `services/session-service/tests/test_session_create.py`:

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from session_service.app import create_session_app


def _make_client(dapr_url: str = "http://localhost:3500") -> TestClient:
    return TestClient(create_session_app(dapr_url=dapr_url))


class TestCreateSessionEndpoint:
    """Tests for POST /sessions/create."""

    @pytest.fixture(autouse=True)
    def isolate_from_yaml(self):
        """Force get_agent_config to use the hardcoded AGENTS dict."""
        with patch(
            "session_service.agents._load_from_yaml",
            return_value=None,
        ):
            yield

    @pytest.fixture
    def mock_discover(self):
        """Patch discover_services to return an empty routing table."""
        with patch(
            "session_service.app.discover_services",
            new_callable=AsyncMock,
            return_value={
                "tools": {},
                "providers": {},
                "hooks": {},
                "_tool_specs": [],
                "context": "svc-context",
                "hook_endpoints": {},
                "hook_priorities": {},
            },
        ) as m:
            yield m

    def test_create_session_returns_session_id(self, mock_discover) -> None:
        """POST /sessions/create returns 200 with a session_id."""
        client = _make_client()
        response = client.post(
            "/sessions/create",
            json={"agent_ref": "foundation"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert isinstance(data["session_id"], str)
        assert len(data["session_id"]) > 0

    def test_create_session_without_machine_config(self, mock_discover) -> None:
        """POST /sessions/create without machine_config sets machine_instance_id to null."""
        client = _make_client()
        response = client.post(
            "/sessions/create",
            json={"agent_ref": "default"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["machine_instance_id"] is None

    def test_create_session_with_machine_config_provisions_instance(
        self, mock_discover
    ) -> None:
        """POST /sessions/create with machine_config calls machine service and returns instance_id."""
        # Mock the routing table to include a machine behavior
        mock_discover.return_value = {
            "tools": {"bash": "svc-machine-abc123"},
            "providers": {},
            "hooks": {},
            "_tool_specs": [],
            "context": "svc-context",
            "hook_endpoints": {},
            "hook_priorities": {},
            "_behaviors": {"machine": "svc-machine-abc123"},
        }

        # Mock the Dapr HTTP call to machine service POST /instances
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"instance_id": "inst-xyz789"})

        with patch("session_service.app.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_http

            client = _make_client()
            response = client.post(
                "/sessions/create",
                json={
                    "agent_ref": "foundation",
                    "machine_config": {
                        "type": "ssh",
                        "host": "localhost",
                        "working_dir": "/home/user/project",
                    },
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["machine_instance_id"] == "inst-xyz789"

    def test_create_session_stores_session_state(self, mock_discover) -> None:
        """After POST /sessions/create, GET /sessions/{id} returns session info."""
        client = _make_client()
        create_resp = client.post(
            "/sessions/create",
            json={"agent_ref": "default"},
        )
        session_id = create_resp.json()["session_id"]

        info_resp = client.get(f"/sessions/{session_id}")
        assert info_resp.status_code == 200
        assert info_resp.json()["status"] == "active"
        assert info_resp.json()["turn_count"] == 0
```

**Step 2: Run the test to verify it fails**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py::TestCreateSessionEndpoint -v
```

Expected: FAIL — `404 Not Found` (endpoint doesn't exist yet)

**Step 3: Write the implementation**

In `services/session-service/src/session_service/app.py`:

1. Add `import uuid` at the top of the file (after `import os` on line 7).

2. Inside `create_session_app()`, add this endpoint after the `session_clear` endpoint (after line 434):

```python
    @app.post("/sessions/create")
    async def create_session(request: CreateSessionRequest) -> dict[str, Any]:
        """Create a new session, optionally provisioning a machine instance.

        This is the explicit session creation path. Sessions can still be
        created implicitly on the first turn (backward compatibility).
        """
        session_id = uuid.uuid4().hex[:16]

        # Resolve agent config and discover services
        agent_config = get_agent_config(request.agent_ref)
        service_ids = agent_config["services"]
        routing_table_dict: dict[str, Any] = await discover_services(
            service_ids,
            _dapr_url,
            context_app_id=agent_config.get("context_app_id", "svc-context"),
        )

        machine_instance_id: str | None = None

        # Provision machine instance if machine_config is provided
        if request.machine_config is not None:
            # Find the machine service app-id from the routing table behaviors
            machine_app_id = routing_table_dict.get("_behaviors", {}).get("machine")
            if machine_app_id:
                invoke_url = (
                    f"{_dapr_url}/v1.0/invoke/{machine_app_id}/method/instances"
                )
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        invoke_url,
                        json={
                            "driver_type": request.machine_config.get("type", "ssh"),
                            "config": request.machine_config,
                        },
                        timeout=30.0,
                    )
                    resp.raise_for_status()
                    machine_instance_id = resp.json().get("instance_id")

        # Store session state
        _sessions[session_id] = {
            "turn_count": 0,
            "status": "active",
            "agent_ref": request.agent_ref,
            "routing_table": routing_table_dict,
            "machine_instance_id": machine_instance_id,
        }

        return CreateSessionResponse(
            session_id=session_id,
            machine_instance_id=machine_instance_id,
        ).model_dump()
```

**Step 4: Run the test to verify it passes**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py -v
```

Expected: PASS (all 8 tests — 4 model tests + 4 endpoint tests)

**Step 5: Commit**

```bash
git add services/session-service/src/session_service/app.py services/session-service/tests/test_session_create.py && git commit -m "feat(session): add POST /sessions/create endpoint with machine provisioning"
```

---

## Task 3: Include machine_instance_id in the turn payload to orchestrator

**Files:**
- Modify: `services/session-service/src/session_service/app.py` (the `turn` endpoint, around line 210-219 where `payload` is built)
- Modify: `services/session-service/tests/test_session_create.py` (append new test class)

**Step 1: Write the failing test**

Append to `services/session-service/tests/test_session_create.py`:

```python
class TestTurnPayloadIncludesMachineInstanceId:
    """Verify that the orchestrator turn payload includes machine_instance_id."""

    @pytest.fixture(autouse=True)
    def isolate_from_yaml(self):
        with patch("session_service.agents._load_from_yaml", return_value=None):
            yield

    @pytest.fixture
    def mock_discover(self):
        with patch(
            "session_service.app.discover_services",
            new_callable=AsyncMock,
            return_value={
                "tools": {},
                "providers": {},
                "hooks": {},
                "_tool_specs": [],
                "context": "svc-context",
                "hook_endpoints": {},
                "hook_priorities": {},
            },
        ) as m:
            yield m

    @pytest.fixture
    def mock_transcript(self):
        with (
            patch(
                "session_service.app.load_transcript",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("session_service.app.save_transcript", new_callable=AsyncMock),
        ):
            yield

    @pytest.fixture
    def mock_orchestrator(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"result": "ok", "messages": []})

        with patch("session_service.app.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_http
            yield mock_http

    def test_turn_payload_includes_machine_instance_id(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """When session has machine_instance_id, it appears in the turn payload."""
        from session_service.app import _sessions

        # Pre-populate a session with a machine_instance_id
        _sessions["test-machine-session"] = {
            "turn_count": 0,
            "status": "active",
            "machine_instance_id": "inst-abc123",
        }

        client = _make_client()
        client.post(
            "/sessions/test-machine-session/turn",
            json={"prompt": "hello"},
        )

        payload = mock_orchestrator.post.call_args[1]["json"]
        assert payload["machine_instance_id"] == "inst-abc123"

    def test_turn_payload_machine_instance_id_none_when_absent(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """When session has no machine_instance_id, the field is null in payload."""
        client = _make_client()
        client.post(
            "/sessions/new-session/turn",
            json={"prompt": "hello"},
        )

        payload = mock_orchestrator.post.call_args[1]["json"]
        assert payload.get("machine_instance_id") is None
```

**Step 2: Run the test to verify it fails**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py::TestTurnPayloadIncludesMachineInstanceId -v
```

Expected: FAIL — `KeyError: 'machine_instance_id'` (field not in payload yet)

**Step 3: Write the implementation**

In `services/session-service/src/session_service/app.py`, in the `turn` endpoint, modify the payload dict (around line 210-219). Change the payload construction from:

```python
        payload = {
            "system_prompt": system_prompt,
            "messages": [m.model_dump() for m in transcript],
            "config": {
                "provider": provider_name,
                "tools": routing_table_dict.get("_tool_specs", []),
            },
            "routing_table": routing_table_dict,
            "session_id": session_id,
        }
```

to:

```python
        # Look up machine_instance_id from session state (if session was
        # created via POST /sessions/create with a machine config).
        machine_instance_id = _sessions[session_id].get("machine_instance_id")

        payload = {
            "system_prompt": system_prompt,
            "messages": [m.model_dump() for m in transcript],
            "config": {
                "provider": provider_name,
                "tools": routing_table_dict.get("_tool_specs", []),
            },
            "routing_table": routing_table_dict,
            "session_id": session_id,
            "machine_instance_id": machine_instance_id,
        }
```

**Step 4: Run the test to verify it passes**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py::TestTurnPayloadIncludesMachineInstanceId -v
```

Expected: PASS (2 tests)

**Step 5: Run all session-service tests to check for regressions**

```bash
cd services/session-service && python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add services/session-service/src/session_service/app.py services/session-service/tests/test_session_create.py && git commit -m "feat(session): include machine_instance_id in turn payload to orchestrator"
```

---

## Task 4: Add machine instance cleanup on session end/clear

**Files:**
- Modify: `services/session-service/src/session_service/app.py` (the `session_clear` endpoint around line 429)
- Modify: `services/session-service/tests/test_session_create.py` (append new test class)

**Step 1: Write the failing test**

Append to `services/session-service/tests/test_session_create.py`:

```python
class TestSessionClearDestroysMachineInstance:
    """POST /sessions/{id}/clear calls DELETE on machine instance."""

    @pytest.fixture(autouse=True)
    def isolate_from_yaml(self):
        with patch("session_service.agents._load_from_yaml", return_value=None):
            yield

    def test_clear_session_calls_machine_delete(self) -> None:
        """When session has machine_instance_id, clearing calls DELETE /instances/{id}."""
        from session_service.app import _sessions

        _sessions["sess-with-machine"] = {
            "turn_count": 2,
            "status": "active",
            "machine_instance_id": "inst-delete-me",
            "routing_table": {
                "tools": {"bash": "svc-machine-abc"},
                "_behaviors": {"machine": "svc-machine-abc"},
            },
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"success": True})

        with patch("session_service.app.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.delete = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_http

            client = _make_client()
            response = client.post("/sessions/sess-with-machine/clear")

        assert response.status_code == 200
        # Verify DELETE was called with the correct URL containing the instance ID
        delete_call_url = mock_http.delete.call_args[0][0]
        assert "inst-delete-me" in delete_call_url
        assert "svc-machine-abc" in delete_call_url

    def test_clear_session_without_machine_does_not_call_delete(self) -> None:
        """When session has no machine_instance_id, clearing skips the DELETE call."""
        with patch("session_service.app.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_http

            client = _make_client()
            response = client.post("/sessions/no-machine-session/clear")

        assert response.status_code == 200
        mock_http.delete.assert_not_called()
```

**Step 2: Run the test to verify it fails**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py::TestSessionClearDestroysMachineInstance -v
```

Expected: FAIL — DELETE not called (current `session_clear` doesn't do machine cleanup)

**Step 3: Write the implementation**

In `services/session-service/src/session_service/app.py`, replace the `session_clear` endpoint (around line 429-434) with:

```python
    @app.post("/sessions/{session_id}/clear")
    async def session_clear(session_id: str) -> dict[str, Any]:
        """Reset session state to initial values.

        If the session has a machine instance, destroy it first.
        """
        # Destroy machine instance if one exists
        old_session = _sessions.get(session_id, {})
        machine_instance_id = old_session.get("machine_instance_id")
        if machine_instance_id:
            machine_app_id = (
                old_session.get("routing_table", {})
                .get("_behaviors", {})
                .get("machine")
            )
            if machine_app_id:
                try:
                    delete_url = (
                        f"{_dapr_url}/v1.0/invoke/{machine_app_id}"
                        f"/method/instances/{machine_instance_id}"
                    )
                    async with httpx.AsyncClient() as client:
                        resp = await client.delete(delete_url, timeout=15.0)
                        resp.raise_for_status()
                except Exception:
                    _logger.warning(
                        "Failed to destroy machine instance %s for session %s",
                        machine_instance_id,
                        session_id,
                    )

        # Upsert: create a fresh session entry whether or not one already existed.
        _sessions[session_id] = {"turn_count": 0, "status": "active"}
        return {"status": "cleared"}
```

**Step 4: Run the test to verify it passes**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py::TestSessionClearDestroysMachineInstance -v
```

Expected: PASS (2 tests)

**Step 5: Run all session-service tests**

```bash
cd services/session-service && python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add services/session-service/src/session_service/app.py services/session-service/tests/test_session_create.py && git commit -m "feat(session): destroy machine instance on session clear"
```

---

## Task 5: Orchestrator includes machine_instance_id in tool request body

**Files:**
- Modify: `services/svc-orchestrator/src/svc_orchestrator/app.py` (add `machine_instance_id` to `ExecuteRequest` model, line 20-27)
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py` (pass `machine_instance_id` through `execute()` and add it to tool dispatch at line 660-663)
- Modify: `services/svc-orchestrator/tests/test_orchestrator.py` (add new test class)

**Step 1: Write the failing test**

Append to the end of `services/svc-orchestrator/tests/test_orchestrator.py`:

```python
class TestMachineInstanceIdForwarding:
    """Verify machine_instance_id is included in tool dispatch requests."""

    @pytest.mark.asyncio
    async def test_tool_dispatch_includes_machine_instance_id(self) -> None:
        """When machine_instance_id is set, it appears in the tool invoke body."""
        dapr = _make_dapr()
        invoke_payloads: list[dict[str, Any]] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if "tools/" in method and "/execute" in method:
                invoke_payloads.append(data)
                return {"success": True, "output": "result"}
            if "complete" in method:
                return {
                    "content": "Done",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "name": "bash",
                            "arguments": {"command": "echo hi"},
                        }
                    ],
                    "usage": None,
                    "stop_reason": "tool_use",
                }
            return {"ok": True}

        call_count = 0

        async def mock_invoke_provider(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if "complete" in method:
                if call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "tc1",
                                "name": "bash",
                                "arguments": {"command": "echo hi"},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                return {
                    "content": "Done",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            if "tools/" in method:
                invoke_payloads.append(data)
                return {"success": True, "output": "ok"}
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "test"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke_provider  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        await orch.execute(
            system_prompt="test",
            messages=[Message(role="user", content="run something")],
            config={"provider": "mock", "max_iterations": 2},
            routing_table=_routing_table(tools={"bash": "svc-machine-abc123"}),
            session_id="sess-machine-1",
            machine_instance_id="inst-xyz789",
        )

        assert len(invoke_payloads) > 0
        assert invoke_payloads[0].get("machine_instance_id") == "inst-xyz789"

    @pytest.mark.asyncio
    async def test_tool_dispatch_without_machine_instance_id(self) -> None:
        """When machine_instance_id is None, the field is absent or None in body."""
        dapr = _make_dapr()
        invoke_payloads: list[dict[str, Any]] = []
        call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if "complete" in method:
                if call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "tc1",
                                "name": "bash",
                                "arguments": {"command": "echo hi"},
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                return {
                    "content": "Done",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            if "tools/" in method:
                invoke_payloads.append(data)
                return {"success": True, "output": "ok"}
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "test"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        await orch.execute(
            system_prompt="test",
            messages=[Message(role="user", content="run something")],
            config={"provider": "mock", "max_iterations": 2},
            routing_table=_routing_table(tools={"bash": "svc-machine-abc123"}),
            session_id="sess-no-machine",
        )

        assert len(invoke_payloads) > 0
        assert invoke_payloads[0].get("machine_instance_id") is None
```

**Step 2: Run the test to verify it fails**

```bash
cd services/svc-orchestrator && python -m pytest tests/test_orchestrator.py::TestMachineInstanceIdForwarding -v
```

Expected: FAIL — `execute()` doesn't accept `machine_instance_id` parameter

**Step 3: Write the implementation**

Make these three changes:

**3a.** In `services/svc-orchestrator/src/svc_orchestrator/app.py`, add `machine_instance_id` to the `ExecuteRequest` model (around line 20-27). Change:

```python
class ExecuteRequest(BaseModel):
    """Request model for POST /orchestrator/execute."""

    system_prompt: str
    messages: list[Message]
    config: dict[str, Any] = {}
    routing_table: RoutingTable
    session_id: str = ""
```

to:

```python
class ExecuteRequest(BaseModel):
    """Request model for POST /orchestrator/execute."""

    system_prompt: str
    messages: list[Message]
    config: dict[str, Any] = {}
    routing_table: RoutingTable
    session_id: str = ""
    machine_instance_id: str | None = None
```

Then update the `execute` endpoint handler (around line 91-100) to pass the new field. Change:

```python
        result, messages = await orch.execute(
            system_prompt=request.system_prompt,
            messages=request.messages,
            config=request.config,
            routing_table=request.routing_table,
            session_id=request.session_id,
```

to:

```python
        result, messages = await orch.execute(
            system_prompt=request.system_prompt,
            messages=request.messages,
            config=request.config,
            routing_table=request.routing_table,
            session_id=request.session_id,
            machine_instance_id=request.machine_instance_id,
```

Do the same for the streaming `execute_stream` endpoint handler if it also calls `orch.execute_stream()`.

**3b.** In `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`, add `machine_instance_id` parameter to `execute()` (line 35-42). Change the signature from:

```python
    async def execute(
        self,
        system_prompt: str,
        messages: list[Message],
        config: dict[str, Any],
        routing_table: RoutingTable,
        session_id: str = "",
    ) -> tuple[str, list[Message]]:
```

to:

```python
    async def execute(
        self,
        system_prompt: str,
        messages: list[Message],
        config: dict[str, Any],
        routing_table: RoutingTable,
        session_id: str = "",
        machine_instance_id: str | None = None,
    ) -> tuple[str, list[Message]]:
```

Store it as an instance attribute at the start of `execute()`:

```python
        self._machine_instance_id = machine_instance_id
```

Do the same for `execute_stream()` if it exists with a similar signature.

**3c.** In the `_execute_single_tool` method (line 660-663), change the tool invoke body from:

```python
            raw_result = await self._dapr.invoke(
                tool_app_id,
                f"tools/{tool_call.name}/execute",
                {"name": tool_call.name, "input": tool_call.arguments},
            )
```

to:

```python
            raw_result = await self._dapr.invoke(
                tool_app_id,
                f"tools/{tool_call.name}/execute",
                {
                    "name": tool_call.name,
                    "input": tool_call.arguments,
                    "machine_instance_id": self._machine_instance_id,
                },
            )
```

**Step 4: Run the test to verify it passes**

```bash
cd services/svc-orchestrator && python -m pytest tests/test_orchestrator.py::TestMachineInstanceIdForwarding -v
```

Expected: PASS (2 tests)

**Step 5: Run all orchestrator tests for regressions**

```bash
cd services/svc-orchestrator && python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add services/svc-orchestrator/src/svc_orchestrator/app.py services/svc-orchestrator/src/svc_orchestrator/orchestrator.py services/svc-orchestrator/tests/test_orchestrator.py && git commit -m "feat(orchestrator): forward machine_instance_id in all tool dispatch requests"
```

---

## Task 6: Remove svc-bash, svc-filesystem, svc-search from hardcoded AGENTS dict and DEFAULT_SERVICES

**Files:**
- Modify: `services/session-service/src/session_service/agents.py` (lines 15-78, the `AGENTS` dict)
- Modify: `services/session-service/src/session_service/app.py` (lines 62-78, the `DEFAULT_SERVICES` list)
- Modify: `services/session-service/tests/test_session_create.py` (append new test class)

**Step 1: Write the failing test**

Append to `services/session-service/tests/test_session_create.py`:

```python
class TestOldServicesRemoved:
    """Verify svc-bash, svc-filesystem, svc-search are removed from hardcoded lists."""

    def test_default_services_excludes_old_proxy_services(self) -> None:
        """DEFAULT_SERVICES does not include svc-bash, svc-filesystem, svc-search."""
        from session_service.app import DEFAULT_SERVICES

        removed = {"svc-bash", "svc-filesystem", "svc-search"}
        for svc in removed:
            assert svc not in DEFAULT_SERVICES, f"{svc} should be removed from DEFAULT_SERVICES"

    def test_agents_dict_excludes_old_proxy_services(self) -> None:
        """AGENTS dict entries do not include svc-bash, svc-filesystem, svc-search."""
        from session_service.agents import AGENTS

        removed = {"svc-bash", "svc-filesystem", "svc-search"}
        for agent_name, agent_config in AGENTS.items():
            services = agent_config.get("services", [])
            for svc in removed:
                assert svc not in services, (
                    f"{svc} should be removed from AGENTS['{agent_name}']['services']"
                )

    def test_agents_dict_includes_svc_machine(self) -> None:
        """AGENTS dict entries include svc-machine as the replacement."""
        from session_service.agents import AGENTS

        for agent_name, agent_config in AGENTS.items():
            services = agent_config.get("services", [])
            assert "svc-machine" in services, (
                f"AGENTS['{agent_name}']['services'] should include svc-machine"
            )
```

**Step 2: Run the test to verify it fails**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py::TestOldServicesRemoved -v
```

Expected: FAIL — `svc-bash` is still in the lists

**Step 3: Write the implementation**

**3a.** In `services/session-service/src/session_service/app.py`, change `DEFAULT_SERVICES` (lines 62-78) from:

```python
DEFAULT_SERVICES: list[str] = [
    "svc-bash",
    "svc-filesystem",
    "svc-search",
    "svc-web",
    "svc-skills",
    "svc-todo",
    "svc-modes",
    "svc-mock-provider",
    "svc-providers",
    # Phase 3b: delegation and hook services
    "svc-delegation",
    "svc-hooks-approval",
    "svc-hooks-routing",
    "svc-hooks-async",
    "svc-hooks-shell",
]
```

to:

```python
DEFAULT_SERVICES: list[str] = [
    "svc-machine",
    "svc-web",
    "svc-skills",
    "svc-todo",
    "svc-modes",
    "svc-mock-provider",
    "svc-providers",
    # Phase 3b: delegation and hook services
    "svc-delegation",
    "svc-hooks-approval",
    "svc-hooks-routing",
    "svc-hooks-async",
    "svc-hooks-shell",
]
```

**3b.** In `services/session-service/src/session_service/agents.py`, update the `AGENTS` dict. In both the `"default"` and `"foundation"` entries, replace the three lines:

```python
            "svc-bash",
            "svc-filesystem",
            "svc-search",
```

with the single line:

```python
            "svc-machine",
```

**Step 4: Run the test to verify it passes**

```bash
cd services/session-service && python -m pytest tests/test_session_create.py::TestOldServicesRemoved -v
```

Expected: PASS (3 tests)

**Step 5: Run all session-service tests for regressions**

```bash
cd services/session-service && python -m pytest tests/ -v
```

Expected: ALL PASS (some tests that reference `svc-bash` in assertions may need updating — fix any that fail)

**Step 6: Commit**

```bash
git add services/session-service/src/session_service/app.py services/session-service/src/session_service/agents.py services/session-service/tests/ && git commit -m "refactor(session): replace svc-bash/filesystem/search with svc-machine in service lists"
```

---

## Task 7: Add create_session() method to CLI SessionClient

**Files:**
- Modify: `amplifier-cli/src/amplifier_cli/client.py` (add `create_session()` method after `close()`, around line 77)
- Modify: `amplifier-cli/tests/test_client.py` (append new test class)

**Step 1: Write the failing test**

Append to `amplifier-cli/tests/test_client.py`:

```python
class TestCreateSession:
    """Tests for SessionClient.create_session()."""

    async def test_create_session_calls_correct_endpoint(self) -> None:
        """create_session() performs POST /sessions/create with agent_ref and machine_config."""
        captured_bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/sessions/create"
            body = json.loads(request.content)
            captured_bodies.append(body)
            return httpx.Response(
                200,
                json={"session_id": "sess-new-123", "machine_instance_id": "inst-abc"},
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.create_session(
                agent_ref="foundation",
                machine_config={"type": "ssh", "host": "localhost", "working_dir": "/tmp"},
            )

        assert result["session_id"] == "sess-new-123"
        assert result["machine_instance_id"] == "inst-abc"
        assert captured_bodies[0]["agent_ref"] == "foundation"
        assert captured_bodies[0]["machine_config"]["host"] == "localhost"

    async def test_create_session_without_machine_config(self) -> None:
        """create_session() works without machine_config (sends null)."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body.get("machine_config") is None
            return httpx.Response(
                200,
                json={"session_id": "sess-no-machine", "machine_instance_id": None},
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.create_session(agent_ref="default")

        assert result["session_id"] == "sess-no-machine"
        assert result["machine_instance_id"] is None

    async def test_create_session_default_machine_config(self) -> None:
        """create_session() with use_default_machine=True sends localhost SSH config."""
        captured_bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            captured_bodies.append(body)
            return httpx.Response(
                200,
                json={"session_id": "sess-default", "machine_instance_id": "inst-local"},
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.create_session(
                agent_ref="foundation",
                use_default_machine=True,
            )

        mc = captured_bodies[0]["machine_config"]
        assert mc["type"] == "ssh"
        assert mc["host"] == "localhost"
        assert "working_dir" in mc
```

**Step 2: Run the test to verify it fails**

```bash
cd amplifier-cli && python -m pytest tests/test_client.py::TestCreateSession -v
```

Expected: FAIL — `AttributeError: 'SessionClient' object has no attribute 'create_session'`

**Step 3: Write the implementation**

In `amplifier-cli/src/amplifier_cli/client.py`, add `import os` at the top (after `import json` on line 5), then add this method to the `SessionClient` class after the `__aexit__` method (after line 77):

```python
    async def create_session(
        self,
        agent_ref: str = "default",
        machine_config: dict[str, Any] | None = None,
        use_default_machine: bool = False,
    ) -> dict[str, Any]:
        """Create a new session, optionally provisioning a machine instance.

        POST /sessions/create

        Args:
            agent_ref: The agent name to use for this session.
            machine_config: Explicit machine configuration dict. Takes
                precedence over *use_default_machine*.
            use_default_machine: If True and *machine_config* is None,
                sends a default localhost SSH config using the current
                working directory.

        Returns:
            Response dict with ``session_id`` and ``machine_instance_id``.
        """
        if machine_config is None and use_default_machine:
            machine_config = {
                "type": "ssh",
                "host": "localhost",
                "working_dir": os.getcwd(),
            }

        body: dict[str, Any] = {"agent_ref": agent_ref, "machine_config": machine_config}
        http = self._get_http()
        response = await http.post("/sessions/create", json=body, timeout=30.0)
        response.raise_for_status()
        return response.json()
```

**Step 4: Run the test to verify it passes**

```bash
cd amplifier-cli && python -m pytest tests/test_client.py::TestCreateSession -v
```

Expected: PASS (3 tests)

**Step 5: Run all CLI tests for regressions**

```bash
cd amplifier-cli && python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add amplifier-cli/src/amplifier_cli/client.py amplifier-cli/tests/test_client.py && git commit -m "feat(cli): add create_session() method to SessionClient"
```

---

## Task 8: CLI REPL calls create_session() before first turn

**Files:**
- Modify: `amplifier-cli/src/amplifier_cli/repl.py` (the `interactive_repl` function, lines 179-196)
- Modify: `amplifier-cli/tests/test_repl.py` (add new test)

**Step 1: Write the failing test**

First, read the existing `amplifier-cli/tests/test_repl.py` to understand the test conventions. Then append to it:

```python
from unittest.mock import AsyncMock, patch, MagicMock


class TestReplCallsCreateSession:
    """Verify the REPL calls create_session() at startup."""

    async def test_repl_calls_create_session_on_start(self) -> None:
        """interactive_repl calls client.create_session() before entering the loop."""
        from amplifier_cli.repl import interactive_repl
        from rich.console import Console

        mock_client = AsyncMock()
        mock_client.create_session = AsyncMock(
            return_value={"session_id": "sess-created", "machine_instance_id": "inst-1"}
        )
        mock_client.stream_turn = AsyncMock(return_value=AsyncMock(__aiter__=AsyncMock(return_value=iter([]))))

        console = Console(file=MagicMock(), force_terminal=False)

        # Patch prompt_async to simulate user typing "exit" immediately
        with patch("amplifier_cli.repl._create_prompt_session") as mock_ps:
            mock_session = MagicMock()
            mock_session.prompt_async = AsyncMock(side_effect=["exit"])
            mock_ps.return_value = mock_session

            await interactive_repl(
                client=mock_client,
                session_id="will-be-replaced",
                provider_name="mock",
                workspace_content=None,
                console=console,
                agent_ref="foundation",
            )

        mock_client.create_session.assert_awaited_once()
        call_kwargs = mock_client.create_session.call_args[1]
        assert call_kwargs["agent_ref"] == "foundation"
        assert call_kwargs["use_default_machine"] is True
```

**Step 2: Run the test to verify it fails**

```bash
cd amplifier-cli && python -m pytest tests/test_repl.py::TestReplCallsCreateSession -v
```

Expected: FAIL — `create_session` not called (current REPL doesn't call it)

**Step 3: Write the implementation**

In `amplifier-cli/src/amplifier_cli/repl.py`, modify the `interactive_repl` function. After the line `console.print(Panel(BANNER.strip(), title="Amplifier IPC REPL", expand=False))` (line 196) and before `session = _create_prompt_session(history_path)` (line 198), add session creation:

```python
    # Create session via the session-service (provisions machine instance if needed)
    try:
        create_result = await client.create_session(
            agent_ref=agent_ref or "default",
            use_default_machine=True,
        )
        session_id = create_result["session_id"]
    except Exception as exc:
        console.print(f"[yellow]Warning: session creation failed ({exc}), using local session ID[/yellow]")
```

**Step 4: Run the test to verify it passes**

```bash
cd amplifier-cli && python -m pytest tests/test_repl.py::TestReplCallsCreateSession -v
```

Expected: PASS

**Step 5: Run all CLI tests for regressions**

```bash
cd amplifier-cli && python -m pytest tests/ -v
```

Expected: ALL PASS (existing tests don't call `interactive_repl` or mock `create_session` already)

**Step 6: Commit**

```bash
git add amplifier-cli/src/amplifier_cli/repl.py amplifier-cli/tests/test_repl.py && git commit -m "feat(cli): REPL calls create_session() at startup with default machine config"
```

---

## Task 9: Run full test suites and fix regressions

**Files:** No new files — verification and fix step.

**Step 1: Run session-service tests**

```bash
cd services/session-service && python -m pytest tests/ -v --tb=short
```

Expected: ALL PASS. If any tests fail due to `svc-bash` references in assertions (e.g., `test_caller_supplied_services_take_priority` in `test_app_agent.py` uses `"svc-bash"` in a custom services list), update those test fixtures to use `"svc-machine"` instead.

**Step 2: Run orchestrator tests**

```bash
cd services/svc-orchestrator && python -m pytest tests/ -v --tb=short
```

Expected: ALL PASS.

**Step 3: Run CLI tests**

```bash
cd amplifier-cli && python -m pytest tests/ -v --tb=short
```

Expected: ALL PASS.

**Step 4: Run linting on all changed files**

```bash
python -m ruff check services/session-service/src/ services/session-service/tests/ services/svc-orchestrator/src/ services/svc-orchestrator/tests/ amplifier-cli/src/ amplifier-cli/tests/ && python -m ruff format --check services/session-service/src/ services/session-service/tests/ services/svc-orchestrator/src/ services/svc-orchestrator/tests/ amplifier-cli/src/ amplifier-cli/tests/
```

Fix any lint or format issues found.

**Step 5: Commit any fixes**

```bash
git add -A && git commit -m "fix: lint and regression fixes for Phase 2 session lifecycle"
```

(Skip this commit if no fixes were needed.)

---

## Summary

After completing all 9 tasks, the system has:

1. **Session-service `POST /sessions/create`** — Creates a session, resolves agent config, discovers services, provisions a machine instance via Dapr call to the machine service, and stores `machine_instance_id` in session state.

2. **Turn payload enrichment** — Every turn payload to the orchestrator includes `machine_instance_id` as a top-level field (null when no machine).

3. **Machine instance cleanup** — `POST /sessions/{id}/clear` destroys the machine instance via `DELETE /instances/{id}` on the machine service before resetting session state.

4. **Orchestrator forwarding** — The orchestrator includes `machine_instance_id` in every tool dispatch request body. Machine tools use it; non-machine tools ignore it.

5. **Service list consolidation** — `svc-bash`, `svc-filesystem`, `svc-search` replaced with `svc-machine` in both `DEFAULT_SERVICES` and the hardcoded `AGENTS` dict.

6. **CLI `create_session()`** — The `SessionClient` has a `create_session()` method that calls `POST /sessions/create` with agent ref and machine config.

7. **CLI REPL integration** — The REPL calls `create_session()` at startup with `use_default_machine=True`, defaulting to `{type: "ssh", host: "localhost", working_dir: <cwd>}`.

**Not done yet (Phase 3):**
- Agent definition YAML changes (removing bash/filesystem/search entries, adding machine behavior)
- ampctl compose changes (stop generating svc-bash/filesystem/search containers)
- Service-map generation changes (machine behavior routes all tool names)
- Deleting old service directories (svc-bash, svc-filesystem, svc-search)
- Full-stack integration tests