# IPC Event Parity — Phase 1 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Unblock the 6+ hooks that subscribe to `session:start`, `session:end`, `provider:response`, and `content_block:start/end` but never receive events — restoring audit logging, routing matrix initialization, and streaming UI support.

**Architecture:** The Host emits session lifecycle events (`session:start`, `session:end`) directly through the Router — same dispatch path as `request.hook_emit` but without IPC indirection. The streaming orchestrator emits turn-level events (`provider:response`, `content_block:start/end`) via its existing `_hook_emit()` mechanism. All event name strings come from a shared constants module so emitters and subscribers can never disagree on naming.

**Tech Stack:** Python 3.11+, Pydantic, pytest with `asyncio_mode="auto"`, uv for package management.

**Design doc:** `docs/plans/2026-03-25-ipc-event-parity-design.md`

---

## Task 1: Create Events Constants Module

**Files:**
- Create: `amplifier-ipc-protocol/pyproject.toml`
- Create: `amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py`
- Create: `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py`
- Modify: `pyproject.toml` (root) — add dependency + uv source
- Modify: `services/amplifier-foundation/pyproject.toml` — add dependency + uv source

**Step 1: Create the package directory structure**

```bash
mkdir -p amplifier-ipc-protocol/src/amplifier_ipc_protocol
```

**Step 2: Create `amplifier-ipc-protocol/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-ipc-protocol"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_ipc_protocol"]
```

**Step 3: Create `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py`**

All 41 canonical event constants. Names match the old `amplifier_core.events` module.

```python
"""Canonical event constants for the Amplifier IPC event system.

All 41 events are defined here as the single source of truth.  Both the Host
(session lifecycle) and orchestrator services (turn-level) import from this
module so emitters and subscribers always agree on event names.
"""

# ---------------------------------------------------------------------------
# Session Lifecycle
# ---------------------------------------------------------------------------
SESSION_START = "session:start"
SESSION_END = "session:end"
SESSION_FORK = "session:fork"
SESSION_RESUME = "session:resume"

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
PROMPT_SUBMIT = "prompt:submit"
PROMPT_COMPLETE = "prompt:complete"

# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
PLAN_START = "plan:start"
PLAN_END = "plan:end"

# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------
PROVIDER_REQUEST = "provider:request"
PROVIDER_RESPONSE = "provider:response"
PROVIDER_RETRY = "provider:retry"
PROVIDER_ERROR = "provider:error"
PROVIDER_THROTTLE = "provider:throttle"
PROVIDER_TOOL_SEQUENCE_REPAIRED = "provider:tool_sequence_repaired"
PROVIDER_RESOLVE = "provider:resolve"

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
LLM_REQUEST = "llm:request"
LLM_RESPONSE = "llm:response"

# ---------------------------------------------------------------------------
# Content Blocks
# ---------------------------------------------------------------------------
CONTENT_BLOCK_START = "content_block:start"
CONTENT_BLOCK_DELTA = "content_block:delta"
CONTENT_BLOCK_END = "content_block:end"

# ---------------------------------------------------------------------------
# Thinking
# ---------------------------------------------------------------------------
THINKING_DELTA = "thinking:delta"
THINKING_FINAL = "thinking:final"

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
TOOL_PRE = "tool:pre"
TOOL_POST = "tool:post"
TOOL_ERROR = "tool:error"

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
CONTEXT_PRE_COMPACT = "context:pre_compact"
CONTEXT_POST_COMPACT = "context:post_compact"
CONTEXT_COMPACTION = "context:compaction"
CONTEXT_INCLUDE = "context:include"

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
ORCHESTRATOR_COMPLETE = "orchestrator:complete"
EXECUTION_START = "execution:start"
EXECUTION_END = "execution:end"

# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
USER_NOTIFICATION = "user:notification"

# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------
ARTIFACT_WRITE = "artifact:write"
ARTIFACT_READ = "artifact:read"

# ---------------------------------------------------------------------------
# Policy / Approvals
# ---------------------------------------------------------------------------
POLICY_VIOLATION = "policy:violation"
APPROVAL_REQUIRED = "approval:required"
APPROVAL_GRANTED = "approval:granted"
APPROVAL_DENIED = "approval:denied"

# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------
CANCEL_REQUESTED = "cancel:requested"
CANCEL_COMPLETED = "cancel:completed"
```

**Step 4: Create `amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py`**

Re-export all event constants (follows the re-export pattern from `src/amplifier_ipc/protocol/__init__.py`):

```python
"""amplifier-ipc-protocol: Shared event constants for the Amplifier IPC system."""

from amplifier_ipc_protocol.events import (
    APPROVAL_DENIED,
    APPROVAL_GRANTED,
    APPROVAL_REQUIRED,
    ARTIFACT_READ,
    ARTIFACT_WRITE,
    CANCEL_COMPLETED,
    CANCEL_REQUESTED,
    CONTENT_BLOCK_DELTA,
    CONTENT_BLOCK_END,
    CONTENT_BLOCK_START,
    CONTEXT_COMPACTION,
    CONTEXT_INCLUDE,
    CONTEXT_POST_COMPACT,
    CONTEXT_PRE_COMPACT,
    EXECUTION_END,
    EXECUTION_START,
    LLM_REQUEST,
    LLM_RESPONSE,
    ORCHESTRATOR_COMPLETE,
    PLAN_END,
    PLAN_START,
    POLICY_VIOLATION,
    PROMPT_COMPLETE,
    PROMPT_SUBMIT,
    PROVIDER_ERROR,
    PROVIDER_REQUEST,
    PROVIDER_RESOLVE,
    PROVIDER_RESPONSE,
    PROVIDER_RETRY,
    PROVIDER_THROTTLE,
    PROVIDER_TOOL_SEQUENCE_REPAIRED,
    SESSION_END,
    SESSION_FORK,
    SESSION_RESUME,
    SESSION_START,
    THINKING_DELTA,
    THINKING_FINAL,
    TOOL_ERROR,
    TOOL_POST,
    TOOL_PRE,
    USER_NOTIFICATION,
)

__all__ = [
    "SESSION_START", "SESSION_END", "SESSION_FORK", "SESSION_RESUME",
    "PROMPT_SUBMIT", "PROMPT_COMPLETE",
    "PLAN_START", "PLAN_END",
    "PROVIDER_REQUEST", "PROVIDER_RESPONSE", "PROVIDER_RETRY", "PROVIDER_ERROR",
    "PROVIDER_THROTTLE", "PROVIDER_TOOL_SEQUENCE_REPAIRED", "PROVIDER_RESOLVE",
    "LLM_REQUEST", "LLM_RESPONSE",
    "CONTENT_BLOCK_START", "CONTENT_BLOCK_DELTA", "CONTENT_BLOCK_END",
    "THINKING_DELTA", "THINKING_FINAL",
    "TOOL_PRE", "TOOL_POST", "TOOL_ERROR",
    "CONTEXT_PRE_COMPACT", "CONTEXT_POST_COMPACT", "CONTEXT_COMPACTION", "CONTEXT_INCLUDE",
    "ORCHESTRATOR_COMPLETE", "EXECUTION_START", "EXECUTION_END",
    "USER_NOTIFICATION",
    "ARTIFACT_WRITE", "ARTIFACT_READ",
    "POLICY_VIOLATION", "APPROVAL_REQUIRED", "APPROVAL_GRANTED", "APPROVAL_DENIED",
    "CANCEL_REQUESTED", "CANCEL_COMPLETED",
]
```

**Step 5: Wire up dependencies**

In **`pyproject.toml`** (root), add the dependency and uv source:

```
# Under [project] dependencies, add:
"amplifier-ipc-protocol",

# Add new section:
[tool.uv.sources]
amplifier-ipc-protocol = { path = "amplifier-ipc-protocol" }

# Under [tool.pyright] extraPaths, add the new package:
extraPaths = ["src", "amplifier-ipc-protocol/src"]
```

In **`services/amplifier-foundation/pyproject.toml`**, add the dependency and uv source:

```
# Under [project] dependencies, add:
"amplifier-ipc-protocol",

# Under [tool.uv.sources], add:
amplifier-ipc-protocol = { path = "../../amplifier-ipc-protocol" }

# Under [tool.pyright] extraPaths, add:
extraPaths = ["src", "../../amplifier-ipc-protocol/src"]
```

**Step 6: Install the new package**

Run from the repo root:
```bash
uv sync
```

Then from the foundation service:
```bash
cd services/amplifier-foundation && uv sync && cd ../..
```

**Step 7: Verify imports work**

```bash
python -c "from amplifier_ipc_protocol.events import SESSION_START, CONTENT_BLOCK_START; print(SESSION_START, CONTENT_BLOCK_START)"
```
Expected: `session:start content_block:start`

**Step 8: Commit**

```bash
git add amplifier-ipc-protocol/ pyproject.toml services/amplifier-foundation/pyproject.toml
git commit -m "feat: add amplifier-ipc-protocol package with 41 canonical event constants"
```

---

## Task 2: Add Host._emit_hook_event() Helper + parent_session_id

**Files:**
- Modify: `src/amplifier_ipc/host/host.py` — add `parent_session_id` param and `_emit_hook_event()` method
- Create: `tests/host/test_session_events.py` — unit tests for the helper

**Step 1: Write the failing tests**

Create `tests/host/test_session_events.py`:

```python
"""Tests for Host session event emission (session:start, session:end)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from amplifier_ipc.host.config import HostSettings, SessionConfig
from amplifier_ipc.host.host import Host


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_host(**kwargs: Any) -> Host:
    """Create a Host with minimal valid config for unit tests."""
    config = SessionConfig(
        services=["svc"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )
    return Host(config=config, settings=HostSettings(), **kwargs)


# ---------------------------------------------------------------------------
# _emit_hook_event unit tests
# ---------------------------------------------------------------------------


async def test_emit_hook_event_dispatches_to_router() -> None:
    """_emit_hook_event calls router.route_request with the correct params."""
    host = _make_host()

    mock_router = MagicMock()
    mock_router.route_request = AsyncMock(return_value={"action": "CONTINUE"})
    host._router = mock_router

    await host._emit_hook_event("session:start", {"session_id": "abc"})

    mock_router.route_request.assert_called_once_with(
        "request.hook_emit",
        {"event": "session:start", "data": {"session_id": "abc"}},
    )


async def test_emit_hook_event_swallows_exceptions() -> None:
    """_emit_hook_event must not propagate exceptions — it logs and continues."""
    host = _make_host()

    mock_router = MagicMock()
    mock_router.route_request = AsyncMock(side_effect=RuntimeError("hook exploded"))
    host._router = mock_router

    # Must NOT raise
    await host._emit_hook_event("session:start", {"session_id": "abc"})


async def test_emit_hook_event_noop_without_router() -> None:
    """_emit_hook_event is a silent no-op when the router has not been built yet."""
    host = _make_host()
    assert host._router is None

    # Must NOT raise
    await host._emit_hook_event("session:start", {"session_id": "abc"})
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/host/test_session_events.py -v
```
Expected: FAIL — `AttributeError: 'Host' object has no attribute '_emit_hook_event'`

**Step 3: Add `parent_session_id` parameter and `_emit_hook_event()` method to Host**

In `src/amplifier_ipc/host/host.py`, add `parent_session_id` to `__init__`:

Find this block (lines 74–83):
```python
    def __init__(
        self,
        config: SessionConfig,
        settings: HostSettings,
        session_dir: Path | None = None,
        service_configs: dict[str, Any] | None = None,
        shared_services: dict[str, Any] | None = None,
        shared_registry: ServiceIndex | None = None,
        spawn_depth: int = 0,
    ) -> None:
```

Replace with:
```python
    def __init__(
        self,
        config: SessionConfig,
        settings: HostSettings,
        session_dir: Path | None = None,
        service_configs: dict[str, Any] | None = None,
        shared_services: dict[str, Any] | None = None,
        shared_registry: ServiceIndex | None = None,
        spawn_depth: int = 0,
        parent_session_id: str | None = None,
    ) -> None:
```

Add this line after `self._resume_session_id: str | None = None` (line 114):
```python
        self._parent_session_id: str | None = parent_session_id
```

Then add the `_emit_hook_event` method. Place it right after the `_session_id` / `_resume_session_id` / `_parent_session_id` block, before the `# Public API` section comment (around line 116). Add it as a new section:

```python
    # ------------------------------------------------------------------
    # Hook event emission (session-level)
    # ------------------------------------------------------------------

    async def _emit_hook_event(self, event_name: str, data: dict[str, Any]) -> None:
        """Emit a hook event through the Router, swallowing errors.

        Uses the same dispatch path as ``request.hook_emit`` from the
        orchestrator, but without IPC indirection.  Errors are logged
        but never propagated — a failing hook must not crash the session.
        """
        if self._router is None:
            return
        try:
            await self._router.route_request(
                "request.hook_emit", {"event": event_name, "data": data}
            )
        except Exception:
            logger.exception("Failed to emit hook event %r", event_name)
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/host/test_session_events.py -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add src/amplifier_ipc/host/host.py tests/host/test_session_events.py
git commit -m "feat: add Host._emit_hook_event() helper and parent_session_id param"
```

---

## Task 3: Emit session:start in Host.run()

**Files:**
- Modify: `src/amplifier_ipc/host/host.py` — add session:start emission after router build
- Modify: `tests/host/test_session_events.py` — add integration test

**Step 1: Write the failing test**

Append to `tests/host/test_session_events.py`:

```python
from unittest.mock import patch

from amplifier_ipc.host.service_index import ServiceIndex


class FakeClient:
    """Records calls and returns canned responses."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._responses: dict[str, Any] = responses or {}

    async def request(self, method: str, params: Any = None) -> Any:
        self.calls.append((method, params))
        return self._responses.get(method, {})


class FakeService:
    """Minimal service stub with a FakeClient."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client


def _make_host_with_registry(tmp_path: Any, **host_kwargs: Any) -> tuple[Host, MagicMock]:
    """Create a Host with populated registry and shared services.

    Returns (host, mock_emit) where mock_emit replaces _emit_hook_event.
    """
    config = SessionConfig(
        services=["svc"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )

    registry = ServiceIndex()
    registry.register("svc", {
        "tools": [],
        "hooks": [],
        "orchestrators": [{"name": "streaming"}],
        "context_managers": [{"name": "simple"}],
        "providers": [{"name": "anthropic"}],
        "content": [],
    })

    svc_client = FakeClient()
    svc = FakeService(svc_client)

    host = Host(
        config=config,
        settings=HostSettings(),
        session_dir=tmp_path,
        shared_services={"svc": svc},
        shared_registry=registry,
        **host_kwargs,
    )
    return host


async def _drain(host: Host, prompt: str) -> list[tuple[str, dict[str, Any]]]:
    """Run host.run() and collect all _emit_hook_event calls.

    Patches _orchestrator_loop to yield nothing (skips the real subprocess),
    and patches assemble_system_prompt.  Returns the list of
    (event_name, data) tuples passed to _emit_hook_event.
    """
    emitted: list[tuple[str, dict[str, Any]]] = []
    original_emit = host._emit_hook_event

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        emitted.append((event_name, data))

    async def fake_loop(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        return
        yield  # makes this an async generator

    host._emit_hook_event = capture_emit  # type: ignore[assignment]

    with (
        patch(
            "amplifier_ipc.host.host.assemble_system_prompt",
            new_callable=AsyncMock,
            return_value="system prompt",
        ),
        patch.object(host, "_orchestrator_loop", side_effect=fake_loop),
    ):
        async for _ in host.run(prompt):
            pass

    return emitted


async def test_run_emits_session_start(tmp_path: Any) -> None:
    """Host.run() emits session:start with session_id, parent_id, and raw config."""
    host = _make_host_with_registry(tmp_path)

    emitted = await _drain(host, "hello")

    start_events = [(e, d) for e, d in emitted if e == "session:start"]
    assert len(start_events) == 1, f"Expected 1 session:start, got {len(start_events)}"

    data = start_events[0][1]
    assert data["session_id"] == host._session_id
    assert data["parent_id"] is None
    assert "raw" in data
    # raw should contain the full SessionConfig dump
    assert data["raw"]["provider"] == "anthropic"
    assert data["raw"]["orchestrator"] == "streaming"


async def test_run_session_start_includes_parent_id(tmp_path: Any) -> None:
    """session:start includes parent_session_id when set."""
    host = _make_host_with_registry(tmp_path, parent_session_id="parent-123")

    emitted = await _drain(host, "hello")

    start_events = [(e, d) for e, d in emitted if e == "session:start"]
    assert len(start_events) == 1
    assert start_events[0][1]["parent_id"] == "parent-123"
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/host/test_session_events.py::test_run_emits_session_start -v
python -m pytest tests/host/test_session_events.py::test_run_session_start_includes_parent_id -v
```
Expected: FAIL — no session:start event emitted (emitted list is empty)

**Step 3: Add session:start emission to Host.run()**

In `src/amplifier_ipc/host/host.py`, add the import at the top of the file (with the other imports):

```python
from amplifier_ipc_protocol.events import SESSION_START, SESSION_END
```

Then, in the `run()` method, add the session:start emission **after** the router is built (after line 387, `self._router = Router(...)`) and **before** the resume session check (line 389, `if self._resume_session_id is not None:`).

Find this line:
```python
            # 5b. Resume session: restore previous transcript if resuming
```

Insert immediately before it:
```python
            # 5a. Emit session:start hook event
            await self._emit_hook_event(SESSION_START, {
                "session_id": self._session_id,
                "parent_id": self._parent_session_id,
                "raw": self._config.model_dump(),
            })

```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/host/test_session_events.py -v
```
Expected: 5 PASSED (3 from Task 2 + 2 new)

**Step 5: Commit**

```bash
git add src/amplifier_ipc/host/host.py tests/host/test_session_events.py
git commit -m "feat: emit session:start hook event in Host.run()"
```

---

## Task 4: Emit session:end in Host.run() finally Block

**Files:**
- Modify: `src/amplifier_ipc/host/host.py` — restructure try/except/finally to track status and emit session:end
- Modify: `tests/host/test_session_events.py` — add tests for completed, cancelled, and failed status

**Step 1: Write the failing tests**

Append to `tests/host/test_session_events.py`:

```python
import asyncio


async def test_run_emits_session_end_completed(tmp_path: Any) -> None:
    """Host.run() emits session:end with status='completed' on normal exit."""
    host = _make_host_with_registry(tmp_path)

    emitted = await _drain(host, "hello")

    end_events = [(e, d) for e, d in emitted if e == "session:end"]
    assert len(end_events) == 1, f"Expected 1 session:end, got {len(end_events)}"

    data = end_events[0][1]
    assert data["session_id"] == host._session_id
    assert data["status"] == "completed"


async def test_run_emits_session_end_failed(tmp_path: Any) -> None:
    """Host.run() emits session:end with status='failed' when an exception occurs."""
    host = _make_host_with_registry(tmp_path)

    emitted: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        emitted.append((event_name, data))

    async def exploding_loop(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        raise RuntimeError("orchestrator crashed")
        yield  # makes this an async generator  # noqa: RUF027

    host._emit_hook_event = capture_emit  # type: ignore[assignment]

    with (
        patch(
            "amplifier_ipc.host.host.assemble_system_prompt",
            new_callable=AsyncMock,
            return_value="system prompt",
        ),
        patch.object(host, "_orchestrator_loop", side_effect=exploding_loop),
        pytest.raises(RuntimeError, match="orchestrator crashed"),
    ):
        async for _ in host.run("hello"):
            pass

    end_events = [(e, d) for e, d in emitted if e == "session:end"]
    assert len(end_events) == 1
    assert end_events[0][1]["status"] == "failed"


async def test_run_emits_session_end_cancelled(tmp_path: Any) -> None:
    """Host.run() emits session:end with status='cancelled' on CancelledError."""
    host = _make_host_with_registry(tmp_path)

    emitted: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        emitted.append((event_name, data))

    async def cancelled_loop(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        raise asyncio.CancelledError()
        yield  # makes this an async generator  # noqa: RUF027

    host._emit_hook_event = capture_emit  # type: ignore[assignment]

    with (
        patch(
            "amplifier_ipc.host.host.assemble_system_prompt",
            new_callable=AsyncMock,
            return_value="system prompt",
        ),
        patch.object(host, "_orchestrator_loop", side_effect=cancelled_loop),
        pytest.raises(asyncio.CancelledError),
    ):
        async for _ in host.run("hello"):
            pass

    end_events = [(e, d) for e, d in emitted if e == "session:end"]
    assert len(end_events) == 1
    assert end_events[0][1]["status"] == "cancelled"
```

Also add the missing `pytest` import at the top of the file (it's not there yet):
```python
import pytest
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/host/test_session_events.py::test_run_emits_session_end_completed -v
python -m pytest tests/host/test_session_events.py::test_run_emits_session_end_failed -v
python -m pytest tests/host/test_session_events.py::test_run_emits_session_end_cancelled -v
```
Expected: FAIL — no session:end event emitted

**Step 3: Restructure Host.run() try/except/finally**

In `src/amplifier_ipc/host/host.py`, find the `run()` method's try block. The current structure is:

```python
        try:
            # 1b. Load shared state from persistence
            self._state = self._persistence.load_state()
            ...
            # 8. Save state, metadata, and finalize
            ...
        finally:
            await self._teardown_services()
```

Replace with a try/except/finally that tracks status:

Find this exact block:
```python
        try:
            # 1b. Load shared state from persistence
            self._state = self._persistence.load_state()
```

Replace with:
```python
        _session_status = "completed"
        try:
            # 1b. Load shared state from persistence
            self._state = self._persistence.load_state()
```

Then, find the `finally:` block (currently just `await self._teardown_services()`):

```python
        finally:
            await self._teardown_services()
```

Replace with:
```python
        except asyncio.CancelledError:
            _session_status = "cancelled"
            raise
        except Exception:
            _session_status = "failed"
            raise
        finally:
            await self._emit_hook_event(SESSION_END, {
                "session_id": self._session_id,
                "status": _session_status,
            })
            await self._teardown_services()
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/host/test_session_events.py -v
```
Expected: 8 PASSED

**Step 5: Run the full host test suite to check for regressions**

```bash
python -m pytest tests/host/ -v
```
Expected: All tests pass (the new except blocks re-raise, so existing behavior is preserved).

**Step 6: Commit**

```bash
git add src/amplifier_ipc/host/host.py tests/host/test_session_events.py
git commit -m "feat: emit session:end hook event with completed/cancelled/failed status"
```

---

## Task 5: Emit provider:response in Streaming Orchestrator

**Files:**
- Modify: `src/amplifier_ipc/host/host.py:711-714` — pass `provider_name` in config dict to orchestrator
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` — import constant, read provider name from config, emit provider:response after successful provider.complete
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py` — add test

**Step 1: Write the failing test**

Append to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
# ---------------------------------------------------------------------------
# Test: provider:response hook event emitted on successful provider call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_provider_response() -> None:
    """provider:response hook event emitted after successful provider.complete."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    provider_result = {
        "content": "Hello!",
        "text": "Hello!",
        "tool_calls": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "finish_reason": "end_turn",
    }

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": provider_result,
        }
    )

    config = {"provider_name": "anthropic"}
    result = await orch.execute("Hi", config, client)
    assert result == "Hello!"

    # Find the provider:response hook_emit call
    hook_calls = [
        (m, p) for m, p in client.requests
        if m == "request.hook_emit" and p.get("event") == "provider:response"
    ]
    assert len(hook_calls) == 1, (
        f"Expected 1 provider:response hook_emit, got {len(hook_calls)}. "
        f"All hook_emits: {[(m, p.get('event')) for m, p in client.requests if m == 'request.hook_emit']}"
    )

    data = hook_calls[0][1]["data"]
    assert data["provider"] == "anthropic"
    assert data["usage"] == {"input_tokens": 10, "output_tokens": 5}
```

**Step 2: Run test to verify it fails**

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_provider_response -v && cd ../..
```
Expected: FAIL — no provider:response hook_emit call found

**Step 3: Pass provider_name in config from Host to orchestrator**

In `src/amplifier_ipc/host/host.py`, find the config dict inside `_orchestrator_loop` (around line 711):

```python
                "config": {
                    "tools": self._registry.get_all_tool_specs(),
                    "hooks": self._registry.get_all_hook_descriptors(),
                },
```

Replace with:
```python
                "config": {
                    "tools": self._registry.get_all_tool_specs(),
                    "hooks": self._registry.get_all_hook_descriptors(),
                    "provider_name": self._config.provider or "unknown",
                },
```

**Step 4: Add provider:response emission to the streaming orchestrator**

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`:

First, add the import at the top of the file (after the existing imports, around line 28):
```python
from amplifier_ipc_protocol.events import (
    CONTENT_BLOCK_END,
    CONTENT_BLOCK_START,
    PROVIDER_RESPONSE,
)
```

Then, in the `execute()` method, read the provider name from config. Find this line (around line 116):
```python
        min_delay_ms: int = config.get("min_delay_between_calls_ms", 0)
```

Add after it:
```python
        provider_name: str = config.get("provider_name", "unknown")
```

Now add the provider:response emission. Find the line after the successful retry loop exit and before `chat_response = ChatResponse.model_validate(response_raw)`. The insertion point is right after `self._last_provider_call_end = time.monotonic()` (line 262). Find:

```python
            self._last_provider_call_end = time.monotonic()

            chat_response = ChatResponse.model_validate(response_raw)
```

Replace with:
```python
            self._last_provider_call_end = time.monotonic()

            chat_response = ChatResponse.model_validate(response_raw)

            # --- emit provider:response hook event ---
            await self._hook_emit(
                client,
                PROVIDER_RESPONSE,
                {
                    "provider": provider_name,
                    "response": response_raw,
                    "usage": chat_response.usage,
                },
            )
```

**Step 5: Run test to verify it passes**

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_provider_response -v && cd ../..
```
Expected: PASS

**Step 6: Run the full orchestrator test suite to check for regressions**

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```
Expected: All tests pass. Existing tests use `request.hook_emit: hook_continue()` which returns CONTINUE for all events including the new provider:response.

**Step 7: Commit**

```bash
git add src/amplifier_ipc/host/host.py services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat: emit provider:response hook event after successful provider.complete"
```

---

## Task 6: Fix content_block Naming and Emit content_block:start/end

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` — fix constant values, add hook emissions around content blocks
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py` — add tests

**Step 1: Write the failing tests**

Append to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
# ---------------------------------------------------------------------------
# Test: content_block constants match hook subscriptions
# ---------------------------------------------------------------------------


def test_content_block_constants_match_hook_subscriptions() -> None:
    """content_block constants must use underscore naming (content_block:start, not content:block_start)."""
    from amplifier_foundation.orchestrators.streaming import (  # type: ignore[import]
        CONTENT_BLOCK_END,
        CONTENT_BLOCK_START,
    )

    # These must match the subscription strings in StreamingUIHook
    assert CONTENT_BLOCK_START == "content_block:start", (
        f"CONTENT_BLOCK_START should be 'content_block:start', got {CONTENT_BLOCK_START!r}"
    )
    assert CONTENT_BLOCK_END == "content_block:end", (
        f"CONTENT_BLOCK_END should be 'content_block:end', got {CONTENT_BLOCK_END!r}"
    )


# ---------------------------------------------------------------------------
# Test: content_block:start/end hook events emitted for content blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_content_block_start_end() -> None:
    """content_block:start and content_block:end emitted for each content block."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    response_with_blocks = {
        "content": "Here is my answer.",
        "text": "Here is my answer.",
        "tool_calls": None,
        "usage": None,
        "finish_reason": None,
        "content_blocks": [
            {"type": "thinking", "thinking": "Let me reason..."},
            {"type": "text", "text": "Here is my answer."},
        ],
    }

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": response_with_blocks,
        }
    )

    result = await orch.execute("Think about this", {}, client)
    assert result == "Here is my answer."

    # Extract content_block hook_emit calls
    block_events = [
        (p["event"], p["data"])
        for m, p in client.requests
        if m == "request.hook_emit" and p.get("event", "").startswith("content_block:")
    ]

    # Should have 2 starts and 2 ends (one per content block)
    starts = [(e, d) for e, d in block_events if e == "content_block:start"]
    ends = [(e, d) for e, d in block_events if e == "content_block:end"]

    assert len(starts) == 2, f"Expected 2 content_block:start, got {len(starts)}: {starts}"
    assert len(ends) == 2, f"Expected 2 content_block:end, got {len(ends)}: {ends}"

    # Verify payload shape: block_type and index
    assert starts[0][1] == {"block_type": "thinking", "index": 0}
    assert starts[1][1] == {"block_type": "text", "index": 1}
    assert ends[0][1] == {"block_type": "thinking", "index": 0}
    assert ends[1][1] == {"block_type": "text", "index": 1}

    # Verify ordering: start(0) before end(0), start(1) before end(1)
    event_names = [p["event"] for m, p in client.requests if m == "request.hook_emit" and p.get("event", "").startswith("content_block:")]
    assert event_names == [
        "content_block:start", "content_block:end",
        "content_block:start", "content_block:end",
    ]
```

**Step 2: Run tests to verify they fail**

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_content_block_constants_match_hook_subscriptions -v && cd ../..
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_content_block_start_end -v && cd ../..
```
Expected: First test FAILS (constants have wrong values: `"content:block_start"` vs `"content_block:start"`). Second test FAILS (no content_block hook events emitted).

**Step 3: Fix the constant values**

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, find the broken constants (lines 46–47):

```python
CONTENT_BLOCK_START = "content:block_start"  # reserved for streaming block events
CONTENT_BLOCK_END = "content:block_end"  # reserved for streaming block events
```

Replace with imports from the protocol constants (these were already added in Task 5's import block). Remove the local definitions entirely:

```python
# CONTENT_BLOCK_START and CONTENT_BLOCK_END imported from amplifier_ipc_protocol.events
```

If the import from Task 5 isn't there yet (it should be), make sure the import block near the top of the file includes:
```python
from amplifier_ipc_protocol.events import (
    CONTENT_BLOCK_END,
    CONTENT_BLOCK_START,
    PROVIDER_RESPONSE,
)
```

**Step 4: Add content_block:start/end hook emissions around content block processing**

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, find the content blocks processing section (around line 270):

```python
            # --- stream thinking notifications (before stream.token) ---
            if chat_response.content_blocks:
                for block in chat_response.content_blocks:
                    if isinstance(block, ThinkingBlock):
                        thinking_text = block.thinking
                    elif isinstance(block, dict) and block.get("type") == "thinking":
                        thinking_text = block.get("thinking", "")
                    else:
                        continue
                    if thinking_text:
                        await client.send_notification(
                            STREAM_THINKING, {"thinking": thinking_text}
                        )
```

Replace with:
```python
            # --- stream content block + thinking notifications (before stream.token) ---
            if chat_response.content_blocks:
                for _block_idx, block in enumerate(chat_response.content_blocks):
                    # Determine block type for hook payload
                    if isinstance(block, dict):
                        _block_type = block.get("type", "unknown")
                    elif hasattr(block, "type"):
                        _block_type = block.type
                    else:
                        _block_type = "unknown"

                    await self._hook_emit(
                        client,
                        CONTENT_BLOCK_START,
                        {"block_type": _block_type, "index": _block_idx},
                    )

                    # Existing thinking block handling
                    if isinstance(block, ThinkingBlock):
                        thinking_text = block.thinking
                    elif isinstance(block, dict) and block.get("type") == "thinking":
                        thinking_text = block.get("thinking", "")
                    else:
                        thinking_text = None
                    if thinking_text:
                        await client.send_notification(
                            STREAM_THINKING, {"thinking": thinking_text}
                        )

                    await self._hook_emit(
                        client,
                        CONTENT_BLOCK_END,
                        {"block_type": _block_type, "index": _block_idx},
                    )
```

**Step 5: Run tests to verify they pass**

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_content_block_constants_match_hook_subscriptions tests/test_orchestrator.py::test_orchestrator_emits_content_block_start_end -v && cd ../..
```
Expected: 2 PASSED

**Step 6: Run the full orchestrator test suite to check for regressions**

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```
Expected: All tests pass. The thinking notification test (`test_orchestrator_emits_stream_thinking_for_thinking_blocks`) should still pass since the thinking logic is preserved inside the new block iteration.

**Step 7: Run the full host test suite too**

```bash
python -m pytest tests/host/ -v
```
Expected: All tests pass.

**Step 8: Commit**

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "fix: correct content_block naming and emit content_block:start/end hook events"
```

---

## Post-Implementation Verification

After all 6 tasks are complete, run the full test suites:

```bash
# Root test suite (host tests)
python -m pytest tests/ -v

# Foundation service tests
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..
```

All tests should pass with zero failures.

### What's Now Unblocked

After this phase, the following hooks will receive events they subscribe to:
- **LoggingHook** — receives `session:start`, `session:end`, `provider:response` → `events.jsonl` audit log now captures these
- **RoutingMatrixHook** — receives `session:start` → can now initialize routing tables
- **StreamingUIHook** — receives `provider:response`, `content_block:start`, `content_block:end` → can track model info and content blocks
- **DeprecationHook** — receives `session:start` → can fire deprecation warnings
- **RedactionHook** — receives `session:start` with `raw` config → can strip secrets via MODIFY response
- **ShellHook** — receives `session:start`, `session:end` → shell bridge gets lifecycle events

### Critical Detail: LoggingHook session_id

The LoggingHook's `_write_log()` function silently returns if `rec.get("session_id")` is falsy (see `services/amplifier-foundation/src/amplifier_foundation/hooks/logging.py:86-88`). The `session:start` payload includes `session_id` as a top-level key in `data`, and LoggingHook spreads `**data` into the record (`rec = {"schema": SCHEMA, "ts": _ts(), "event": event, **data}`), so `session_id` is present. This is correct by construction but worth verifying in integration tests in a future phase.