# IPC Event Parity — Phase 5 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Add the 8 policy + delegation event emissions (`approval:required`, `approval:granted`, `approval:denied`, `policy:violation`, `delegate:agent_spawned`, `delegate:agent_completed`, `delegate:agent_resumed`, `delegate:error`) so that hooks can observe approval decisions, mode-policy enforcement, and agent delegation lifecycle.

**Architecture:** Three subsystems gain event emission: (1) `_ApprovalCore` emits approval lifecycle events (`approval:required/granted/denied`) via an IPC client injected through the `ApprovalHook` proxy; (2) `ModeHooks` emits `policy:violation` whenever it returns DENY, via a newly-injected IPC client; (3) `DelegateTool` emits delegate lifecycle events (`delegate:agent_spawned/completed/resumed/error`) via its existing injected client. The protocol server's `_handle_hook_emit` is extended to inject client into hooks that declare a `client` attribute — the same pattern already used for tools and context managers.

**Tech Stack:** Python 3.11+, Pydantic, pytest with `@pytest.mark.asyncio`, uv for package management.

**Design doc:** `docs/plans/2026-03-25-ipc-event-parity-design.md`
**Phase 4 plan:** `docs/plans/2026-03-25-ipc-event-parity-phase4-plan.md`

---

## Context for the Implementer

### Files You'll Touch

| Action | Path |
|---|---|
| **Modify** | `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py` (135 lines) — add 4 delegate:* constants |
| **Modify** | `amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py` (112 lines) — re-export new constants |
| **Modify** | `src/amplifier_ipc/protocol/server.py` (878 lines) — inject client into hooks in `_handle_hook_emit` |
| **Modify** | `services/amplifier-foundation/src/amplifier_foundation/hooks/approval/approval_hook.py` (124 lines) — add client attribute, emit approval events |
| **Modify** | `services/amplifier-foundation/src/amplifier_foundation/hooks/approval_hook.py` (36 lines) — add client attribute, pass through to `_ApprovalCore` |
| **Modify** | `services/amplifier-modes/src/amplifier_modes/hooks/mode.py` (204 lines) — add client attribute, emit `policy:violation` |
| **Modify** | `services/amplifier-foundation/src/amplifier_foundation/tools/delegate.py` (116 lines) — emit delegate lifecycle events |
| **Create** | `services/amplifier-foundation/tests/test_approval_events.py` — tests for approval event emissions |
| **Create** | `services/amplifier-modes/tests/test_policy_events.py` — tests for policy:violation emission |
| **Modify** | `services/amplifier-foundation/tests/test_delegate.py` (151 lines) — add delegate event tests |

### Existing Patterns You Must Follow

**Client injection into tools** — The protocol server (`src/amplifier_ipc/protocol/server.py` lines 575–579) automatically injects an IPC client into any tool that has a `client` attribute:
```python
if (
    hasattr(tool_instance, "client")
    and self._current_orchestrator_client is not None
):
    tool_instance.client = self._current_orchestrator_client
```
`DelegateTool` already has `client: Any = None` (line 19 of `delegate.py`).

**Client injection into context managers** — Added in Phase 4 at `server.py` lines 663–664, same pattern applied to `_handle_context_get_messages`.

**Hook emission from tools/hooks** — Components with an injected client emit hook events via:
```python
await self.client.request("request.hook_emit", {"event": EVENT_CONSTANT, "data": {...}})
```
This is handled locally by `_OrchestratorLocalClient.request()` which routes to `self._server._handle_hook_emit()` — no IPC round-trip.

**Fire-and-forget pattern** — All event emissions are wrapped in try/except:
```python
if self.client is not None:
    try:
        await self.client.request("request.hook_emit", {"event": ..., "data": ...})
    except Exception:
        pass  # Hook emission must never affect the result
```

**Event constants** — Canonical events are defined in `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py`. The 4 approval/policy constants already exist (lines 69–73):
- `APPROVAL_REQUIRED = "approval:required"`
- `APPROVAL_GRANTED = "approval:granted"`
- `APPROVAL_DENIED = "approval:denied"`
- `POLICY_VIOLATION = "policy:violation"`

The 4 delegate:* constants are **NOT** yet defined — they are module-level custom events per the hybrid approach in the design doc. Despite being module-level, we define them in events.py for consistency (all constants in one place).

**Test pattern (foundation service tests)** — Tests use `@pytest.mark.asyncio`, direct imports, and `MockClient`/`FakeClient` to record `request()` calls:
```python
class MockClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, Any]] = []

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append((method, params))
        return {"action": "CONTINUE"}
```

**Test pattern (modes service tests)** — Tests in `services/amplifier-modes/tests/` import directly from `amplifier_modes.hooks.mode` and use `ModeDefinition`, `ModeHooks`. See `test_mode_operations.py` for examples.

**ApprovalHook proxy pattern** — `ApprovalHook` (in `hooks/approval_hook.py`) is the discoverable `@hook`-decorated class. It delegates all logic to `_ApprovalCore` (in `hooks/approval/approval_hook.py`). The client must be injected into `ApprovalHook` and passed through to `_ApprovalCore`.

### Running Tests

```bash
# Foundation service tests (approval events, delegate events)
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..

# Modes service tests (policy events)
cd services/amplifier-modes && python -m pytest tests/ -v && cd ../..

# Protocol server tests
python -m pytest tests/ -v
```

---

## Task 1: Add Delegate Event Constants to `events.py`

**Files:**
- Modify: `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py`
- Modify: `amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py`

### Step 1: Add 4 delegate:* constants to events.py

In `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py`, add a new section after the "Cancellation" constants (after line 77). Find:

```python
CANCEL_COMPLETED: str = "cancel:completed"

__all__ = [
```

Replace with:

```python
CANCEL_COMPLETED: str = "cancel:completed"

# Delegate (module-level custom events, defined here for consistency)
DELEGATE_AGENT_SPAWNED: str = "delegate:agent_spawned"
DELEGATE_AGENT_COMPLETED: str = "delegate:agent_completed"
DELEGATE_AGENT_RESUMED: str = "delegate:agent_resumed"
DELEGATE_ERROR: str = "delegate:error"

__all__ = [
```

### Step 2: Add delegate constants to `__all__` in events.py

In the same file, find the end of the `__all__` list (after `"CANCEL_COMPLETED"`):

```python
    "CANCEL_REQUESTED",
    "CANCEL_COMPLETED",
]
```

Replace with:

```python
    "CANCEL_REQUESTED",
    "CANCEL_COMPLETED",
    # Delegate
    "DELEGATE_AGENT_SPAWNED",
    "DELEGATE_AGENT_COMPLETED",
    "DELEGATE_AGENT_RESUMED",
    "DELEGATE_ERROR",
]
```

### Step 3: Re-export new constants from `__init__.py`

In `amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py`, add the 4 new imports. Find:

```python
    CONTENT_BLOCK_DELTA,
    CONTENT_BLOCK_END,
    CONTENT_BLOCK_START,
```

Replace with:

```python
    CONTENT_BLOCK_DELTA,
    CONTENT_BLOCK_END,
    CONTENT_BLOCK_START,
    DELEGATE_AGENT_COMPLETED,
    DELEGATE_AGENT_RESUMED,
    DELEGATE_AGENT_SPAWNED,
    DELEGATE_ERROR,
```

Then add to the `__all__` list in `__init__.py`. Find:

```python
    "CANCEL_REQUESTED",
    "CANCEL_COMPLETED",
]
```

Replace with:

```python
    "CANCEL_REQUESTED",
    "CANCEL_COMPLETED",
    # Delegate
    "DELEGATE_AGENT_SPAWNED",
    "DELEGATE_AGENT_COMPLETED",
    "DELEGATE_AGENT_RESUMED",
    "DELEGATE_ERROR",
]
```

### Step 4: Verify the constants are importable

```bash
python -c "from amplifier_ipc_protocol.events import DELEGATE_AGENT_SPAWNED, DELEGATE_AGENT_COMPLETED, DELEGATE_AGENT_RESUMED, DELEGATE_ERROR; print('OK:', DELEGATE_AGENT_SPAWNED, DELEGATE_AGENT_COMPLETED, DELEGATE_AGENT_RESUMED, DELEGATE_ERROR)"
```
Expected: `OK: delegate:agent_spawned delegate:agent_completed delegate:agent_resumed delegate:error`

### Step 5: Commit

```bash
git add amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py amplifier-ipc-protocol/src/amplifier_ipc_protocol/__init__.py
git commit -m "feat(events): add delegate:* event constants to events.py"
```

---

## Task 2: Inject Client into Hooks via Protocol Server

**Files:**
- Modify: `src/amplifier_ipc/protocol/server.py`

This task extends `_handle_hook_emit` to inject the orchestrator client into any hook that declares a `client` attribute — the same pattern already used for tools (line 575–579) and context managers (line 663–664). This is a prerequisite for Tasks 3 and 4 (approval and policy events).

### Step 1: Add client injection in `_handle_hook_emit`

In `src/amplifier_ipc/protocol/server.py`, find the hook dispatch loop in `_handle_hook_emit` (line 605):

```python
        for hook_instance in hooks:
            result: HookResult = await hook_instance.handle(event, data)
```

Replace with:

```python
        for hook_instance in hooks:
            # Inject orchestrator client so hooks can emit events
            if (
                hasattr(hook_instance, "client")
                and self._current_orchestrator_client is not None
            ):
                hook_instance.client = self._current_orchestrator_client
            result: HookResult = await hook_instance.handle(event, data)
```

### Step 2: Run existing tests to verify no regressions

```bash
python -m pytest tests/ -v
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..
```
Expected: All existing tests pass. The new client injection is a no-op for hooks that don't declare a `client` attribute.

### Step 3: Commit

```bash
git add src/amplifier_ipc/protocol/server.py
git commit -m "feat(events): inject orchestrator client into hooks that declare client attribute"
```

---

## Task 3: Emit `approval:required`, `approval:granted`, `approval:denied` from `_ApprovalCore`

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/hooks/approval_hook.py` — add `client` attribute, pass to `_ApprovalCore`
- Modify: `services/amplifier-foundation/src/amplifier_foundation/hooks/approval/approval_hook.py` — add `client` attribute, emit approval events
- Create: `services/amplifier-foundation/tests/test_approval_events.py`

### Step 1: Write the failing tests

Create `services/amplifier-foundation/tests/test_approval_events.py`:

```python
"""Tests for approval:required/granted/denied event emissions from _ApprovalCore."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_foundation.hooks.approval.approval_hook import _ApprovalCore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockClient:
    """Records IPC request calls."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, Any]] = []

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append((method, params))
        return {"action": "CONTINUE"}


def _hook_emits(client: MockClient, event: str) -> list[dict[str, Any]]:
    """Extract hook_emit calls for a given event name."""
    return [
        params["data"]
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == event
    ]


# ---------------------------------------------------------------------------
# Test 1: approval:required fires when tool needs approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_required_emitted_for_high_risk_tool() -> None:
    """_ApprovalCore emits approval:required when a tool needs approval."""
    core = _ApprovalCore(config={})
    mock_client = MockClient()
    core.client = mock_client

    await core._handle_tool_pre("tool:pre", {"tool_name": "bash", "tool_input": {"command": "ls"}})

    events = _hook_emits(mock_client, "approval:required")
    assert len(events) == 1, f"Expected 1 approval:required, got {len(events)}"
    assert events[0]["tool_name"] == "bash"
    assert events[0]["risk_level"] == "high"
    assert "action" in events[0]


# ---------------------------------------------------------------------------
# Test 2: approval:granted fires after auto-approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_granted_emitted_on_auto_approve() -> None:
    """_ApprovalCore emits approval:granted when auto-approved in IPC mode."""
    core = _ApprovalCore(config={})
    mock_client = MockClient()
    core.client = mock_client

    result = await core._handle_tool_pre("tool:pre", {"tool_name": "bash", "tool_input": {"command": "ls"}})

    # Default IPC mode auto-approves (no interactive provider)
    assert result.action.value == "CONTINUE"

    events = _hook_emits(mock_client, "approval:granted")
    assert len(events) == 1, f"Expected 1 approval:granted, got {len(events)}"
    assert events[0]["tool_name"] == "bash"
    assert "reason" in events[0]


# ---------------------------------------------------------------------------
# Test 3: approval:denied fires after auto-deny rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_denied_emitted_on_auto_deny() -> None:
    """_ApprovalCore emits approval:denied when an auto-deny rule matches."""
    rules = [
        {"tool": "bash", "action": "auto_deny"},
    ]
    core = _ApprovalCore(config={"rules": rules})
    mock_client = MockClient()
    core.client = mock_client

    result = await core._handle_tool_pre("tool:pre", {"tool_name": "bash", "tool_input": {"command": "rm -rf /"}})

    assert result.action.value == "DENY"

    events = _hook_emits(mock_client, "approval:denied")
    assert len(events) == 1, f"Expected 1 approval:denied, got {len(events)}"
    assert events[0]["tool_name"] == "bash"
    assert "reason" in events[0]


# ---------------------------------------------------------------------------
# Test 4: no approval events when tool does NOT need approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_approval_events_for_safe_tool() -> None:
    """_ApprovalCore emits no approval events when tool doesn't need approval."""
    core = _ApprovalCore(config={})
    mock_client = MockClient()
    core.client = mock_client

    await core._handle_tool_pre("tool:pre", {"tool_name": "read_file", "tool_input": {}})

    all_emits = [
        (method, params)
        for method, params in mock_client.requests
        if method == "request.hook_emit"
    ]
    assert len(all_emits) == 0, (
        f"Expected no hook_emit calls for safe tool, got {len(all_emits)}"
    )


# ---------------------------------------------------------------------------
# Test 5: approval events work when client is None (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_works_without_client() -> None:
    """_ApprovalCore does not crash when client is None."""
    core = _ApprovalCore(config={})
    assert core.client is None

    # Should not raise even without client
    result = await core._handle_tool_pre("tool:pre", {"tool_name": "bash", "tool_input": {"command": "ls"}})
    assert result.action.value == "CONTINUE"


# ---------------------------------------------------------------------------
# Test 6: ApprovalHook proxy passes client to _ApprovalCore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_hook_proxy_passes_client() -> None:
    """ApprovalHook passes its client through to _ApprovalCore."""
    from amplifier_foundation.hooks.approval_hook import ApprovalHook

    hook = ApprovalHook()
    mock_client = MockClient()
    hook.client = mock_client

    await hook.handle("tool:pre", {"tool_name": "bash", "tool_input": {"command": "ls"}})

    events = _hook_emits(mock_client, "approval:required")
    assert len(events) == 1, (
        f"Expected 1 approval:required via proxy, got {len(events)}"
    )
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-foundation && python -m pytest tests/test_approval_events.py -v && cd ../..
```
Expected: FAIL — `AttributeError: '_ApprovalCore' object has no attribute 'client'`

### Step 3: Add `client` attribute and event emission to `_ApprovalCore`

In `services/amplifier-foundation/src/amplifier_foundation/hooks/approval/approval_hook.py`:

**Add imports** — find:

```python
from amplifier_ipc.protocol.models import HookAction, HookResult
```

Replace with:

```python
from amplifier_ipc.protocol.models import HookAction, HookResult
from amplifier_ipc_protocol.events import (
    APPROVAL_DENIED,
    APPROVAL_GRANTED,
    APPROVAL_REQUIRED,
)
```

**Add `client` attribute** — find:

```python
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
```

Replace with:

```python
    # Injected by the protocol server via ApprovalHook proxy.
    # Enables IPC hook event emission for approval decisions.
    client: Any = None

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
```

**Add a helper method** — add after the `__init__` method (after line 34):

```python
    async def _emit_hook(self, event: str, data: dict[str, Any]) -> None:
        """Emit a hook event via the injected client. Errors are swallowed."""
        if self.client is None:
            return
        try:
            await self.client.request(
                "request.hook_emit", {"event": event, "data": data}
            )
        except Exception:
            pass  # Hook emission must never affect approval decisions
```

**Add emission at the `approval:required` site** — find:

```python
        # Log approval required (no IPC emit)
        logger.info(
            "approval:required tool=%s action=%s risk=%s",
            tool_name,
            request.action,
            request.risk_level,
        )
```

Replace with:

```python
        # Emit approval:required
        logger.info(
            "approval:required tool=%s action=%s risk=%s",
            tool_name,
            request.action,
            request.risk_level,
        )
        await self._emit_hook(APPROVAL_REQUIRED, {
            "tool_name": tool_name,
            "action": request.action,
            "risk_level": request.risk_level,
            "tool_input": tool_input,
            "timeout": request.timeout,
        })
```

**Add emission at the auto-approve `approval:granted` site** — find:

```python
            if auto_action == "auto_approve":
                logger.info(
                    "approval:granted tool=%s reason=Auto-approved by rule", tool_name
                )
                return HookResult(action=HookAction.CONTINUE)
```

Replace with:

```python
            if auto_action == "auto_approve":
                logger.info(
                    "approval:granted tool=%s reason=Auto-approved by rule", tool_name
                )
                await self._emit_hook(APPROVAL_GRANTED, {
                    "tool_name": tool_name,
                    "reason": "Auto-approved by rule",
                })
                return HookResult(action=HookAction.CONTINUE)
```

**Add emission at the auto-deny `approval:denied` site** — find:

```python
            logger.info("approval:denied tool=%s reason=Auto-denied by rule", tool_name)
            return HookResult(action=HookAction.DENY, reason="Auto-denied by rule")
```

Replace with:

```python
            logger.info("approval:denied tool=%s reason=Auto-denied by rule", tool_name)
            await self._emit_hook(APPROVAL_DENIED, {
                "tool_name": tool_name,
                "reason": "Auto-denied by rule",
            })
            return HookResult(action=HookAction.DENY, reason="Auto-denied by rule")
```

**Add emission at the IPC-mode auto-approve `approval:granted` site** — find:

```python
        # In IPC mode: auto-approve (no interactive provider available)
        logger.info(
            "approval:granted tool=%s reason=Auto-approved in IPC mode (no interactive provider)",
            tool_name,
        )
```

Replace with:

```python
        # In IPC mode: auto-approve (no interactive provider available)
        logger.info(
            "approval:granted tool=%s reason=Auto-approved in IPC mode (no interactive provider)",
            tool_name,
        )
        await self._emit_hook(APPROVAL_GRANTED, {
            "tool_name": tool_name,
            "reason": "Auto-approved in IPC mode",
        })
```

### Step 4: Add `client` attribute to `ApprovalHook` proxy and pass through to `_ApprovalCore`

In `services/amplifier-foundation/src/amplifier_foundation/hooks/approval_hook.py`:

**Add `client` attribute and pass-through** — find:

```python
@hook(events=["tool:pre"], priority=5)
class ApprovalHook:
    """Proxy hook — intercepts tool:pre events and applies approval logic.

    Delegates to approval._ApprovalCore for the actual decision logic.
    In IPC mode, interactive approval is not available, so tools are
    auto-approved (with audit logging) unless an auto-deny rule matches.
    """

    name = "approval"
    events = ["tool:pre"]
    priority = 5

    def __init__(self) -> None:
        self._core = _ApprovalCore(config={})

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event."""
        if event == "tool:pre":
            return await self._core._handle_tool_pre(event, data)
        return HookResult(action=HookAction.CONTINUE)
```

Replace with:

```python
@hook(events=["tool:pre"], priority=5)
class ApprovalHook:
    """Proxy hook — intercepts tool:pre events and applies approval logic.

    Delegates to approval._ApprovalCore for the actual decision logic.
    In IPC mode, interactive approval is not available, so tools are
    auto-approved (with audit logging) unless an auto-deny rule matches.
    """

    name = "approval"
    events = ["tool:pre"]
    priority = 5

    # Injected by the protocol server's _handle_hook_emit when the
    # orchestrator is active (allows IPC calls back to the host).
    client: Any = None

    def __init__(self) -> None:
        self._core = _ApprovalCore(config={})

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch to the appropriate handler based on event."""
        # Pass client through to core so it can emit approval events
        self._core.client = self.client
        if event == "tool:pre":
            return await self._core._handle_tool_pre(event, data)
        return HookResult(action=HookAction.CONTINUE)
```

### Step 5: Run tests to verify they pass

```bash
cd services/amplifier-foundation && python -m pytest tests/test_approval_events.py -v && cd ../..
```
Expected: 6 PASS

### Step 6: Run the full foundation test suite

```bash
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..
```
Expected: All tests pass.

### Step 7: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/hooks/approval/approval_hook.py services/amplifier-foundation/src/amplifier_foundation/hooks/approval_hook.py services/amplifier-foundation/tests/test_approval_events.py
git commit -m "feat(events): emit approval:required/granted/denied from _ApprovalCore"
```

---

## Task 4: Emit `policy:violation` from `ModeHooks`

**Files:**
- Modify: `services/amplifier-modes/src/amplifier_modes/hooks/mode.py`
- Create: `services/amplifier-modes/tests/test_policy_events.py`

### Step 1: Write the failing tests

Create `services/amplifier-modes/tests/test_policy_events.py`:

```python
"""Tests for policy:violation event emission from ModeHooks."""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_modes.hooks.mode import ModeDefinition, ModeHooks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockClient:
    """Records IPC request calls."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, Any]] = []

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append((method, params))
        return {"action": "CONTINUE"}


def _hook_emits(client: MockClient, event: str) -> list[dict[str, Any]]:
    """Extract hook_emit calls for a given event name."""
    return [
        params["data"]
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == event
    ]


def _make_mode_with_policy() -> ModeDefinition:
    """Create a mode that blocks some tools and warns on others."""
    return ModeDefinition(
        name="focus",
        description="Deep focus mode",
        safe_tools=["read_file", "grep"],
        warn_tools=["bash"],
        block_tools=["write_file"],
        default_action="block",
    )


# ---------------------------------------------------------------------------
# Test 1: policy:violation emitted for blocked tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_violation_emitted_for_blocked_tool() -> None:
    """ModeHooks emits policy:violation when a blocked tool is denied."""
    hooks = ModeHooks()
    hooks.set_active_mode(_make_mode_with_policy())
    mock_client = MockClient()
    hooks.client = mock_client

    result = await hooks.handle("tool:pre", {"tool_name": "write_file"})

    assert result.action.value == "DENY"

    events = _hook_emits(mock_client, "policy:violation")
    assert len(events) == 1, f"Expected 1 policy:violation, got {len(events)}"
    assert events[0]["tool_name"] == "write_file"
    assert events[0]["mode"] == "focus"
    assert "reason" in events[0]


# ---------------------------------------------------------------------------
# Test 2: policy:violation emitted for warn-first tool (first call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_violation_emitted_for_warn_first_tool() -> None:
    """ModeHooks emits policy:violation on the first call to a warn-first tool."""
    hooks = ModeHooks()
    hooks.set_active_mode(_make_mode_with_policy())
    mock_client = MockClient()
    hooks.client = mock_client

    result = await hooks.handle("tool:pre", {"tool_name": "bash"})

    assert result.action.value == "DENY"

    events = _hook_emits(mock_client, "policy:violation")
    assert len(events) == 1, f"Expected 1 policy:violation, got {len(events)}"
    assert events[0]["tool_name"] == "bash"
    assert events[0]["mode"] == "focus"


# ---------------------------------------------------------------------------
# Test 3: NO policy:violation for warn-first tool on second call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_violation_for_warn_first_tool_second_call() -> None:
    """ModeHooks does NOT emit policy:violation for the second call to a warn-first tool."""
    hooks = ModeHooks()
    hooks.set_active_mode(_make_mode_with_policy())
    mock_client = MockClient()
    hooks.client = mock_client

    # First call: DENY with warning
    await hooks.handle("tool:pre", {"tool_name": "bash"})

    # Clear recorded calls
    mock_client.requests.clear()

    # Second call: CONTINUE (warned already)
    result = await hooks.handle("tool:pre", {"tool_name": "bash"})
    assert result.action.value == "CONTINUE"

    events = _hook_emits(mock_client, "policy:violation")
    assert len(events) == 0, (
        f"Expected no policy:violation on second call, got {len(events)}"
    )


# ---------------------------------------------------------------------------
# Test 4: policy:violation emitted for unlisted tool with default_action=block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_violation_emitted_for_unlisted_tool() -> None:
    """ModeHooks emits policy:violation for unlisted tools when default_action=block."""
    hooks = ModeHooks()
    hooks.set_active_mode(_make_mode_with_policy())
    mock_client = MockClient()
    hooks.client = mock_client

    result = await hooks.handle("tool:pre", {"tool_name": "some_unknown_tool"})

    assert result.action.value == "DENY"

    events = _hook_emits(mock_client, "policy:violation")
    assert len(events) == 1, f"Expected 1 policy:violation, got {len(events)}"
    assert events[0]["tool_name"] == "some_unknown_tool"
    assert events[0]["mode"] == "focus"


# ---------------------------------------------------------------------------
# Test 5: NO policy:violation for safe tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_violation_for_safe_tool() -> None:
    """ModeHooks does NOT emit policy:violation for safe tools."""
    hooks = ModeHooks()
    hooks.set_active_mode(_make_mode_with_policy())
    mock_client = MockClient()
    hooks.client = mock_client

    result = await hooks.handle("tool:pre", {"tool_name": "read_file"})

    assert result.action.value == "CONTINUE"

    all_emits = [
        (method, params)
        for method, params in mock_client.requests
        if method == "request.hook_emit"
    ]
    assert len(all_emits) == 0, (
        f"Expected no hook_emit calls for safe tool, got {len(all_emits)}"
    )


# ---------------------------------------------------------------------------
# Test 6: NO policy:violation when no mode is active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_violation_when_no_mode_active() -> None:
    """ModeHooks does NOT emit policy:violation when no mode is active."""
    hooks = ModeHooks()
    mock_client = MockClient()
    hooks.client = mock_client

    result = await hooks.handle("tool:pre", {"tool_name": "bash"})

    assert result.action.value == "CONTINUE"

    all_emits = [
        (method, params)
        for method, params in mock_client.requests
        if method == "request.hook_emit"
    ]
    assert len(all_emits) == 0


# ---------------------------------------------------------------------------
# Test 7: policy:violation works when client is None (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_violation_works_without_client() -> None:
    """ModeHooks does not crash when client is None."""
    hooks = ModeHooks()
    hooks.set_active_mode(_make_mode_with_policy())
    assert hooks.client is None

    result = await hooks.handle("tool:pre", {"tool_name": "write_file"})
    assert result.action.value == "DENY"
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-modes && python -m pytest tests/test_policy_events.py -v && cd ../..
```
Expected: FAIL — `AttributeError: 'ModeHooks' object has no attribute 'client'`

### Step 3: Add `client` attribute and `policy:violation` emission to `ModeHooks`

In `services/amplifier-modes/src/amplifier_modes/hooks/mode.py`:

**Add imports** — find:

```python
from amplifier_ipc.protocol import HookAction, HookResult, hook
```

Replace with:

```python
from amplifier_ipc.protocol import HookAction, HookResult, hook
from amplifier_ipc_protocol.events import POLICY_VIOLATION
```

**Add `client` attribute** — find:

```python
@hook(events=["provider:request", "tool:pre"], priority=5)
class ModeHooks:
    """Generic mode enforcement via hooks."""

    name = "mode_hooks"

    def __init__(self) -> None:
        self._warned_tools: set[str] = set()
        self._active_mode: ModeDefinition | None = None
```

Replace with:

```python
@hook(events=["provider:request", "tool:pre"], priority=5)
class ModeHooks:
    """Generic mode enforcement via hooks."""

    name = "mode_hooks"

    # Injected by the protocol server's _handle_hook_emit when the
    # orchestrator is active (allows IPC calls back to the host).
    client: Any = None

    def __init__(self) -> None:
        self._warned_tools: set[str] = set()
        self._active_mode: ModeDefinition | None = None
```

**Add `Any` to typing import** — find at the top of the file (there is no `Any` import currently since the class uses plain `dict` annotations). Add after the existing imports:

```python
from typing import Any
```

Actually, check — let me look. The file has `from dataclasses import dataclass, field` etc. but doesn't import `Any`. Since `ModeHooks.handle` uses `data: dict` (not `dict[str, Any]`), `Any` isn't imported. We need it for `client: Any = None`. Add it after line 7:

Find:

```python
from dataclasses import dataclass, field
from pathlib import Path
```

Replace with:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
```

**Add a helper method** — add after the `__init__` method (after line 105 which has `self._active_mode: ModeDefinition | None = None`):

```python
    async def _emit_policy_violation(
        self, tool_name: str, mode_name: str, reason: str
    ) -> None:
        """Emit a policy:violation hook event. Errors are swallowed."""
        if self.client is None:
            return
        try:
            await self.client.request(
                "request.hook_emit",
                {
                    "event": POLICY_VIOLATION,
                    "data": {
                        "tool_name": tool_name,
                        "mode": mode_name,
                        "reason": reason,
                    },
                },
            )
        except Exception:
            pass  # Hook emission must never affect policy decisions
```

**Add emission for blocked tools** — find:

```python
        # Explicitly blocked tools: always deny
        if tool_name in mode.block_tools:
            return HookResult(
                action=HookAction.DENY,
                reason=f"Mode '{mode.name}': '{tool_name}' is blocked. {mode.description}",
            )
```

Replace with:

```python
        # Explicitly blocked tools: always deny
        if tool_name in mode.block_tools:
            reason = f"Mode '{mode.name}': '{tool_name}' is blocked. {mode.description}"
            await self._emit_policy_violation(tool_name, mode.name, reason)
            return HookResult(action=HookAction.DENY, reason=reason)
```

**Add emission for warn-first tools (first call)** — find:

```python
        # Warn-first tools: warn once, then allow
        if tool_name in mode.warn_tools:
            warn_key = f"{mode.name}:{tool_name}"
            if warn_key not in self._warned_tools:
                self._warned_tools.add(warn_key)
                return HookResult(
                    action=HookAction.DENY,
                    reason=f"Mode '{mode.name}': '{tool_name}' requires confirmation. "
                    f"Call again if this is appropriate for {mode.name} mode.",
                )
            return HookResult(action=HookAction.CONTINUE)
```

Replace with:

```python
        # Warn-first tools: warn once, then allow
        if tool_name in mode.warn_tools:
            warn_key = f"{mode.name}:{tool_name}"
            if warn_key not in self._warned_tools:
                self._warned_tools.add(warn_key)
                reason = (
                    f"Mode '{mode.name}': '{tool_name}' requires confirmation. "
                    f"Call again if this is appropriate for {mode.name} mode."
                )
                await self._emit_policy_violation(tool_name, mode.name, reason)
                return HookResult(action=HookAction.DENY, reason=reason)
            return HookResult(action=HookAction.CONTINUE)
```

**Add emission for unlisted tools (default block)** — find:

```python
        # Default is block
        return HookResult(
            action=HookAction.DENY,
            reason=f"Mode '{mode.name}': '{tool_name}' is not in the allowed list. "
            f"Use /mode off to exit {mode.name} mode.",
        )
```

Replace with:

```python
        # Default is block
        reason = (
            f"Mode '{mode.name}': '{tool_name}' is not in the allowed list. "
            f"Use /mode off to exit {mode.name} mode."
        )
        await self._emit_policy_violation(tool_name, mode.name, reason)
        return HookResult(action=HookAction.DENY, reason=reason)
```

### Step 4: Run tests to verify they pass

```bash
cd services/amplifier-modes && python -m pytest tests/test_policy_events.py -v && cd ../..
```
Expected: 7 PASS

### Step 5: Run the full modes test suite

```bash
cd services/amplifier-modes && python -m pytest tests/ -v && cd ../..
```
Expected: All tests pass.

### Step 6: Commit

```bash
git add services/amplifier-modes/src/amplifier_modes/hooks/mode.py services/amplifier-modes/tests/test_policy_events.py
git commit -m "feat(events): emit policy:violation from ModeHooks on tool deny"
```

---

## Task 5: Emit Delegate Lifecycle Events from `DelegateTool`

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/tools/delegate.py`
- Modify: `services/amplifier-foundation/tests/test_delegate.py`

### Step 1: Write the failing tests

Append to `services/amplifier-foundation/tests/test_delegate.py`:

```python
# ---------------------------------------------------------------------------
# Delegate event emission tests
# ---------------------------------------------------------------------------


def _hook_emits(client: FakeClient, event: str) -> list[dict[str, Any]]:
    """Extract hook_emit calls for a given event name."""
    return [
        params["data"]
        for method, params in client.calls
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == event
    ]


@pytest.mark.asyncio
async def test_delegate_emits_agent_spawned_and_completed() -> None:
    """DelegateTool emits delegate:agent_spawned before and delegate:agent_completed after spawn."""
    tool = DelegateTool()
    tool.client = FakeClient(
        responses={
            "request.session_spawn": make_spawn_response(
                session_id="sess-new", response="Done.", turn_count=2
            ),
        }
    )

    result = await tool.execute(
        {"agent": "foundation:explorer", "instruction": "Explore"}
    )

    assert result.success is True

    # Check agent_spawned
    spawned = _hook_emits(tool.client, "delegate:agent_spawned")
    assert len(spawned) == 1, f"Expected 1 delegate:agent_spawned, got {len(spawned)}"
    assert spawned[0]["agent"] == "foundation:explorer"

    # Check agent_completed
    completed = _hook_emits(tool.client, "delegate:agent_completed")
    assert len(completed) == 1, f"Expected 1 delegate:agent_completed, got {len(completed)}"
    assert completed[0]["agent"] == "foundation:explorer"
    assert completed[0]["sub_session_id"] == "sess-new"
    assert completed[0]["success"] is True


@pytest.mark.asyncio
async def test_delegate_emits_agent_resumed_and_completed() -> None:
    """DelegateTool emits delegate:agent_resumed before and delegate:agent_completed after resume."""
    tool = DelegateTool()
    tool.client = FakeClient(
        responses={
            "request.session_resume": make_spawn_response(
                session_id="existing-sess", response="Continued.", turn_count=5
            ),
        }
    )

    result = await tool.execute(
        {"session_id": "existing-sess", "instruction": "Continue"}
    )

    assert result.success is True

    # Check agent_resumed (NOT agent_spawned)
    resumed = _hook_emits(tool.client, "delegate:agent_resumed")
    assert len(resumed) == 1, f"Expected 1 delegate:agent_resumed, got {len(resumed)}"
    assert resumed[0]["session_id"] == "existing-sess"

    spawned = _hook_emits(tool.client, "delegate:agent_spawned")
    assert len(spawned) == 0, "delegate:agent_spawned should NOT fire for resume"

    # Check agent_completed
    completed = _hook_emits(tool.client, "delegate:agent_completed")
    assert len(completed) == 1
    assert completed[0]["sub_session_id"] == "existing-sess"
    assert completed[0]["success"] is True


@pytest.mark.asyncio
async def test_delegate_emits_error_on_failure() -> None:
    """DelegateTool emits delegate:error when spawn fails."""
    tool = DelegateTool()
    tool.client = FailingClient()

    result = await tool.execute(
        {"agent": "foundation:explorer", "instruction": "Explore"}
    )

    assert result.success is False

    # FailingClient doesn't record calls, but we need to verify the event
    # was attempted. For this test, we use a modified client that records
    # some calls but fails on session_spawn.


@pytest.mark.asyncio
async def test_delegate_emits_error_with_recording_client() -> None:
    """DelegateTool emits delegate:agent_spawned then delegate:error when spawn fails."""

    class SpawnFailingClient:
        """Records hook_emit calls but fails on session_spawn."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        async def request(self, method: str, params: Any = None) -> Any:
            self.calls.append((method, params))
            if method == "request.session_spawn":
                raise RuntimeError("Spawn failed")
            return {"action": "CONTINUE"}

    tool = DelegateTool()
    tool.client = SpawnFailingClient()

    result = await tool.execute(
        {"agent": "foundation:explorer", "instruction": "Explore"}
    )

    assert result.success is False

    # Check agent_spawned was emitted before the failure
    spawned = _hook_emits(tool.client, "delegate:agent_spawned")
    assert len(spawned) == 1, f"Expected 1 delegate:agent_spawned, got {len(spawned)}"

    # Check delegate:error was emitted after the failure
    errors = _hook_emits(tool.client, "delegate:error")
    assert len(errors) == 1, f"Expected 1 delegate:error, got {len(errors)}"
    assert errors[0]["agent"] == "foundation:explorer"
    assert "Spawn failed" in errors[0]["error"]


@pytest.mark.asyncio
async def test_delegate_no_completed_on_failure() -> None:
    """DelegateTool does NOT emit delegate:agent_completed when spawn fails."""

    class SpawnFailingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        async def request(self, method: str, params: Any = None) -> Any:
            self.calls.append((method, params))
            if method == "request.session_spawn":
                raise RuntimeError("Spawn failed")
            return {"action": "CONTINUE"}

    tool = DelegateTool()
    tool.client = SpawnFailingClient()

    await tool.execute({"agent": "self", "instruction": "Do something"})

    completed = _hook_emits(tool.client, "delegate:agent_completed")
    assert len(completed) == 0, (
        f"delegate:agent_completed should NOT fire on failure, got {len(completed)}"
    )
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-foundation && python -m pytest tests/test_delegate.py::test_delegate_emits_agent_spawned_and_completed tests/test_delegate.py::test_delegate_emits_agent_resumed_and_completed tests/test_delegate.py::test_delegate_emits_error_with_recording_client tests/test_delegate.py::test_delegate_no_completed_on_failure -v && cd ../..
```
Expected: FAIL — no `delegate:agent_spawned` event emitted (tool doesn't emit events yet)

### Step 3: Add delegate event emissions to `DelegateTool.execute()`

In `services/amplifier-foundation/src/amplifier_foundation/tools/delegate.py`:

**Add imports** — find:

```python
from amplifier_ipc.protocol import ToolResult, tool
```

Replace with:

```python
from amplifier_ipc.protocol import ToolResult, tool
from amplifier_ipc_protocol.events import (
    DELEGATE_AGENT_COMPLETED,
    DELEGATE_AGENT_RESUMED,
    DELEGATE_AGENT_SPAWNED,
    DELEGATE_ERROR,
)
```

**Replace the entire `execute()` method** — find:

```python
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Spawn or resume a child session via request.session_spawn / request.session_resume."""
        try:
            instruction: str = input["instruction"]
            session_id: str | None = input.get("session_id")

            if session_id:
                # Resume an existing session
                params: dict[str, Any] = {
                    "session_id": session_id,
                    "instruction": instruction,
                }
                result = await self.client.request("request.session_resume", params)
            else:
                # Spawn a new child session
                params = {
                    "agent": input.get("agent", "self"),
                    "instruction": instruction,
                }
                # Forward optional spawning parameters if provided
                for key in (
                    "context_depth",
                    "context_scope",
                    "context_turns",
                    "exclude_tools",
                    "inherit_tools",
                    "model_role",
                ):
                    if key in input:
                        params[key] = input[key]
                result = await self.client.request("request.session_spawn", params)

            child_session_id: str = result.get("session_id", "")
            response: str = result.get("response", "")
            turn_count: int = result.get("turn_count", 0)

            output = f"[Delegate session: {child_session_id}]\n[Turns: {turn_count}]\n\n{response}"
            return ToolResult(success=True, output=output)

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error={"message": str(exc)},
            )
```

Replace with:

```python
    async def _emit_hook(self, event: str, data: dict[str, Any]) -> None:
        """Emit a hook event via the injected client. Errors are swallowed."""
        if self.client is None:
            return
        try:
            await self.client.request(
                "request.hook_emit", {"event": event, "data": data}
            )
        except Exception:
            pass  # Hook emission must never affect tool result

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Spawn or resume a child session via request.session_spawn / request.session_resume."""
        agent_name: str = input.get("agent", "self")
        instruction: str = input.get("instruction", "")
        session_id: str | None = input.get("session_id")

        try:
            if session_id:
                # Resume an existing session
                await self._emit_hook(DELEGATE_AGENT_RESUMED, {
                    "session_id": session_id,
                })

                params: dict[str, Any] = {
                    "session_id": session_id,
                    "instruction": instruction,
                }
                result = await self.client.request("request.session_resume", params)
            else:
                # Spawn a new child session
                await self._emit_hook(DELEGATE_AGENT_SPAWNED, {
                    "agent": agent_name,
                    "context_depth": input.get("context_depth"),
                    "context_scope": input.get("context_scope"),
                })

                params = {
                    "agent": agent_name,
                    "instruction": instruction,
                }
                # Forward optional spawning parameters if provided
                for key in (
                    "context_depth",
                    "context_scope",
                    "context_turns",
                    "exclude_tools",
                    "inherit_tools",
                    "model_role",
                ):
                    if key in input:
                        params[key] = input[key]
                result = await self.client.request("request.session_spawn", params)

            child_session_id: str = result.get("session_id", "")
            response: str = result.get("response", "")
            turn_count: int = result.get("turn_count", 0)

            await self._emit_hook(DELEGATE_AGENT_COMPLETED, {
                "agent": agent_name,
                "sub_session_id": child_session_id,
                "success": True,
                "turn_count": turn_count,
            })

            output = f"[Delegate session: {child_session_id}]\n[Turns: {turn_count}]\n\n{response}"
            return ToolResult(success=True, output=output)

        except Exception as exc:  # noqa: BLE001
            await self._emit_hook(DELEGATE_ERROR, {
                "agent": agent_name,
                "error": str(exc),
            })
            return ToolResult(
                success=False,
                error={"message": str(exc)},
            )
```

### Step 4: Run tests to verify they pass

```bash
cd services/amplifier-foundation && python -m pytest tests/test_delegate.py -v && cd ../..
```
Expected: All tests pass (both old and new).

### Step 5: Run the full foundation test suite

```bash
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..
```
Expected: All tests pass.

### Step 6: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/tools/delegate.py services/amplifier-foundation/tests/test_delegate.py
git commit -m "feat(events): emit delegate:agent_spawned/completed/resumed/error from DelegateTool"
```

---

## Post-Implementation Verification

After all 5 tasks are complete, run the full test suites:

```bash
# Root test suite (host tests, protocol server tests)
python -m pytest tests/ -v

# Foundation service tests (approval events, delegate events, all others)
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..

# Modes service tests (policy events, mode operations)
cd services/amplifier-modes && python -m pytest tests/ -v && cd ../..
```

All tests should pass with zero failures.

### Summary of Changes

**Event constants** — 1 file modified:

| File | Change |
|---|---|
| `events.py` | Added `DELEGATE_AGENT_SPAWNED`, `DELEGATE_AGENT_COMPLETED`, `DELEGATE_AGENT_RESUMED`, `DELEGATE_ERROR` |
| `__init__.py` | Re-exported the 4 new constants |

**Protocol server** — 1 file modified:

| File | Change |
|---|---|
| `server.py` | `_handle_hook_emit()` now injects orchestrator client into hooks with `client` attribute |

**Approval hooks** — 2 files modified:

| File | Change |
|---|---|
| `approval/approval_hook.py` | Added `client: Any = None`, `_emit_hook()` helper, emits `approval:required/granted/denied` at decision points |
| `approval_hook.py` | Added `client: Any = None`, passes client through to `_ApprovalCore` in `handle()` |

**Mode hooks** — 1 file modified:

| File | Change |
|---|---|
| `mode.py` | Added `client: Any = None`, `_emit_policy_violation()` helper, emits `policy:violation` at all 3 DENY sites |

**Delegate tool** — 1 file modified:

| File | Change |
|---|---|
| `delegate.py` | Added `_emit_hook()` helper, emits `delegate:agent_spawned/completed/resumed/error` at lifecycle points |

**Event payloads:**

| Event | Payload |
|---|---|
| `approval:required` | `{"tool_name": str, "action": str, "risk_level": str, "tool_input": dict, "timeout": float \| None}` |
| `approval:granted` | `{"tool_name": str, "reason": str}` |
| `approval:denied` | `{"tool_name": str, "reason": str}` |
| `policy:violation` | `{"tool_name": str, "mode": str, "reason": str}` |
| `delegate:agent_spawned` | `{"agent": str, "context_depth": str \| None, "context_scope": str \| None}` |
| `delegate:agent_completed` | `{"agent": str, "sub_session_id": str, "success": bool, "turn_count": int}` |
| `delegate:agent_resumed` | `{"session_id": str}` |
| `delegate:error` | `{"agent": str, "error": str}` |

**Test files:**
- `services/amplifier-foundation/tests/test_approval_events.py` — 6 new tests (approval event emissions)
- `services/amplifier-modes/tests/test_policy_events.py` — 7 new tests (policy:violation emission)
- `services/amplifier-foundation/tests/test_delegate.py` — 5 new tests (delegate event emissions)

### What's Now Complete

After Phase 5, all 41 canonical events + 4 module-level delegate events have emission sites. The full IPC event parity project is complete:

| Phase | Events | Status |
|---|---|---|
| Phase 1 | `session:start/end`, `provider:response`, `content_block:start/end` fix | Done |
| Phase 2 | `llm:*`, `content_block:delta`, `thinking:*`, `execution:*`, `provider:throttle/resolve/tool_sequence_repaired` | Done |
| Phase 3 | `session:fork/resume`, `cancel:requested/completed`, `user:notification` | Done |
| Phase 4 | `artifact:write/read`, `context:include/pre_compact/post_compact/compaction` | Done |
| Phase 5 | `approval:required/granted/denied`, `policy:violation`, `delegate:agent_spawned/completed/resumed/error` | This plan |

### What's NOT in This Phase (Deferred)

- `deprecation:warning` — Custom module-level event, no existing emission site or subscriber yet
- `plan:start` / `plan:end` — No planning subsystem exists
