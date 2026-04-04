# SSE Event Parity Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Fix field name mismatches, broken hook contracts, and missing events in the CLI-to-orchestrator streaming pipeline so the IPC system matches legacy Amplifier event names and data shapes.

**Architecture:** The CLI (`amplifier-ipc-cli`) connects via HTTP/SSE to `session-service`, which relays events from `svc-orchestrator`. Events flow: orchestrator yields `stream.*` events → orchestrator `app.py` strips the `stream.` prefix → session-service forwards verbatim → CLI dispatches to `_handle_*` methods. This plan fixes field name mismatches at each boundary, aligns the `HookResult` contract with legacy Amplifier, adds finer-grained content block / thinking events, adds token usage reporting, and introduces streaming delegation through `svc-delegation`.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI/Starlette, SSE (sse-starlette), httpx, Dapr sidecar, pytest + pytest-asyncio, Rich (CLI rendering)

---

## Phase 1: Core Fixes (Tasks 1–5)

---

### Task 1: Fix CLI field name mismatches

**One-line:** Align CLI event handler field reads with the field names the orchestrator actually emits.

**Dependencies:** None — standalone CLI fix.

**Files:**
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py`
- Modify: `amplifier-ipc-cli/tests/test_display.py`

#### Problem

The orchestrator emits these field names in its SSE event payloads:
- `stream.thinking` → `{"thinking": "..."}` (display.py reads `data["text"]`)
- `stream.tool_call_start` → `{"tool_name": "..."}` (display.py reads `data["name"]`)
- `stream.tool_call` → `{"tool_name": "...", "arguments": {...}}` (display.py reads `data["name"]`)
- `stream.tool_result` → `{"tool_name": "...", "success": ..., "output": "..."}` (display.py reads `data["name"]`)
- `stream.error` → `{"error": "..."}` (display.py reads `data["message"]`)

The session-service also emits its *own* errors as `{"message": "..."}` (see `session-service/app.py:366`), so the error handler must accept both formats.

#### Step 1: Write failing tests

In `amplifier-ipc-cli/tests/test_display.py`, **update the existing tests** to use the correct field names that the orchestrator actually emits. Also add a test for structured error format.

Replace the test data payloads in these existing tests:

```python
# test_handle_thinking_event (line 55): change {"text": ...} to {"thinking": ...}
event = SSEEvent(event="thinking", data={"thinking": "I think carefully..."})

# test_handle_thinking_hidden_when_disabled (line 64): same fix
event = SSEEvent(event="thinking", data={"thinking": "hidden thought"})

# test_handle_tool_call_event (line 75): change "name" key to "tool_name"
data={"tool_name": "bash", "arguments": {"command": "echo hello"}}

# test_handle_tool_call_truncates_long_values (line 89): change "name" to "tool_name"
data={"tool_name": "write_file", "arguments": {"content": long_value}}

# test_handle_tool_call_limits_arg_count (line 104): change "name" to "tool_name"
data={"tool_name": "multi_arg", "arguments": args}

# test_handle_tool_result_success (line 121): change "name" to "tool_name"
data={"tool_name": "bash", "success": True, "output": "hello from bash"}

# test_handle_tool_result_failure (line 134): change "name" to "tool_name"
data={"tool_name": "bash", "success": False, "output": "error: command not found"}

# test_handle_tool_result_truncates_output (line 153): change "name" to "tool_name"
data={"tool_name": "bash", "success": True, "output": "\n".join(lines)}

# test_handle_error_event (line 177): change "message" to "error"
event = SSEEvent(event="error", data={"error": "something went wrong"})
```

Add a **new test** for structured error dict format:

```python
def test_handle_error_structured_dict(self) -> None:
    """_handle_error handles structured error dicts with 'type' and 'msg' keys."""
    console, buf = make_console()
    display = StreamingDisplay(console)
    event = SSEEvent(
        event="error",
        data={"error": {"type": "ToolExecutionError", "msg": "bash failed"}},
    )
    display.handle_sse_event(event)
    output = buf.getvalue()
    assert "ToolExecutionError" in output
    assert "bash failed" in output
```

Add a **new test** for backward-compat with session-service `{"message": ...}` errors:

```python
def test_handle_error_session_service_message_format(self) -> None:
    """_handle_error still works with session-service's {"message": ...} format."""
    console, buf = make_console()
    display = StreamingDisplay(console)
    event = SSEEvent(event="error", data={"message": "session service error"})
    display.handle_sse_event(event)
    output = buf.getvalue()
    assert "session service error" in output
```

Run: `cd amplifier-ipc-cli && python -m pytest tests/test_display.py -v`
Expected: Multiple failures — handlers read old field names, new test payloads use correct ones.

#### Step 2: Fix the handlers in display.py

In `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py`:

**`_handle_thinking` (line 114):** Change `data.get("text", "")` to `data.get("thinking", "")`:
```python
def _handle_thinking(self, data: Any) -> None:
    """Print thinking text inline in 'cyan dim' style (skipped when show_thinking=False)."""
    if not self._show_thinking:
        return
    text = data.get("thinking", "") if isinstance(data, dict) else str(data)
    self._console.print(text, end="", style="cyan dim", markup=False)
```

**`_handle_tool_call_start` (line 138):** Change `data.get("name", "")` to `data.get("tool_name", "")`:
```python
name = data.get("tool_name", "") if isinstance(data, dict) else str(data)
```

**`_handle_tool_call` (line 150):** Change `data.get("name", "")` to `data.get("tool_name", "")`:
```python
name = data.get("tool_name", "")
```

**`_handle_tool_result` (line 178):** Change `data.get("name", "")` to `data.get("tool_name", "")`:
```python
name = data.get("tool_name", "")
```

**`_handle_error` (lines 347–352):** Rewrite to prefer `data["error"]`, fall back to `data["message"]`, and handle structured error dicts:
```python
def _handle_error(self, data: Any) -> None:
    """Print a red error message with ✗ icon."""
    if isinstance(data, dict):
        error = data.get("error") or data.get("message") or str(data)
        # Handle structured error dict: {"type": "...", "msg": "..."}
        if isinstance(error, dict):
            error_type = error.get("type", "Error")
            error_msg = error.get("msg", str(error))
            message = f"{error_type}: {error_msg}"
        else:
            message = str(error)
    else:
        message = str(data)
    self._console.print(f"  \u2717 {message}", style="red", markup=False)
```

#### Step 3: Run tests to verify pass

Run: `cd amplifier-ipc-cli && python -m pytest tests/test_display.py -v`
Expected: All tests PASS.

#### Step 4: Commit

```bash
cd amplifier-ipc-cli && git add src/amplifier_ipc_cli/display.py tests/test_display.py
git commit -m "fix(cli): align display handler field names with orchestrator payloads

- _handle_thinking: read 'thinking' instead of 'text'
- _handle_tool_call_start/tool_call/tool_result: read 'tool_name' instead of 'name'
- _handle_error: read 'error' instead of 'message', support structured dict format
- Update all tests to use correct field names"
```

**Success criteria:**
- All existing tests in `test_display.py` pass with the new field names
- `_handle_error` accepts both `{"error": "..."}` (orchestrator) and `{"message": "..."}` (session-service) formats
- `_handle_error` accepts structured error dict `{"type": str, "msg": str}`
- No changes to any server-side code

---

### Task 2: Fix HookResult / context injection contract

**One-line:** Add `context_injection`, `context_injection_role`, and `ephemeral` as top-level fields on `HookResult` so the contract matches legacy Amplifier.

**Dependencies:** None — can run in parallel with Task 1.

**Files:**
- Modify: `amplifier-service-sdk/src/amplifier_service_sdk/models.py` (HookResult model, ~line 55)
- Modify: `services/svc-orchestrator/src/svc_orchestrator/hook_dispatcher.py` (lines 88–101)
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py` (lines 125–128, 282–285)
- Modify: `services/svc-todo/src/svc_todo/hooks.py` (lines 85–87)
- Modify: `services/svc-hooks-todo-reminder/src/svc_hooks_todo_reminder/hook.py` (lines 129–132)
- Modify: `services/svc-orchestrator/tests/test_hook_dispatcher.py` (lines 112–133)
- Create: `services/svc-orchestrator/tests/test_hook_result_contract.py`

#### Step 1: Write failing test for the new HookResult contract

Create `services/svc-orchestrator/tests/test_hook_result_contract.py`:

```python
"""Tests verifying the HookResult context injection contract."""

from __future__ import annotations

import pytest
from amplifier_service_sdk.models import HookResult


class TestHookResultContextInjection:
    """HookResult supports top-level context_injection fields (legacy contract)."""

    def test_context_injection_field_exists(self) -> None:
        """HookResult accepts context_injection as a top-level field."""
        result = HookResult(
            action="INJECT_CONTEXT",
            context_injection="You must remember this.",
            ephemeral=True,
        )
        assert result.context_injection == "You must remember this."
        assert result.ephemeral is True

    def test_context_injection_role_defaults_to_system(self) -> None:
        """context_injection_role defaults to 'system'."""
        result = HookResult(action="INJECT_CONTEXT", context_injection="ctx")
        assert result.context_injection_role == "system"

    def test_ephemeral_defaults_to_false(self) -> None:
        """ephemeral defaults to False."""
        result = HookResult(action="CONTINUE")
        assert result.ephemeral is False

    def test_context_injection_defaults_to_none(self) -> None:
        """context_injection defaults to None when not provided."""
        result = HookResult(action="CONTINUE")
        assert result.context_injection is None

    def test_backward_compat_data_dict_still_works(self) -> None:
        """HookResult still accepts the old data dict format."""
        result = HookResult(
            action="INJECT_CONTEXT",
            data={"context_injection": "old-style", "ephemeral": True},
        )
        assert result.data is not None
        assert result.data["context_injection"] == "old-style"
```

Run: `cd services/svc-orchestrator && python -m pytest tests/test_hook_result_contract.py -v`
Expected: FAIL — `HookResult` model does not yet have `context_injection`, `context_injection_role`, or `ephemeral` fields.

#### Step 2: Add fields to HookResult model

In `amplifier-service-sdk/src/amplifier_service_sdk/models.py`, update the `HookResult` class (lines 55–60):

```python
class HookResult(BaseModel):
    """The result returned by a hook handler."""

    action: str = "CONTINUE"
    data: dict[str, Any] | None = None
    reason: str | None = None
    context_injection: str | None = None
    context_injection_role: str = "system"
    ephemeral: bool = False
```

Run: `cd services/svc-orchestrator && python -m pytest tests/test_hook_result_contract.py -v`
Expected: All PASS.

#### Step 3: Update hook_dispatcher.py to read top-level fields

In `services/svc-orchestrator/src/svc_orchestrator/hook_dispatcher.py`:

**Lines 88–93** — change how `INJECT_CONTEXT` accumulates context:
```python
            if hook_result.action == "INJECT_CONTEXT":
                injection = hook_result.context_injection or ""
                if injection:
                    context_injections.append(str(injection))
```

**Lines 95–102** — change the returned HookResult to use top-level fields:
```python
        if context_injections:
            return HookResult(
                action="INJECT_CONTEXT",
                context_injection="\n\n".join(context_injections),
                ephemeral=True,
            )
```

#### Step 4: Update hook_dispatcher tests

In `services/svc-orchestrator/tests/test_hook_dispatcher.py`, update `test_dispatch_pre_inject_context_accumulates` (lines 107–133).

The mock hook responses should use the new top-level field. Update the `side_effect` data:
```python
        dapr.invoke.side_effect = [
            {
                "action": "INJECT_CONTEXT",
                "context_injection": "first context",
                "reason": None,
            },
            {
                "action": "INJECT_CONTEXT",
                "context_injection": "second context",
                "reason": None,
            },
        ]
```

Update the assertions to check the new top-level fields:
```python
        assert result.action == "INJECT_CONTEXT"
        assert result.context_injection == "first context\n\nsecond context"
        assert result.ephemeral is True
```

Run: `cd services/svc-orchestrator && python -m pytest tests/test_hook_dispatcher.py -v`
Expected: All PASS.

#### Step 5: Update orchestrator.py context injection reads

In `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`:

**Lines 125–128** (non-streaming `execute` method):
```python
            effective_system = system_prompt
            if pre_result.action == "INJECT_CONTEXT":
                injection = pre_result.context_injection or ""
                if injection:
                    effective_system = f"{injection}\n\n{system_prompt}"
```

**Lines 282–285** (streaming `execute_stream` method — same pattern):
```python
                effective_system = system_prompt
                if pre_result.action == "INJECT_CONTEXT":
                    injection = pre_result.context_injection or ""
                    if injection:
                        effective_system = f"{injection}\n\n{system_prompt}"
```

#### Step 6: Fix todo reminder hooks

In `services/svc-todo/src/svc_todo/hooks.py` (lines 85–87), change:
```python
        return HookResult(
            action="INJECT_CONTEXT",
            context_injection=content,
            ephemeral=True,
        )
```

In `services/svc-hooks-todo-reminder/src/svc_hooks_todo_reminder/hook.py` (lines 129–132), change:
```python
        return HookResult(
            action="INJECT_CONTEXT",
            context_injection=content,
            ephemeral=True,
        )
```

#### Step 7: Run full test suite for affected packages

```bash
cd services/svc-orchestrator && python -m pytest tests/ -v
cd services/svc-todo && python -m pytest tests/ -v 2>/dev/null || echo "No tests yet"
cd services/svc-hooks-todo-reminder && python -m pytest tests/ -v 2>/dev/null || echo "No tests yet"
```
Expected: All PASS.

#### Step 8: Commit

```bash
git add amplifier-service-sdk/src/amplifier_service_sdk/models.py \
  services/svc-orchestrator/src/svc_orchestrator/hook_dispatcher.py \
  services/svc-orchestrator/src/svc_orchestrator/orchestrator.py \
  services/svc-orchestrator/tests/test_hook_dispatcher.py \
  services/svc-orchestrator/tests/test_hook_result_contract.py \
  services/svc-todo/src/svc_todo/hooks.py \
  services/svc-hooks-todo-reminder/src/svc_hooks_todo_reminder/hook.py
git commit -m "fix(sdk): add context_injection/ephemeral as top-level HookResult fields

- HookResult gains context_injection, context_injection_role, ephemeral
- hook_dispatcher reads result.context_injection instead of result.data['context_injection']
- orchestrator reads pre_result.context_injection (both execute and execute_stream)
- TodoReminderHook (both svc-todo and svc-hooks-todo-reminder) set top-level fields
- Matches legacy amplifier-core HookResult contract"
```

**Success criteria:**
- `HookResult(action="INJECT_CONTEXT", context_injection="...", ephemeral=True)` is the canonical way to inject context
- `hook_dispatcher.dispatch_pre()` reads `hook_result.context_injection` not `hook_result.data["context_injection"]`
- Orchestrator's `execute()` and `execute_stream()` both read `pre_result.context_injection`
- Both todo reminder hooks use top-level fields
- All orchestrator tests pass

---

### Task 3: Emit `todo_update` events from orchestrator

**One-line:** After a tool result for the `todo` tool, emit a `stream.todo_update` SSE event with the parsed todo list.

**Dependencies:** Task 2 (HookResult contract must be fixed first so hooks work correctly).

**Files:**
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py` (~line 358–376)
- Create: `services/svc-orchestrator/tests/test_orchestrator_todo_event.py`

#### Step 1: Write failing test

Create `services/svc-orchestrator/tests/test_orchestrator_todo_event.py`. This test follows the mock patterns from `test_orchestrator.py`:

```python
"""Tests for todo_update event emission in execute_stream."""

from __future__ import annotations

import json
from typing import Any

import pytest

from amplifier_service_sdk.models import Message, RoutingTable
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator


def _make_dapr() -> DaprClient:
    return DaprClient(dapr_url="http://localhost:3500")


def _routing_table(
    tools: dict[str, str] | None = None,
) -> RoutingTable:
    return RoutingTable(
        providers={"mock": "svc-provider-mock"},
        tools=tools or {},
        context="svc-context",
        hooks={},
    )


class TestTodoUpdateEvent:
    """execute_stream emits stream.todo_update after a todo tool result."""

    @pytest.mark.asyncio
    async def test_todo_tool_result_emits_todo_update(self) -> None:
        """When the provider calls the 'todo' tool, a todo_update event is emitted."""
        dapr = _make_dapr()
        provider_call_count = 0
        todo_output = json.dumps({
            "status": "created",
            "todos": [
                {"content": "Write tests", "status": "in_progress", "activeForm": "Writing tests"},
                {"content": "Implement", "status": "pending", "activeForm": "Implementing"},
            ],
            "count": 2,
            "completed": 0,
            "in_progress": 1,
            "pending": 1,
        })

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kw: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count
            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {"id": "call-todo-1", "name": "todo", "arguments": {"action": "create", "todos": []}},
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                return {
                    "content": "Done!",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            if app_id == "svc-todo" and "tools" in method:
                return {"success": True, "output": todo_output}
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kw: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "make a todo"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="You are helpful.",
            messages=[Message(role="user", content="make a todo")],
            config={"provider": "mock"},
            routing_table=_routing_table(tools={"todo": "svc-todo"}),
            session_id="session-todo-1",
        ):
            events.append(event)

        # Find stream.todo_update events
        todo_events = [e for e in events if e["event"] == "stream.todo_update"]
        assert len(todo_events) >= 1, (
            f"Expected at least one stream.todo_update event. Got events: "
            f"{[e['event'] for e in events]}"
        )

        todo_data = json.loads(todo_events[0]["data"])
        assert "todos" in todo_data
        assert isinstance(todo_data["todos"], list)
        assert len(todo_data["todos"]) == 2
        assert todo_data["status"] == "created"
```

Run: `cd services/svc-orchestrator && python -m pytest tests/test_orchestrator_todo_event.py -v`
Expected: FAIL — no `stream.todo_update` event in output.

#### Step 2: Add todo_update emission to execute_stream

In `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`, in the `execute_stream` method, after the loop that emits `stream.tool_result` events (around line 376), add todo_update emission:

```python
                # Emit tool_result events after all tools complete
                for tc, msg in zip(
                    chat_response.tool_calls, tool_result_msgs, strict=False
                ):
                    raw_output = (
                        msg.content
                        if isinstance(msg.content, str)
                        else json.dumps(msg.content)
                    )
                    truncated = raw_output[:2000] if raw_output else ""
                    yield {
                        "event": "stream.tool_result",
                        "data": json.dumps(
                            {
                                "tool_name": tc.name,
                                "success": True,
                                "output": truncated,
                            }
                        ),
                    }

                    # Emit todo_update after todo tool results
                    if tc.name == "todo" and raw_output:
                        try:
                            parsed = json.loads(raw_output)
                            if isinstance(parsed, dict) and "todos" in parsed:
                                yield {
                                    "event": "stream.todo_update",
                                    "data": json.dumps(
                                        {
                                            "todos": parsed["todos"],
                                            "status": parsed.get("status", "updated"),
                                        }
                                    ),
                                }
                        except (json.JSONDecodeError, TypeError):
                            pass  # Best-effort: skip if output isn't valid JSON
```

#### Step 3: Run tests

Run: `cd services/svc-orchestrator && python -m pytest tests/test_orchestrator_todo_event.py tests/test_orchestrator.py -v`
Expected: All PASS.

#### Step 4: Commit

```bash
git add services/svc-orchestrator/src/svc_orchestrator/orchestrator.py \
  services/svc-orchestrator/tests/test_orchestrator_todo_event.py
git commit -m "feat(orchestrator): emit stream.todo_update after todo tool results

Parse the todo tool's JSON output and emit stream.todo_update with
{todos, status} so the CLI can render a live todo panel."
```

**Success criteria:**
- When the provider calls the `todo` tool, `execute_stream` yields a `stream.todo_update` event
- The event data contains `{"todos": [...], "status": "created"|"updated"}`
- Best-effort: non-JSON tool output is silently ignored
- No regressions in existing orchestrator tests

---

### Task 4: Emit finer-grained content block and thinking events

**One-line:** Replace the single `stream.thinking` event with structured `content_block:start/delta/end` and `thinking:delta/final` events matching legacy Amplifier's event granularity.

**Dependencies:** Tasks 1 and 2 (CLI field names and hooks must be fixed first).

**Files:**
- Modify: `services/session-service/src/session_service/streaming.py` (StreamEventType enum)
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py` (content block emission, ~lines 298–307)
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py` (handler dispatch + new handlers)
- Modify: `amplifier-ipc-cli/tests/test_display.py` (new tests for colon events)
- Create: `services/svc-orchestrator/tests/test_orchestrator_content_blocks.py`

#### Step 1: Update StreamEventType enum

In `services/session-service/src/session_service/streaming.py`, replace the enum:

```python
class StreamEventType(str, Enum):
    """Event types for SSE streaming from session-service."""

    token = "token"
    tool_call_start = "tool_call_start"
    tool_call = "tool_call"
    tool_result = "tool_result"
    todo_update = "todo_update"
    error = "error"
    complete = "complete"
    # Content block events (colon-separated, matching legacy Amplifier)
    content_block_start = "content_block:start"
    content_block_end = "content_block:end"
    content_block_delta = "content_block:delta"
    # Thinking events (finer-grained replacement for old 'thinking' value)
    thinking_delta = "thinking:delta"
    thinking_final = "thinking:final"
    # Delegation events (placeholder names, updated in Task 6)
    child_session_start = "child_session_start"
    child_session_end = "child_session_end"
```

Note: The `thinking` value is removed — replaced by `thinking:delta` and `thinking:final`. The `content_block_start`/`content_block_end` member names stay the same but the *values* now use colons instead of underscores.

#### Step 2: Write failing orchestrator test

Create `services/svc-orchestrator/tests/test_orchestrator_content_blocks.py`:

```python
"""Tests for content block and thinking event emission in execute_stream."""

from __future__ import annotations

import json
from typing import Any

import pytest

from amplifier_service_sdk.models import Message, RoutingTable
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator


def _make_dapr() -> DaprClient:
    return DaprClient(dapr_url="http://localhost:3500")


def _routing_table() -> RoutingTable:
    return RoutingTable(
        providers={"mock": "svc-provider-mock"},
        tools={},
        context="svc-context",
        hooks={},
    )


class TestContentBlockEvents:
    """execute_stream emits structured content_block and thinking events."""

    @pytest.mark.asyncio
    async def test_thinking_block_emits_full_sequence(self) -> None:
        """A thinking block yields content_block:start, thinking:delta, thinking:final, content_block:end."""
        dapr = _make_dapr()

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kw: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": [
                        {"type": "thinking", "thinking": "Let me think about this..."},
                        {"type": "text", "text": "Here is my answer."},
                    ],
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kw: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Think about this"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="Think step by step.",
            messages=[Message(role="user", content="Think about this")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-think-1",
        ):
            events.append(event)

        event_names = [e["event"] for e in events]

        # Thinking block sequence
        assert "stream.content_block:start" in event_names
        assert "stream.thinking:delta" in event_names
        assert "stream.thinking:final" in event_names
        assert "stream.content_block:end" in event_names

        # Text block sequence
        assert "stream.content_block:delta" in event_names

        # Old stream.thinking should NOT be emitted
        assert "stream.thinking" not in event_names

        # Verify thinking:delta has correct data
        thinking_delta = next(e for e in events if e["event"] == "stream.thinking:delta")
        td_data = json.loads(thinking_delta["data"])
        assert td_data["delta"] == "Let me think about this..."

        # Verify thinking:final has correct data
        thinking_final = next(e for e in events if e["event"] == "stream.thinking:final")
        tf_data = json.loads(thinking_final["data"])
        assert tf_data["text"] == "Let me think about this..."

        # Verify text content_block:delta
        text_delta = next(e for e in events if e["event"] == "stream.content_block:delta")
        txd_data = json.loads(text_delta["data"])
        assert txd_data["delta"] == "Here is my answer."
        assert txd_data["block_type"] == "text"

    @pytest.mark.asyncio
    async def test_text_only_response_emits_content_block_delta(self) -> None:
        """A simple text response still emits content_block events when content is a list."""
        dapr = _make_dapr()

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kw: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": [{"type": "text", "text": "Just text."}],
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kw: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Say hi"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="Be brief.",
            messages=[Message(role="user", content="Say hi")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-text-blocks-1",
        ):
            events.append(event)

        event_names = [e["event"] for e in events]
        assert "stream.content_block:start" in event_names
        assert "stream.content_block:delta" in event_names
        assert "stream.content_block:end" in event_names

    @pytest.mark.asyncio
    async def test_plain_string_content_no_content_block_events(self) -> None:
        """When content is a plain string (not a list), no content_block events are emitted."""
        dapr = _make_dapr()

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kw: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": "Plain string response.",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kw: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Hello"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="Be brief.",
            messages=[Message(role="user", content="Hello")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-plain-1",
        ):
            events.append(event)

        event_names = [e["event"] for e in events]
        # Plain string content → no content_block events
        assert "stream.content_block:start" not in event_names
        assert "stream.content_block:delta" not in event_names
```

Run: `cd services/svc-orchestrator && python -m pytest tests/test_orchestrator_content_blocks.py -v`
Expected: FAIL — orchestrator still emits `stream.thinking` instead of the new events.

#### Step 3: Rewrite orchestrator content block emission

In `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`, replace the thinking block emission code (lines 298–307) with structured content block events. Replace:

```python
                # Emit thinking blocks (if any)
                if isinstance(chat_response.content, list):
                    for block in chat_response.content:
                        if isinstance(block, dict) and block.get("type") == "thinking":
                            thinking_text = block.get("thinking", "")
                            if thinking_text:
                                yield {
                                    "event": "stream.thinking",
                                    "data": json.dumps({"thinking": thinking_text}),
                                }
```

With:

```python
                # Emit structured content block events (thinking + text)
                if isinstance(chat_response.content, list):
                    for idx, block in enumerate(chat_response.content):
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type", "text")

                        yield {
                            "event": "stream.content_block:start",
                            "data": json.dumps(
                                {"block_type": block_type, "index": idx}
                            ),
                        }

                        if block_type == "thinking":
                            thinking_text = block.get("thinking", "")
                            if thinking_text:
                                yield {
                                    "event": "stream.thinking:delta",
                                    "data": json.dumps(
                                        {"index": idx, "delta": thinking_text}
                                    ),
                                }
                                yield {
                                    "event": "stream.thinking:final",
                                    "data": json.dumps(
                                        {"index": idx, "text": thinking_text}
                                    ),
                                }
                        elif block_type == "text":
                            text = block.get("text", "")
                            if text:
                                yield {
                                    "event": "stream.content_block:delta",
                                    "data": json.dumps(
                                        {
                                            "index": idx,
                                            "block_type": "text",
                                            "delta": text,
                                        }
                                    ),
                                }

                        yield {
                            "event": "stream.content_block:end",
                            "data": json.dumps(
                                {"block_type": block_type, "index": idx}
                            ),
                        }
```

Run: `cd services/svc-orchestrator && python -m pytest tests/test_orchestrator_content_blocks.py tests/test_orchestrator.py -v`
Expected: All PASS.

#### Step 4: Write failing CLI tests for colon-separated events

In `amplifier-ipc-cli/tests/test_display.py`, add new tests:

```python
class TestContentBlockEvents:
    """Tests for colon-separated content block and thinking events."""

    def test_colon_events_dispatch_correctly(self) -> None:
        """Events with colons (e.g., 'content_block:start') dispatch to _handle_content_block_start."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=True)
        event = SSEEvent(event="content_block:start", data={"type": "thinking"})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "Thinking" in output  # The thinking header should appear

    def test_thinking_delta_displays_text(self) -> None:
        """thinking:delta event prints thinking text in dim style."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=True)
        event = SSEEvent(
            event="thinking:delta",
            data={"index": 0, "delta": "Let me consider..."},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "Let me consider..." in output

    def test_thinking_delta_hidden_when_disabled(self) -> None:
        """thinking:delta skips output when show_thinking=False."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=False)
        event = SSEEvent(
            event="thinking:delta",
            data={"index": 0, "delta": "hidden thought"},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert output == ""

    def test_content_block_delta_displays_text(self) -> None:
        """content_block:delta event prints text content."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="content_block:delta",
            data={"index": 0, "block_type": "text", "delta": "Hello world"},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "Hello world" in output

    def test_content_block_end_closes_thinking_border(self) -> None:
        """content_block:end with type 'thinking' closes the thinking border."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=True)
        # Start a thinking block
        display.handle_sse_event(
            SSEEvent(event="content_block:start", data={"type": "thinking"})
        )
        # End it
        display.handle_sse_event(
            SSEEvent(event="content_block:end", data={"type": "thinking"})
        )
        output = buf.getvalue()
        assert "\u255a" in output  # bottom border character
```

Run: `cd amplifier-ipc-cli && python -m pytest tests/test_display.py::TestContentBlockEvents -v`
Expected: FAIL — colons in event names don't dispatch to handlers.

#### Step 5: Update CLI handler dispatch and add new handlers

In `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py`:

**Update `handle_sse_event` (line 68)** to normalize colons to underscores for handler dispatch:
```python
    def handle_sse_event(self, event: SSEEvent) -> None:
        """Dispatch an SSE event to the appropriate ``_handle_*`` method.

        Colon-separated event names (e.g. ``content_block:start``) are
        normalised to underscores for the method lookup so they map to
        ``_handle_content_block_start``.  Unknown event types are silently
        ignored.
        """
        safe_name = event.event.replace(":", "_")
        handler = getattr(self, f"_handle_{safe_name}", None)
        if handler is not None:
            handler(event.data)
```

**Add `_handle_thinking_delta` handler** (after the existing `_handle_thinking` method):
```python
    def _handle_thinking_delta(self, data: Any) -> None:
        """Print thinking delta text in 'cyan dim' style."""
        if not self._show_thinking:
            return
        delta = data.get("delta", "") if isinstance(data, dict) else str(data)
        if delta:
            self._console.print(delta, end="", style="cyan dim", markup=False)
```

**Add `_handle_thinking_final` handler:**
```python
    def _handle_thinking_final(self, data: Any) -> None:
        """No-op: final thinking text is already displayed by thinking:delta."""
```

**Add `_handle_content_block_delta` handler:**
```python
    def _handle_content_block_delta(self, data: Any) -> None:
        """Print content block delta text."""
        if not isinstance(data, dict):
            return
        block_type = data.get("block_type", "text")
        delta = data.get("delta", "")
        if block_type == "text" and delta:
            self._console.print(delta, end="", highlight=False, markup=False)
```

Run: `cd amplifier-ipc-cli && python -m pytest tests/test_display.py -v`
Expected: All PASS.

#### Step 6: Commit

```bash
git add services/session-service/src/session_service/streaming.py \
  services/svc-orchestrator/src/svc_orchestrator/orchestrator.py \
  services/svc-orchestrator/tests/test_orchestrator_content_blocks.py \
  amplifier-ipc-cli/src/amplifier_ipc_cli/display.py \
  amplifier-ipc-cli/tests/test_display.py
git commit -m "feat: emit finer-grained content_block and thinking events

Orchestrator:
- Replace single stream.thinking with content_block:start/end + thinking:delta/final
- Emit content_block:delta for text blocks
- Iterate through response content blocks with index tracking

StreamEventType enum:
- Remove 'thinking' value
- Add content_block:delta, thinking:delta, thinking:final
- Rename content_block_start/end values to use colon separator

CLI:
- Normalize colons to underscores in handler dispatch
- Add _handle_thinking_delta, _handle_thinking_final, _handle_content_block_delta"
```

**Success criteria:**
- Orchestrator emits `content_block:start` → `thinking:delta` → `thinking:final` → `content_block:end` for thinking blocks
- Orchestrator emits `content_block:start` → `content_block:delta` → `content_block:end` for text blocks
- No more `stream.thinking` events are emitted
- CLI correctly dispatches colon-separated event names to `_handle_*` methods
- `thinking:delta` renders in cyan dim style (matches old `_handle_thinking` behavior)
- `content_block:delta` renders text content (non-thinking blocks)

---

### Task 5: Include token usage in completion event

**One-line:** Capture `ChatResponse.usage` (input_tokens, output_tokens) and include it in the `stream.complete` event so the CLI can display token counts.

**Dependencies:** None — independent of other tasks.

**Files:**
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py` (~lines 294–402)
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py` (`_handle_complete`)
- Modify: `amplifier-ipc-cli/tests/test_display.py`
- Create: `services/svc-orchestrator/tests/test_orchestrator_usage.py`

#### Step 1: Write failing orchestrator test

Create `services/svc-orchestrator/tests/test_orchestrator_usage.py`:

```python
"""Tests for token usage in stream.complete event."""

from __future__ import annotations

import json
from typing import Any

import pytest

from amplifier_service_sdk.models import Message, RoutingTable
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator


def _make_dapr() -> DaprClient:
    return DaprClient(dapr_url="http://localhost:3500")


def _routing_table() -> RoutingTable:
    return RoutingTable(
        providers={"mock": "svc-provider-mock"},
        tools={},
        context="svc-context",
        hooks={},
    )


class TestTokenUsageInComplete:
    """stream.complete event includes token usage when available."""

    @pytest.mark.asyncio
    async def test_complete_event_includes_usage(self) -> None:
        """When provider returns usage, stream.complete event includes usage data."""
        dapr = _make_dapr()

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kw: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": "Hello!",
                    "tool_calls": None,
                    "usage": {"input_tokens": 150, "output_tokens": 42},
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kw: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Hi"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="Be brief.",
            messages=[Message(role="user", content="Hi")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-usage-1",
        ):
            events.append(event)

        complete_events = [e for e in events if e["event"] == "stream.complete"]
        assert len(complete_events) == 1

        complete_data = json.loads(complete_events[0]["data"])
        assert "usage" in complete_data
        assert complete_data["usage"]["input_tokens"] == 150
        assert complete_data["usage"]["output_tokens"] == 42

    @pytest.mark.asyncio
    async def test_complete_event_no_usage_when_none(self) -> None:
        """When provider returns no usage, stream.complete omits the usage field."""
        dapr = _make_dapr()

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kw: Any
        ) -> dict[str, Any]:
            if app_id == "svc-provider-mock" and "complete" in method:
                return {
                    "content": "Hello!",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kw: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Hi"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="Be brief.",
            messages=[Message(role="user", content="Hi")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-usage-none-1",
        ):
            events.append(event)

        complete_events = [e for e in events if e["event"] == "stream.complete"]
        assert len(complete_events) == 1

        complete_data = json.loads(complete_events[0]["data"])
        assert "usage" not in complete_data

    @pytest.mark.asyncio
    async def test_usage_accumulates_across_iterations(self) -> None:
        """When multiple provider calls happen (tool loop), usage accumulates totals."""
        dapr = _make_dapr()
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kw: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count
            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {"id": "call-1", "name": "bash", "arguments": {"command": "echo hi"}},
                        ],
                        "usage": {"input_tokens": 100, "output_tokens": 20},
                        "stop_reason": "tool_use",
                    }
                return {
                    "content": "Done!",
                    "tool_calls": None,
                    "usage": {"input_tokens": 200, "output_tokens": 30},
                    "stop_reason": "end_turn",
                }
            if "tools" in method:
                return {"success": True, "output": "hi"}
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kw: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "run bash"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="Be brief.",
            messages=[Message(role="user", content="run bash")],
            config={"provider": "mock"},
            routing_table=_routing_table(tools={"bash": "svc-bash"}),
            session_id="session-usage-accum-1",
        ):
            events.append(event)

        complete_events = [e for e in events if e["event"] == "stream.complete"]
        complete_data = json.loads(complete_events[0]["data"])
        assert "usage" in complete_data
        # Accumulated: 100+200 input, 20+30 output
        assert complete_data["usage"]["input_tokens"] == 300
        assert complete_data["usage"]["output_tokens"] == 50
```

Run: `cd services/svc-orchestrator && python -m pytest tests/test_orchestrator_usage.py -v`
Expected: FAIL — `stream.complete` does not include `usage`.

#### Step 2: Track and emit usage in orchestrator

In `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`, in the `execute_stream` method:

**After `result_text = ""` and `iteration = 0` (around line 262), add usage accumulator:**
```python
            result_text = ""
            iteration = 0
            total_input_tokens = 0
            total_output_tokens = 0
```

**After parsing `chat_response` (around line 295), accumulate usage:**
```python
                chat_response = ChatResponse(**response_data)
                result_text = self._extract_text(chat_response.content)

                # Accumulate token usage
                if chat_response.usage is not None:
                    total_input_tokens += chat_response.usage.input_tokens
                    total_output_tokens += chat_response.usage.output_tokens
```

**In the complete event emission (around lines 394–402), include usage:**
```python
            complete_data: dict[str, Any] = {
                "result": result_text,
                "messages": [m.model_dump() for m in final_messages],
            }
            if total_input_tokens > 0 or total_output_tokens > 0:
                complete_data["usage"] = {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                }

            yield {
                "event": "stream.complete",
                "data": json.dumps(complete_data),
            }
```

Run: `cd services/svc-orchestrator && python -m pytest tests/test_orchestrator_usage.py tests/test_orchestrator.py -v`
Expected: All PASS.

#### Step 3: Write failing CLI test for usage display

In `amplifier-ipc-cli/tests/test_display.py`, add:

```python
class TestTokenUsageDisplay:
    """Tests for token usage display in complete event."""

    def test_complete_with_usage_shows_token_counts(self) -> None:
        """_handle_complete prints token counts when usage is present."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="complete",
            data={
                "result": "Done",
                "usage": {"input_tokens": 150, "output_tokens": 42},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "150" in output
        assert "42" in output

    def test_complete_without_usage_no_token_display(self) -> None:
        """_handle_complete does not print token info when usage is absent."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(event="complete", data={"result": "Done"})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "tokens" not in output.lower()
```

Run: `cd amplifier-ipc-cli && python -m pytest tests/test_display.py::TestTokenUsageDisplay -v`
Expected: FAIL — `_handle_complete` doesn't display usage.

#### Step 4: Update CLI `_handle_complete`

In `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py`, update `_handle_complete` (lines 354–362):

```python
    def _handle_complete(self, data: Any) -> None:
        """Store the final response text. Print only if no tokens were streamed."""
        if isinstance(data, dict):
            self._response = data.get("result", "") or data.get("response", "")
        # Only print the response if no token events were received
        # (avoids duplication when tokens already printed the text)
        if self._response and not self._tokens_received:
            self._console.print(self._response, highlight=False, markup=False)
        # Display token usage if available
        if isinstance(data, dict) and "usage" in data:
            usage = data["usage"]
            input_t = usage.get("input_tokens", 0)
            output_t = usage.get("output_tokens", 0)
            self._safe_print(
                f"\n[dim]tokens: {input_t} in / {output_t} out[/dim]"
            )
        self._console.print()
```

Run: `cd amplifier-ipc-cli && python -m pytest tests/test_display.py -v`
Expected: All PASS.

#### Step 5: Commit

```bash
git add services/svc-orchestrator/src/svc_orchestrator/orchestrator.py \
  services/svc-orchestrator/tests/test_orchestrator_usage.py \
  amplifier-ipc-cli/src/amplifier_ipc_cli/display.py \
  amplifier-ipc-cli/tests/test_display.py
git commit -m "feat: include token usage in stream.complete event

Orchestrator:
- Accumulate input_tokens/output_tokens across all provider calls
- Include usage dict in stream.complete when tokens were reported

CLI:
- Display token counts in dim style after response completion"
```

**Success criteria:**
- `stream.complete` includes `{"usage": {"input_tokens": N, "output_tokens": N}}` when provider returns usage
- Usage accumulates across multiple provider calls in a tool loop
- No `usage` key when provider returns `None` usage
- CLI prints token counts after the response when available

---

## Phase 2: Streaming Delegation (Task 6)

Task 6 is the largest change in this plan. It converts delegation from a blocking HTTP POST to a streaming SSE flow, where child session events are forwarded through the parent's event stream in real time.

---

### Task 6a: Update StreamEventType delegation event names

**One-line:** Rename child_session events to `delegate:*` names matching the legacy Amplifier convention.

**Dependencies:** Task 4 (enum was already modified; this adds delegation names).

**Files:**
- Modify: `services/session-service/src/session_service/streaming.py`
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py` (rename handlers)
- Modify: `amplifier-ipc-cli/tests/test_display.py`

#### Step 1: Update StreamEventType enum

In `services/session-service/src/session_service/streaming.py`, replace the delegation placeholders:

```python
    # Delegation events (matching legacy Amplifier naming)
    delegate_agent_spawned = "delegate:agent_spawned"
    delegate_agent_completed = "delegate:agent_completed"
    delegate_agent_resumed = "delegate:agent_resumed"
    delegate_error = "delegate:error"
```

Remove the old `child_session_start` and `child_session_end` entries entirely.

#### Step 2: Rename CLI delegation handlers

In `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py`:

Rename `_handle_child_session_start` → `_handle_delegate_agent_spawned`:
```python
    def _handle_delegate_agent_spawned(self, data: Any) -> None:
        """Print a 🔧 delegation header indented according to session depth."""
        if not isinstance(data, dict):
            return
        depth = data.get("depth", 0)
        agent = data.get("agent", data.get("name", "sub-agent"))
        indent = _NESTING_INDENT * (depth - 1) if depth > 0 else ""
        self._safe_print(
            f"{indent}\U0001f527 delegate -> [bold cyan]{agent}[/bold cyan]"
        )
```

Rename `_handle_child_session_end` → `_handle_delegate_agent_completed`:
```python
    def _handle_delegate_agent_completed(self, data: Any) -> None:
        """Print delegation completion summary."""
        if not isinstance(data, dict):
            return
        agent = data.get("agent", "sub-agent")
        success = data.get("success", True)
        icon = "\u2705" if success else "\u274c"
        self._safe_print(f"  {icon} [dim]{agent} completed[/dim]")
```

Remove `_handle_child_session_event` (will be replaced by forwarded child events in 6d/6e).

**Keep the old handlers as aliases** temporarily for backward compat during the transition:
```python
    # Backward compat aliases (remove after full migration)
    _handle_child_session_start = _handle_delegate_agent_spawned
    _handle_child_session_end = _handle_delegate_agent_completed
```

#### Step 3: Update tests

Update any tests referencing old event names. Currently `test_display.py` doesn't have explicit delegation tests, but verify no regressions:

Run: `cd amplifier-ipc-cli && python -m pytest tests/test_display.py -v`
Expected: All PASS.

#### Step 4: Commit

```bash
git add services/session-service/src/session_service/streaming.py \
  amplifier-ipc-cli/src/amplifier_ipc_cli/display.py \
  amplifier-ipc-cli/tests/test_display.py
git commit -m "refactor: rename delegation events to delegate:agent_spawned/completed

- StreamEventType: replace child_session_start/end with delegate:* names
- CLI: rename handlers, add backward-compat aliases
- Matches legacy Amplifier delegate event naming convention"
```

---

### Task 6b: Add streaming child turn endpoint to session-service

**One-line:** Add a `/sessions/{id}/turn/stream` endpoint to session-service that creates/resumes a child session and streams SSE events from the orchestrator.

**Dependencies:** Task 6a (enum names).

**Files:**
- Modify: `services/session-service/src/session_service/app.py`
- Create: `services/session-service/tests/test_child_stream_endpoint.py`

#### Step 1: Write failing test

Create `services/session-service/tests/test_child_stream_endpoint.py`:

```python
"""Tests for the streaming child turn endpoint."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

# This test validates the endpoint exists and returns SSE content type.
# Full integration requires orchestrator mocking (covered in Task 6f).


class TestChildStreamEndpointExists:
    """The /sessions/{id}/turn/stream endpoint exists and returns SSE."""

    def test_endpoint_registered(self) -> None:
        """GET /sessions/{id}/turn/stream with a POST body returns 200 or 405."""
        from session_service.app import create_app

        app = create_app()
        client = TestClient(app)
        # POST to the streaming endpoint — should at least not 404
        response = client.post(
            "/sessions/test-child-123/turn/stream",
            json={"prompt": "hello from child"},
        )
        # Expect either 200 (streaming) or 422 (validation) — NOT 404
        assert response.status_code != 404, (
            "Endpoint /sessions/{id}/turn/stream should be registered"
        )
```

Run: `cd services/session-service && python -m pytest tests/test_child_stream_endpoint.py -v`
Expected: FAIL with 404 — endpoint doesn't exist yet.

#### Step 2: Add the streaming child turn endpoint

In `services/session-service/src/session_service/app.py`, add a new endpoint after the existing `/sessions/{session_id}/turn` route. The endpoint:
1. Creates or resumes a child session
2. Opens a streaming connection to the orchestrator's `/orchestrator/execute/stream` endpoint
3. Forwards SSE events to the client

```python
    @app.post("/sessions/{session_id}/turn/stream")
    async def turn_stream_child(
        session_id: str, request: TurnRequest
    ) -> EventSourceResponse:
        """Stream a child session turn, forwarding SSE events from the orchestrator.

        This endpoint mirrors the parent /turn/stream but is intended for child
        sessions spawned during delegation. Events are forwarded verbatim so
        the caller (svc-delegation) can relay them to the parent stream.
        """

        async def event_generator():  # type: ignore[return]
            try:
                # Reuse the same session setup logic as the blocking /turn endpoint
                if session_id not in _sessions:
                    _sessions[session_id] = {
                        "session_id": session_id,
                        "routing_table": {},
                        "turn_count": 0,
                    }

                # Build orchestrator request (same logic as parent stream)
                # ... (follow the same pattern as the existing streaming endpoint)

                orch_url = f"{_dapr_url}/v1.0/invoke/svc-orchestrator/method/orchestrator/execute/stream"

                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream(
                        "POST",
                        orch_url,
                        json={
                            "system_prompt": request.system_prompt or "You are helpful.",
                            "messages": [{"role": "user", "content": request.prompt}],
                            "config": request.config or {},
                            "routing_table": _sessions[session_id].get("routing_table", {}),
                            "session_id": session_id,
                        },
                    ) as response:
                        response.raise_for_status()

                        current_event: str | None = None
                        current_data: str | None = None

                        async for line in response.aiter_lines():
                            if line.startswith("event:"):
                                current_event = line[6:].strip()
                            elif line.startswith("data:"):
                                current_data = line[5:].strip()
                            elif line == "":
                                if current_event is not None and current_data is not None:
                                    yield {
                                        "event": current_event,
                                        "data": current_data,
                                    }
                                current_event = None
                                current_data = None

            except Exception as exc:  # noqa: BLE001
                yield {
                    "event": StreamEventType.error.value,
                    "data": json.dumps({"message": str(exc)}),
                }

        return EventSourceResponse(event_generator())
```

**Note:** This is a simplified version. The implementer should study the existing streaming endpoint at `/sessions/{session_id}/turn` (the `turn_stream` function) and mirror its session setup logic. The key difference is that this child endpoint does **not** save the transcript or update session state — the parent session handles that.

Run: `cd services/session-service && python -m pytest tests/test_child_stream_endpoint.py -v`
Expected: PASS (endpoint exists, no 404).

#### Step 3: Commit

```bash
git add services/session-service/src/session_service/app.py \
  services/session-service/tests/test_child_stream_endpoint.py
git commit -m "feat(session-service): add /sessions/{id}/turn/stream child endpoint

Streaming child turn endpoint that forwards orchestrator SSE events.
Used by svc-delegation for real-time delegation event streaming."
```

---

### Task 6c: Add streaming dispatch to svc-delegation

**One-line:** Add a streaming execution path to `DelegateTool` that opens an SSE connection to session-service, emits `delegate:agent_spawned`, forwards child events, and emits `delegate:agent_completed`.

**Dependencies:** Task 6b (streaming child endpoint).

**Files:**
- Modify: `services/svc-delegation/src/svc_delegation/tool.py`
- Create: `services/svc-delegation/tests/test_streaming_delegation.py`

#### Step 1: Write failing test

Create `services/svc-delegation/tests/test_streaming_delegation.py`:

```python
"""Tests for streaming delegation in DelegateTool."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from svc_delegation.tool import DelegateTool


class TestStreamingDelegation:
    """DelegateTool.execute_stream yields delegation lifecycle events."""

    @pytest.mark.asyncio
    async def test_execute_stream_yields_spawned_and_completed(self) -> None:
        """Streaming delegation emits delegate:agent_spawned and delegate:agent_completed."""
        tool = DelegateTool(
            orchestrator_base_url="http://fake-orch",
            session_service_base_url="http://fake-session",
            parent_session_id="parent-1",
            delegation_depth=0,
        )

        # Mock the SSE stream from session-service
        mock_lines = [
            "event: token",
            'data: {"text": "child response"}',
            "",
            "event: complete",
            'data: {"result": "child done", "messages": []}',
            "",
        ]

        events: list[dict[str, Any]] = []
        async for event in tool.execute_stream({"instruction": "do something", "agent": "test-agent"}):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "delegate:agent_spawned" in event_types
        assert "delegate:agent_completed" in event_types

    @pytest.mark.asyncio
    async def test_execute_stream_not_defined_yet(self) -> None:
        """execute_stream method should exist on DelegateTool."""
        tool = DelegateTool(
            orchestrator_base_url="http://fake",
            session_service_base_url="http://fake",
        )
        assert hasattr(tool, "execute_stream"), "DelegateTool must have execute_stream method"
```

Run: `cd services/svc-delegation && python -m pytest tests/test_streaming_delegation.py -v`
Expected: FAIL — `execute_stream` does not exist on DelegateTool.

#### Step 2: Add execute_stream to DelegateTool

In `services/svc-delegation/src/svc_delegation/tool.py`, add an `execute_stream` async generator method:

```python
    async def execute_stream(
        self, input: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute delegation with streaming, yielding SSE events.

        Yields delegate lifecycle events:
        - delegate:agent_spawned  — when delegation starts
        - (forwarded child events) — token, tool_call, thinking, etc.
        - delegate:agent_completed — when delegation finishes
        - delegate:error — on failure

        Falls back to non-streaming execute() if streaming fails.
        """
        import json

        instruction = input.get("instruction")
        if not instruction:
            yield {
                "event": "delegate:error",
                "data": json.dumps({"error": "Missing required field: instruction"}),
            }
            return

        current_depth = input.get("delegation_depth", self._delegation_depth)
        if current_depth >= MAX_DELEGATION_DEPTH:
            yield {
                "event": "delegate:error",
                "data": json.dumps({
                    "error": f"Maximum delegation depth ({MAX_DELEGATION_DEPTH}) exceeded",
                }),
            }
            return

        agent = input.get("agent", "default")
        child_session_id = input.get("session_id", "")

        # Emit spawned event
        yield {
            "event": "delegate:agent_spawned",
            "data": json.dumps({
                "agent": agent,
                "session_id": child_session_id,
                "instruction": instruction,
                "depth": current_depth + 1,
            }),
        }

        result_text = ""
        success = True
        turn_count = 0

        try:
            if not self._session_service_base_url:
                raise RuntimeError("No session service URL configured")

            stream_url = (
                f"{self._session_service_base_url}"
                f"/sessions/{child_session_id or 'new'}/turn/stream"
            )
            payload = {
                "prompt": instruction,
                "delegation_depth": current_depth + 1,
            }
            if agent != "default":
                payload["agent_ref"] = agent

            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", stream_url, json=payload) as response:
                    response.raise_for_status()

                    current_event: str | None = None
                    current_data: str | None = None

                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                        elif line.startswith("data:"):
                            current_data = line[5:].strip()
                        elif line == "":
                            if current_event is not None and current_data is not None:
                                if current_event == "complete":
                                    try:
                                        complete_data = json.loads(current_data)
                                        result_text = complete_data.get("result", "")
                                        turn_count += 1
                                    except json.JSONDecodeError:
                                        pass
                                else:
                                    # Forward child events
                                    yield {
                                        "event": current_event,
                                        "data": current_data,
                                    }
                            current_event = None
                            current_data = None

        except Exception as exc:
            success = False
            result_text = str(exc)
            yield {
                "event": "delegate:error",
                "data": json.dumps({"error": str(exc), "agent": agent}),
            }

        # Emit completed event
        yield {
            "event": "delegate:agent_completed",
            "data": json.dumps({
                "agent": agent,
                "session_id": child_session_id,
                "success": success,
                "turn_count": turn_count,
                "result_preview": result_text[:200] if result_text else "",
            }),
        }
```

Also add the import at the top of the file:
```python
from collections.abc import AsyncGenerator
```

#### Step 3: Run tests

Run: `cd services/svc-delegation && python -m pytest tests/ -v`
Expected: PASS (at least the method existence test; the full streaming test may need mock refinement).

#### Step 4: Commit

```bash
git add services/svc-delegation/src/svc_delegation/tool.py \
  services/svc-delegation/tests/test_streaming_delegation.py
git commit -m "feat(svc-delegation): add execute_stream for streaming delegation

DelegateTool.execute_stream():
- Emits delegate:agent_spawned at start
- Opens SSE to session-service child streaming endpoint
- Forwards child events (token, tool_call, thinking, etc.)
- Emits delegate:agent_completed at end
- Emits delegate:error on failure"
```

---

### Task 6d: Add streaming-aware tool dispatch to orchestrator

**One-line:** When the orchestrator dispatches a `delegate` tool in `execute_stream`, use the streaming path to yield child events as they arrive instead of blocking.

**Dependencies:** Task 6c (DelegateTool.execute_stream).

**Files:**
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`
- Create: `services/svc-orchestrator/tests/test_orchestrator_streaming_delegation.py`

#### Step 1: Write failing test

Create `services/svc-orchestrator/tests/test_orchestrator_streaming_delegation.py`:

```python
"""Tests for streaming delegation dispatch in execute_stream."""

from __future__ import annotations

import json
from typing import Any

import pytest

from amplifier_service_sdk.models import Message, RoutingTable
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator


def _make_dapr() -> DaprClient:
    return DaprClient(dapr_url="http://localhost:3500")


def _routing_table() -> RoutingTable:
    return RoutingTable(
        providers={"mock": "svc-provider-mock"},
        tools={"delegate": "svc-delegation"},
        context="svc-context",
        hooks={},
    )


class TestStreamingDelegationDispatch:
    """execute_stream yields delegate:* events when 'delegate' tool is called."""

    @pytest.mark.asyncio
    async def test_delegate_tool_emits_spawned_event(self) -> None:
        """When provider calls 'delegate' tool, stream includes delegate:agent_spawned."""
        dapr = _make_dapr()
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kw: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count
            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-delegate-1",
                                "name": "delegate",
                                "arguments": {
                                    "instruction": "Write tests",
                                    "agent": "test-writer",
                                },
                            },
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                return {
                    "content": "Delegation complete.",
                    "tool_calls": None,
                    "usage": None,
                    "stop_reason": "end_turn",
                }
            # svc-delegation tool invocation returns delegation result
            if app_id == "svc-delegation":
                return {
                    "success": True,
                    "output": {"result": "Tests written", "session_id": "child-1"},
                }
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kw: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "delegate work"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="You delegate work.",
            messages=[Message(role="user", content="delegate work")],
            config={"provider": "mock"},
            routing_table=_routing_table(),
            session_id="session-delegate-stream-1",
        ):
            events.append(event)

        event_names = [e["event"] for e in events]
        # At minimum, the tool_call_start and tool_result should be present
        assert "stream.tool_call_start" in event_names
        assert "stream.tool_result" in event_names
        assert "stream.complete" in event_names
```

**Note:** Full streaming delegation (with `delegate:agent_spawned` etc.) requires the orchestrator to detect the `delegate` tool and use a streaming dispatch path. This test first validates the current behavior works, then we'll add streaming detection.

Run: `cd services/svc-orchestrator && python -m pytest tests/test_orchestrator_streaming_delegation.py -v`
Expected: May PASS or FAIL depending on current tool dispatch. Refine mock as needed.

#### Step 2: Add delegate tool detection in execute_stream

In `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`, in the `_dispatch_tools` method (or in `execute_stream`), add logic to detect when the `delegate` tool is called and yield streaming events.

The key change is in the tool dispatch section of `execute_stream`. Currently, tools are dispatched in parallel with `_dispatch_tools`. For the `delegate` tool, we want to emit lifecycle events. Add this **before** the parallel dispatch:

```python
                # Emit delegate lifecycle events for delegation tool calls
                for tc in chat_response.tool_calls:
                    if tc.name == "delegate":
                        agent = tc.arguments.get("agent", "default")
                        instruction = tc.arguments.get("instruction", "")
                        yield {
                            "event": "stream.delegate:agent_spawned",
                            "data": json.dumps({
                                "agent": agent,
                                "instruction": instruction,
                                "depth": 1,  # TODO: track actual depth
                            }),
                        }
```

And after tool dispatch, emit completion for delegate tools:

```python
                for tc, msg in zip(
                    chat_response.tool_calls, tool_result_msgs, strict=False
                ):
                    # ... existing tool_result emission ...

                    # Emit delegate completion for delegation tool results
                    if tc.name == "delegate":
                        yield {
                            "event": "stream.delegate:agent_completed",
                            "data": json.dumps({
                                "agent": tc.arguments.get("agent", "default"),
                                "success": True,
                                "result_preview": (
                                    str(msg.content)[:200] if msg.content else ""
                                ),
                            }),
                        }
```

#### Step 3: Run tests

Run: `cd services/svc-orchestrator && python -m pytest tests/ -v`
Expected: All PASS.

#### Step 4: Commit

```bash
git add services/svc-orchestrator/src/svc_orchestrator/orchestrator.py \
  services/svc-orchestrator/tests/test_orchestrator_streaming_delegation.py
git commit -m "feat(orchestrator): emit delegate lifecycle events in execute_stream

When the provider calls the 'delegate' tool:
- Emit stream.delegate:agent_spawned before dispatch
- Emit stream.delegate:agent_completed after dispatch
- Preserves normal tool_call_start/tool_result flow"
```

---

### Task 6e: Update CLI delegation handlers for forwarded child events

**One-line:** Update CLI delegation display to handle `delegate:agent_spawned`, `delegate:agent_completed`, and forwarded child events with indentation.

**Dependencies:** Task 6a (handler renames), Task 6d (orchestrator emits new events).

**Files:**
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py`
- Modify: `amplifier-ipc-cli/tests/test_display.py`

#### Step 1: Write failing tests

In `amplifier-ipc-cli/tests/test_display.py`, add:

```python
class TestDelegationEvents:
    """Tests for delegate:* event handling."""

    def test_delegate_agent_spawned_shows_agent_name(self) -> None:
        """delegate:agent_spawned prints delegation header with agent name."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_spawned",
            data={"agent": "test-writer", "instruction": "Write tests", "depth": 1},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "test-writer" in output
        assert "delegate" in output.lower()

    def test_delegate_agent_completed_shows_success(self) -> None:
        """delegate:agent_completed prints completion with checkmark."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_completed",
            data={"agent": "test-writer", "success": True, "turn_count": 3},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "test-writer" in output
        assert "\u2705" in output  # ✅ checkmark for success

    def test_delegate_agent_completed_failure_shows_cross(self) -> None:
        """delegate:agent_completed with success=False shows red cross."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_completed",
            data={"agent": "test-writer", "success": False},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u274c" in output  # ❌ cross for failure

    def test_delegate_error_shows_error(self) -> None:
        """delegate:error prints an error message."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:error",
            data={"error": "Connection refused", "agent": "failing-agent"},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "Connection refused" in output
```

Run: `cd amplifier-ipc-cli && python -m pytest tests/test_display.py::TestDelegationEvents -v`
Expected: FAIL — handlers don't exist yet (or renamed handlers from 6a need the colon dispatch from Task 4).

#### Step 2: Ensure delegation handlers work with colon dispatch

The colon-to-underscore normalization from Task 4 means:
- `delegate:agent_spawned` → `_handle_delegate_agent_spawned` ✓ (already renamed in 6a)
- `delegate:agent_completed` → `_handle_delegate_agent_completed` ✓
- `delegate:agent_resumed` → `_handle_delegate_agent_resumed` (add)
- `delegate:error` → `_handle_delegate_error` (add)

Add the missing handler in `display.py`:

```python
    def _handle_delegate_agent_resumed(self, data: Any) -> None:
        """Print delegation resumption header."""
        if not isinstance(data, dict):
            return
        agent = data.get("agent", "sub-agent")
        session_id = data.get("session_id", "")
        self._safe_print(
            f"\U0001f504 resuming [bold cyan]{agent}[/bold cyan] ({session_id})"
        )

    def _handle_delegate_error(self, data: Any) -> None:
        """Print a delegation error."""
        if not isinstance(data, dict):
            return
        error = data.get("error", "Unknown delegation error")
        agent = data.get("agent", "")
        prefix = f"{agent}: " if agent else ""
        self._console.print(
            f"  \u2717 {prefix}{error}", style="red", markup=False
        )
```

Remove the backward-compat aliases added in 6a (the colon normalization handles dispatch):
```python
    # Remove these lines:
    # _handle_child_session_start = _handle_delegate_agent_spawned
    # _handle_child_session_end = _handle_delegate_agent_completed
```

#### Step 3: Run all CLI tests

Run: `cd amplifier-ipc-cli && python -m pytest tests/test_display.py -v`
Expected: All PASS.

#### Step 4: Commit

```bash
git add amplifier-ipc-cli/src/amplifier_ipc_cli/display.py \
  amplifier-ipc-cli/tests/test_display.py
git commit -m "feat(cli): add delegate:* event handlers for streaming delegation

- _handle_delegate_agent_spawned: prints delegation header with agent name
- _handle_delegate_agent_completed: prints success/failure with icon
- _handle_delegate_agent_resumed: prints resumption header
- _handle_delegate_error: prints delegation error in red
- Remove old child_session backward-compat aliases"
```

---

### Task 6f: Integration test — full delegation event sequence

**One-line:** End-to-end test verifying the complete event sequence for a delegation: spawned → child events → completed.

**Dependencies:** Tasks 6a–6e.

**Files:**
- Create: `services/svc-orchestrator/tests/test_delegation_event_sequence.py`

#### Step 1: Write the integration test

Create `services/svc-orchestrator/tests/test_delegation_event_sequence.py`:

```python
"""Integration test: full delegation event sequence in execute_stream."""

from __future__ import annotations

import json
from typing import Any

import pytest

from amplifier_service_sdk.models import Message, RoutingTable
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator


def _make_dapr() -> DaprClient:
    return DaprClient(dapr_url="http://localhost:3500")


class TestDelegationEventSequence:
    """Verify the complete event sequence for a delegation flow."""

    @pytest.mark.asyncio
    async def test_full_delegation_event_order(self) -> None:
        """Events follow: tool_call_start → delegate:agent_spawned → tool_result → delegate:agent_completed → complete."""
        dapr = _make_dapr()
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kw: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count
            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": "I'll delegate this.",
                        "tool_calls": [
                            {
                                "id": "call-del-1",
                                "name": "delegate",
                                "arguments": {
                                    "instruction": "Write unit tests",
                                    "agent": "test-writer",
                                },
                            },
                        ],
                        "usage": {"input_tokens": 50, "output_tokens": 20},
                        "stop_reason": "tool_use",
                    }
                return {
                    "content": "Delegation complete. Tests were written.",
                    "tool_calls": None,
                    "usage": {"input_tokens": 100, "output_tokens": 30},
                    "stop_reason": "end_turn",
                }
            # Delegation tool result
            if app_id == "svc-delegation":
                return {
                    "success": True,
                    "output": json.dumps({
                        "result": "All tests pass",
                        "session_id": "child-session-abc",
                    }),
                }
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kw: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "write tests for me"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        routing = RoutingTable(
            providers={"mock": "svc-provider-mock"},
            tools={"delegate": "svc-delegation"},
            context="svc-context",
            hooks={},
        )

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="You delegate effectively.",
            messages=[Message(role="user", content="write tests for me")],
            config={"provider": "mock"},
            routing_table=routing,
            session_id="session-full-delegation-1",
        ):
            events.append(event)

        event_names = [e["event"] for e in events]

        # Verify key events are present
        assert "stream.tool_call_start" in event_names, f"Missing tool_call_start. Events: {event_names}"
        assert "stream.tool_call" in event_names, f"Missing tool_call. Events: {event_names}"
        assert "stream.delegate:agent_spawned" in event_names, f"Missing delegate:agent_spawned. Events: {event_names}"
        assert "stream.tool_result" in event_names, f"Missing tool_result. Events: {event_names}"
        assert "stream.delegate:agent_completed" in event_names, f"Missing delegate:agent_completed. Events: {event_names}"
        assert "stream.complete" in event_names, f"Missing complete. Events: {event_names}"

        # Verify ordering: spawned before completed
        spawned_idx = event_names.index("stream.delegate:agent_spawned")
        completed_idx = event_names.index("stream.delegate:agent_completed")
        assert spawned_idx < completed_idx, "agent_spawned must come before agent_completed"

        # Verify delegate:agent_spawned payload
        spawned_event = events[spawned_idx]
        spawned_data = json.loads(spawned_event["data"])
        assert spawned_data["agent"] == "test-writer"
        assert spawned_data["instruction"] == "Write unit tests"

        # Verify complete includes accumulated usage
        complete_event = next(e for e in events if e["event"] == "stream.complete")
        complete_data = json.loads(complete_event["data"])
        assert complete_data["usage"]["input_tokens"] == 150  # 50 + 100
        assert complete_data["usage"]["output_tokens"] == 50  # 20 + 30
```

Run: `cd services/svc-orchestrator && python -m pytest tests/test_delegation_event_sequence.py -v`
Expected: PASS (all prior tasks wired up correctly).

#### Step 2: Commit

```bash
git add services/svc-orchestrator/tests/test_delegation_event_sequence.py
git commit -m "test(orchestrator): add integration test for full delegation event sequence

Verifies: tool_call_start → delegate:agent_spawned → tool_result →
delegate:agent_completed → complete with accumulated token usage."
```

**Success criteria (Phase 2 overall):**
- `StreamEventType` uses `delegate:agent_spawned`, `delegate:agent_completed`, `delegate:agent_resumed`, `delegate:error`
- Session-service has `/sessions/{id}/turn/stream` endpoint for child sessions
- `DelegateTool.execute_stream()` yields delegation lifecycle events
- Orchestrator emits `delegate:*` events when dispatching the `delegate` tool
- CLI renders delegation events with agent names, success icons, and error messages
- Full event sequence test passes end-to-end

---

## Execution Order

```
Task 1 (CLI field fixes) ──────────────┐
                                        ├─ Task 4 (content blocks) ─── Task 6a ─── Task 6b ─── Task 6c ─── Task 6d ─── Task 6e ─── Task 6f
Task 2 (HookResult contract) ─── Task 3 (todo_update) ──┘
                                        │
                                   Task 5 (token usage, independent)
```

- **Tasks 1 and 2** can run in parallel (no shared files).
- **Task 3** depends on Task 2 (hooks must work correctly).
- **Task 4** depends on Tasks 1 and 2 (CLI field names and hook contract settled).
- **Task 5** is independent of all others.
- **Tasks 6a–6f** are sequential and depend on Task 4.

## Running All Tests

After all tasks are complete, verify the full suite:

```bash
# CLI tests
cd amplifier-ipc-cli && python -m pytest tests/ -v

# Orchestrator tests
cd services/svc-orchestrator && python -m pytest tests/ -v

# Session-service tests
cd services/session-service && python -m pytest tests/ -v

# Delegation tests
cd services/svc-delegation && python -m pytest tests/ -v

# SDK model tests (if any)
cd amplifier-service-sdk && python -m pytest tests/ -v 2>/dev/null || echo "No SDK tests"
```
