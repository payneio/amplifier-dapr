# IPC Event Parity — Phase 2 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Add the 9 remaining orchestrator-level event emissions (`execution:start`, `execution:end`, `provider:resolve`, `llm:request`, `llm:response`, `content_block:delta`, `thinking:delta`, `thinking:final`, `provider:throttle`) to the streaming orchestrator, completing the core event loop.

**Architecture:** All 9 events are emitted by the streaming orchestrator via the existing `_hook_emit()` IPC mechanism. Event name constants already exist in `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py` from Phase 1. The only code changes are in `streaming.py` (expand imports, add emission calls) and `test_orchestrator.py` (new tests). One structural change: the `_apply_rate_limit_delay()` method gains a `provider_name` parameter for the `provider:throttle` payload, and `execute()` gets a `try/finally` wrapper for the `execution:end` error path.

**Tech Stack:** Python 3.11+, Pydantic, pytest with `@pytest.mark.asyncio`, uv for package management.

**Design doc:** `docs/plans/2026-03-25-ipc-event-parity-design.md`
**Phase 1 plan:** `docs/plans/2026-03-25-ipc-event-parity-phase1-plan.md`

---

## Context for the Implementer

### Files You'll Touch

| Action | Path |
|---|---|
| **Modify** | `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` (687 lines) |
| **Modify** | `services/amplifier-foundation/tests/test_orchestrator.py` (851 lines, 15 existing tests) |

No new files. No package or dependency changes.

### Existing Patterns You Must Follow

**Event emission** — The orchestrator emits hook events with:
```python
await self._hook_emit(client, EVENT_CONSTANT, {"key": value})
```
This calls `client.request("request.hook_emit", {"event": ..., "data": ...})` and returns a `HookResult`.

**Event constants** — Imported from `amplifier_ipc_protocol.events`. Current import block (line 30–34):
```python
from amplifier_ipc_protocol.events import (
    CONTENT_BLOCK_END,
    CONTENT_BLOCK_START,
    PROVIDER_RESPONSE,
)
```

**Test pattern** — Each test creates a `MockClient` with canned `responses` dict, instantiates `StreamingOrchestrator`, calls `orch.execute(prompt, config, client)`, then asserts on `client.requests` (for hook_emit calls) or `client.call_log` (for ordering). Tests use `@pytest.mark.asyncio` and the local-import pattern:
```python
@pytest.mark.asyncio
async def test_orchestrator_emits_xyz() -> None:
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator
    ...
```

**Test numbering** — Existing tests are numbered Test 1–15 in comments. Phase 2 tests continue from Test 16.

**MockClient** — Defined at top of test file (line 23). Supports `Sequence(r1, r2)` for multi-call methods. Records `requests` (method, params), `notifications` (method, params), and `call_log` (kind, method, params).

**Helper functions** — `hook_continue()`, `hook_deny(reason)`, `chat_response(text, tool_calls)`, `tool_result_ok(output)`, `Sequence(*responses)`.

### Key Variables Available in `execute()`

- `provider_name` — `str`, read from config at line 122: `config.get("provider_name", "unknown")`
- `iteration` — `int`, loop counter starting at 1 (line 152+157)
- `messages` — `list[Message]`, from context (line 173)
- `chat_request` — `ChatRequest` model (line 197)
- `response_raw` — raw dict from provider (line 204)
- `chat_response` — validated `ChatResponse` model (line 270)
- `_block_idx`, `_block_type` — set inside the content blocks loop (lines 288-295)

### Running Tests

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```

---

## Task 1: Expand Imports from `amplifier_ipc_protocol.events`

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`

**Step 1: Update the import block**

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, find the import block at lines 30–34:

```python
from amplifier_ipc_protocol.events import (
    CONTENT_BLOCK_END,
    CONTENT_BLOCK_START,
    PROVIDER_RESPONSE,
)
```

Replace with:

```python
from amplifier_ipc_protocol.events import (
    CONTENT_BLOCK_DELTA,
    CONTENT_BLOCK_END,
    CONTENT_BLOCK_START,
    EXECUTION_END,
    EXECUTION_START,
    LLM_REQUEST,
    LLM_RESPONSE,
    PROVIDER_RESOLVE,
    PROVIDER_RESPONSE,
    PROVIDER_THROTTLE,
    THINKING_DELTA,
    THINKING_FINAL,
)
```

**Step 2: Verify the import works**

```bash
cd services/amplifier-foundation && python -c "from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator; print('OK')" && cd ../..
```
Expected: `OK`

**Step 3: Run existing tests to verify no regressions**

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```
Expected: All 15 existing tests PASS.

**Step 4: Commit**

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py
git commit -m "feat(events): expand orchestrator imports for Phase 2 event constants"
```

---

## Task 2: Emit `execution:start` and `execution:end`

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` — add emissions + try/finally wrapper
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py` — add 4 tests

### Step 1: Write the failing tests

Append to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
# ---------------------------------------------------------------------------
# Test 16: execution:start emitted at the beginning of execute()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_execution_start() -> None:
    """execution:start is the first hook event emitted by execute()."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Hi!"),
        }
    )

    await orch.execute("Hello", {"provider_name": "anthropic"}, client)

    hook_emits = [
        params
        for method, params in client.requests
        if method == "request.hook_emit" and isinstance(params, dict)
    ]

    # execution:start must be the very first hook event
    assert len(hook_emits) > 0, "Expected at least one hook_emit call"
    assert hook_emits[0]["event"] == "execution:start", (
        f"Expected first hook event to be execution:start, got {hook_emits[0]['event']!r}"
    )
    assert hook_emits[0]["data"] == {"prompt": "Hello"}, (
        f"Expected payload {{prompt: 'Hello'}}, got {hook_emits[0]['data']!r}"
    )


# ---------------------------------------------------------------------------
# Test 17: execution:end emitted with status='completed' on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_execution_end_completed() -> None:
    """execution:end emitted with status='completed' on normal exit."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Done!"),
        }
    )

    result = await orch.execute("Hello", {}, client)
    assert result == "Done!"

    end_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "execution:end"
    ]

    assert len(end_events) == 1, (
        f"Expected exactly 1 execution:end, got {len(end_events)}"
    )
    data = end_events[0]["data"]
    assert data["response"] == "Done!"
    assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Test 18: execution:end emitted with status='cancelled' when cancelled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_execution_end_cancelled() -> None:
    """execution:end emitted with status='cancelled' when orchestrator is cancelled."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    # Provider returns a response with tool calls, but cancel before tools run
    tool_call_response = chat_response(
        text="Let me check",
        tool_calls=[{"id": "tc1", "tool": "read_file", "arguments": {"path": "x"}}],
    )

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": tool_call_response,
            "request.tool_execute": tool_result_ok("file content"),
        }
    )

    # Cancel after first iteration's tool calls complete (checked at top of next iteration)
    orch._cancelled = True

    result = await orch.execute("Read file", {}, client)

    end_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "execution:end"
    ]

    assert len(end_events) == 1, (
        f"Expected exactly 1 execution:end, got {len(end_events)}"
    )
    assert end_events[0]["data"]["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Test 19: execution:end emitted with status='error' when provider raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_execution_end_error() -> None:
    """execution:end emitted with status='error' when execute() raises."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    # Provider raises a non-retryable error
    class ProviderError(Exception):
        retryable = False

    def raise_provider_error(*_args: Any, **_kwargs: Any) -> None:
        raise ProviderError("model overloaded")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
        }
    )
    # Override provider_complete to raise
    original_request = client.request

    async def request_with_error(method: str, params: Any = None) -> Any:
        if method == "request.provider_complete":
            raise ProviderError("model overloaded")
        return await original_request(method, params)

    client.request = request_with_error  # type: ignore[assignment]

    with pytest.raises(ProviderError):
        await orch.execute("Hello", {}, client)

    # execution:end must still be emitted (via finally)
    end_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "execution:end"
    ]

    assert len(end_events) == 1, (
        f"Expected exactly 1 execution:end even on error, got {len(end_events)}"
    )
    assert end_events[0]["data"]["status"] == "error"
    assert end_events[0]["data"]["response"] == ""
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_execution_start tests/test_orchestrator.py::test_orchestrator_emits_execution_end_completed tests/test_orchestrator.py::test_orchestrator_emits_execution_end_cancelled tests/test_orchestrator.py::test_orchestrator_emits_execution_end_error -v && cd ../..
```
Expected: 4 FAIL — no `execution:start` or `execution:end` events emitted.

### Step 3: Add execution:start emission

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, find this block at line 119:

```python
        # Allow config overrides
        max_iterations: int = config.get("max_iterations", self.max_iterations)
```

Insert **before** it (immediately after the docstring's closing `"""`):

```python
        # --- emit execution:start (first event in execute) ---
        await self._hook_emit(client, EXECUTION_START, {"prompt": prompt})

```

### Step 4: Add try/finally wrapper and execution:end emission

The `execute()` method currently has three exit paths: success (line 424 `return response_text`), cancelled (line 392 `return response_text`), and error (line 243 `raise`). We need a `try/finally` to guarantee `execution:end` fires on all paths.

Find the line right after the `execution:start` emission you just added and the config overrides block (the line that reads `# Reset per-execute state`):

```python
        # Reset per-execute state
        self._pending_ephemeral_injections = []
        self._last_provider_call_end = None
        self._cancelled = False
```

Insert **before** `# Reset per-execute state`:

```python
        _execution_status = "completed"
        _execution_response = ""
```

Now wrap the body of execute() from `# Reset per-execute state` through to the final `return response_text` in a try/except/finally. Find the `# Reset per-execute state` line and everything that follows it (the entire remaining method body). The structure should become:

```python
        _execution_status = "completed"
        _execution_response = ""
        try:
            # Reset per-execute state
            self._pending_ephemeral_injections = []
            ...existing body...
            return response_text
        except Exception:
            _execution_status = "error"
            raise
        finally:
            await self._hook_emit(
                client,
                EXECUTION_END,
                {"response": _execution_response, "status": _execution_status},
            )
```

Specifically, you need to:

1. Add `try:` before `# Reset per-execute state` and indent the entire body one level deeper.

2. At the **cancelled** exit path (line ~392), set `_execution_response` and `_execution_status` before returning. Find:
```python
        if _was_cancelled:
            logger.info("Orchestrator cancelled after %d iteration(s)", iteration)
            return response_text
```
Replace with:
```python
        if _was_cancelled:
            logger.info("Orchestrator cancelled after %d iteration(s)", iteration)
            _execution_status = "cancelled"
            _execution_response = response_text
            return response_text
```

3. At the **success** exit path (last `return response_text`), set `_execution_response` before returning. Find the final:
```python
            return response_text
```
(the one after `prompt:complete` emission). Replace with:
```python
            _execution_response = response_text
            return response_text
```

4. Add the except/finally after the try block's last return:
```python
        except Exception:
            _execution_status = "error"
            raise
        finally:
            await self._hook_emit(
                client,
                EXECUTION_END,
                {"response": _execution_response, "status": _execution_status},
            )
```

### Step 5: Run tests to verify they pass

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_execution_start tests/test_orchestrator.py::test_orchestrator_emits_execution_end_completed tests/test_orchestrator.py::test_orchestrator_emits_execution_end_cancelled tests/test_orchestrator.py::test_orchestrator_emits_execution_end_error -v && cd ../..
```
Expected: 4 PASS.

### Step 6: Run the full test suite to check for regressions

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```
Expected: All 19 tests pass. The new `try/except/finally` re-raises exceptions, so existing error-path behavior is preserved.

### Step 7: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat(events): emit execution:start/end with try/finally for error path"
```

---

## Task 3: Emit `provider:resolve`

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` — one-liner emission
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py` — 1 test

### Step 1: Write the failing test

Append to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
# ---------------------------------------------------------------------------
# Test 20: provider:resolve emitted after provider_name is read from config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_provider_resolve() -> None:
    """provider:resolve emitted with the resolved provider name."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Hi!"),
        }
    )

    await orch.execute("Hello", {"provider_name": "anthropic"}, client)

    resolve_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "provider:resolve"
    ]

    assert len(resolve_events) == 1, (
        f"Expected exactly 1 provider:resolve, got {len(resolve_events)}"
    )
    assert resolve_events[0]["data"] == {"provider": "anthropic"}

    # provider:resolve must come after execution:start but before prompt:submit
    hook_events_in_order = [
        params["event"]
        for method, params in client.requests
        if method == "request.hook_emit" and isinstance(params, dict)
    ]
    exec_start_idx = hook_events_in_order.index("execution:start")
    resolve_idx = hook_events_in_order.index("provider:resolve")
    submit_idx = hook_events_in_order.index("prompt:submit")
    assert exec_start_idx < resolve_idx < submit_idx, (
        f"Expected execution:start < provider:resolve < prompt:submit, "
        f"got indices {exec_start_idx} < {resolve_idx} < {submit_idx}"
    )
```

### Step 2: Run test to verify it fails

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_provider_resolve -v && cd ../..
```
Expected: FAIL — no `provider:resolve` event.

### Step 3: Add provider:resolve emission

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, find this line (inside the `try:` block):

```python
        provider_name: str = config.get("provider_name", "unknown")
```

Add immediately after it:

```python

            # --- emit provider:resolve ---
            await self._hook_emit(client, PROVIDER_RESOLVE, {"provider": provider_name})
```

**Important:** Make sure the indentation matches the surrounding code inside the `try` block. After Task 2, the body of execute() is indented one extra level inside `try:`.

### Step 4: Run test to verify it passes

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_provider_resolve -v && cd ../..
```
Expected: PASS.

### Step 5: Run full test suite

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```
Expected: All 20 tests pass.

### Step 6: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat(events): emit provider:resolve after reading provider_name from config"
```

---

## Task 4: Emit `llm:request` and `llm:response`

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` — 2 emission sites
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py` — 2 tests

### Step 1: Write the failing tests

Append to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
# ---------------------------------------------------------------------------
# Test 21: llm:request emitted before provider.complete call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_llm_request() -> None:
    """llm:request emitted immediately before the provider.complete call."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": chat_response("Hi!"),
        }
    )

    await orch.execute("Hello", {"provider_name": "claude"}, client)

    llm_req_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "llm:request"
    ]

    assert len(llm_req_events) == 1, (
        f"Expected 1 llm:request, got {len(llm_req_events)}"
    )

    data = llm_req_events[0]["data"]
    assert data["provider"] == "claude"
    assert data["message_count"] == 0  # context starts empty
    assert data["iteration"] == 1

    # llm:request must come before provider_complete in call_log
    call_methods = [method for _, method, _ in client.call_log if _ != "notification"]
    llm_req_idx = next(
        i for i, (kind, method, _) in enumerate(client.call_log)
        if kind == "request" and method == "request.hook_emit"
        and isinstance(_, dict) and _.get("event") == "llm:request"
    )
    provider_complete_idx = next(
        i for i, (kind, method, _) in enumerate(client.call_log)
        if kind == "request" and method == "request.provider_complete"
    )
    assert llm_req_idx < provider_complete_idx, (
        f"llm:request (idx {llm_req_idx}) must come before provider_complete (idx {provider_complete_idx})"
    )


# ---------------------------------------------------------------------------
# Test 22: llm:response emitted after successful provider.complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_llm_response() -> None:
    """llm:response emitted after provider.complete with usage and status."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    provider_result = {
        "content": "Response!",
        "text": "Response!",
        "tool_calls": None,
        "usage": {"input_tokens": 50, "output_tokens": 20},
        "finish_reason": None,
    }

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": provider_result,
        }
    )

    await orch.execute("Hello", {"provider_name": "anthropic"}, client)

    llm_resp_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "llm:response"
    ]

    assert len(llm_resp_events) == 1, (
        f"Expected 1 llm:response, got {len(llm_resp_events)}"
    )

    data = llm_resp_events[0]["data"]
    assert data["provider"] == "anthropic"
    assert data["status"] == "ok"
    # Usage may be dict or Pydantic model
    usage = data["usage"]
    if isinstance(usage, dict):
        assert usage["input_tokens"] == 50
        assert usage["output_tokens"] == 20
    else:
        assert getattr(usage, "input_tokens", None) == 50
        assert getattr(usage, "output_tokens", None) == 20

    # llm:response must come after provider_complete and before provider:response
    hook_events = [
        params["event"]
        for method, params in client.requests
        if method == "request.hook_emit" and isinstance(params, dict)
    ]
    llm_resp_idx = hook_events.index("llm:response")
    prov_resp_idx = hook_events.index("provider:response")
    assert llm_resp_idx < prov_resp_idx, (
        f"llm:response (idx {llm_resp_idx}) must come before provider:response (idx {prov_resp_idx})"
    )
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_llm_request tests/test_orchestrator.py::test_orchestrator_emits_llm_response -v && cd ../..
```
Expected: 2 FAIL — no `llm:request` or `llm:response` events.

### Step 3: Add llm:request emission

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, find the provider.complete call site. Look for this line:

```python
            # --- call provider.complete (with retry + exponential backoff) ---
            response_raw: Any = None
```

Insert immediately **before** it:

```python
            # --- emit llm:request before provider call ---
            await self._hook_emit(
                client,
                LLM_REQUEST,
                {
                    "provider": provider_name,
                    "message_count": len(messages),
                    "iteration": iteration,
                },
            )

```

### Step 4: Add llm:response emission

Find the `chat_response = ChatResponse.model_validate(response_raw)` line (around line 270), followed by the existing `provider:response` emission. Insert the `llm:response` emission **after** `ChatResponse.model_validate` and **before** the `provider:response` emission. Find:

```python
            chat_response = ChatResponse.model_validate(response_raw)

            # --- emit provider:response hook ---
```

Replace with:

```python
            chat_response = ChatResponse.model_validate(response_raw)

            # --- emit llm:response after successful provider call ---
            await self._hook_emit(
                client,
                LLM_RESPONSE,
                {
                    "provider": provider_name,
                    "usage": chat_response.usage,
                    "status": "ok",
                },
            )

            # --- emit provider:response hook ---
```

### Step 5: Run tests to verify they pass

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_llm_request tests/test_orchestrator.py::test_orchestrator_emits_llm_response -v && cd ../..
```
Expected: 2 PASS.

### Step 6: Run full test suite

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```
Expected: All 22 tests pass.

### Step 7: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat(events): emit llm:request before and llm:response after provider.complete"
```

---

## Task 5: Emit `content_block:delta`

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` — add emission inside content block loop
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py` — 1 test

### Step 1: Write the failing test

Append to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
# ---------------------------------------------------------------------------
# Test 23: content_block:delta emitted for each content block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_content_block_delta() -> None:
    """content_block:delta emitted between content_block:start and content_block:end."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    response_with_blocks = {
        "content": "My answer.",
        "text": "My answer.",
        "tool_calls": None,
        "usage": None,
        "finish_reason": None,
        "content_blocks": [
            {"type": "thinking", "thinking": "Hmm let me think..."},
            {"type": "text", "text": "My answer."},
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

    await orch.execute("Think", {}, client)

    delta_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "content_block:delta"
    ]

    # One delta per block (thinking + text)
    assert len(delta_events) == 2, (
        f"Expected 2 content_block:delta events, got {len(delta_events)}"
    )

    # Block 0: thinking block
    assert delta_events[0]["data"]["index"] == 0
    assert delta_events[0]["data"]["block_type"] == "thinking"
    assert delta_events[0]["data"]["delta"] == "Hmm let me think..."

    # Block 1: text block
    assert delta_events[1]["data"]["index"] == 1
    assert delta_events[1]["data"]["block_type"] == "text"
    assert delta_events[1]["data"]["delta"] == "My answer."

    # Verify ordering: start(0), delta(0), end(0), start(1), delta(1), end(1)
    block_events = [
        (params["event"], params["data"]["index"])
        for kind, method, params in client.call_log
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event", "").startswith("content_block:")
    ]
    expected = [
        ("content_block:start", 0),
        ("content_block:delta", 0),
        ("content_block:end", 0),
        ("content_block:start", 1),
        ("content_block:delta", 1),
        ("content_block:end", 1),
    ]
    assert block_events == expected, (
        f"Expected block event ordering {expected}, got {block_events}"
    )
```

### Step 2: Run test to verify it fails

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_content_block_delta -v && cd ../..
```
Expected: FAIL — no `content_block:delta` events.

### Step 3: Add content_block:delta emission

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, find the content blocks loop. Locate the section between `CONTENT_BLOCK_START` and the thinking-block extraction. Currently (after Phase 1) it looks like:

```python
                    # Emit content_block:start before processing
                    await self._hook_emit(
                        client,
                        CONTENT_BLOCK_START,
                        {"block_type": _block_type, "index": _block_idx},
                    )

                    if isinstance(block, ThinkingBlock):
                        thinking_text = block.thinking
```

We need to extract the block's content (text or thinking) and emit a delta between `CONTENT_BLOCK_START` and the thinking notification. Replace the section from after the `CONTENT_BLOCK_START` emission up to (and including) the `CONTENT_BLOCK_END` emission with:

```python
                    # Emit content_block:start before processing
                    await self._hook_emit(
                        client,
                        CONTENT_BLOCK_START,
                        {"block_type": _block_type, "index": _block_idx},
                    )

                    # Extract block content for delta emission
                    if isinstance(block, ThinkingBlock):
                        thinking_text = block.thinking
                        _block_content = thinking_text or ""
                    elif isinstance(block, dict) and block.get("type") == "thinking":
                        thinking_text = block.get("thinking", "")
                        _block_content = thinking_text
                    else:
                        thinking_text = None
                        # Text block: extract text content
                        if isinstance(block, dict):
                            _block_content = block.get("text", "")
                        elif hasattr(block, "text"):
                            _block_content = block.text or ""
                        else:
                            _block_content = ""

                    # Emit content_block:delta with the block's content
                    if _block_content:
                        await self._hook_emit(
                            client,
                            CONTENT_BLOCK_DELTA,
                            {
                                "index": _block_idx,
                                "block_type": _block_type,
                                "delta": _block_content,
                            },
                        )

                    if thinking_text:
                        await client.send_notification(
                            STREAM_THINKING, {"thinking": thinking_text}
                        )

                    # Emit content_block:end after processing
                    await self._hook_emit(
                        client,
                        CONTENT_BLOCK_END,
                        {"block_type": _block_type, "index": _block_idx},
                    )
```

### Step 4: Run test to verify it passes

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_content_block_delta -v && cd ../..
```
Expected: PASS.

### Step 5: Run full test suite

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```
Expected: All 23 tests pass. The thinking notification test (Test 5) must still pass — thinking_text extraction is preserved.

### Step 6: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat(events): emit content_block:delta inside content block loop"
```

---

## Task 6: Emit `thinking:delta` and `thinking:final`

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` — 2 emissions alongside STREAM_THINKING
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py` — 2 tests

### Step 1: Write the failing tests

Append to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
# ---------------------------------------------------------------------------
# Test 24: thinking:delta emitted for thinking blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_thinking_delta() -> None:
    """thinking:delta emitted for blocks with non-empty thinking text."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    response_with_thinking = {
        "content": "My answer.",
        "text": "My answer.",
        "tool_calls": None,
        "usage": None,
        "finish_reason": None,
        "content_blocks": [
            {"type": "thinking", "thinking": "Step 1: consider X..."},
            {"type": "text", "text": "My answer."},
        ],
    }

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": response_with_thinking,
        }
    )

    await orch.execute("Think about X", {}, client)

    thinking_delta_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "thinking:delta"
    ]

    # Only the thinking block emits thinking:delta (not the text block)
    assert len(thinking_delta_events) == 1, (
        f"Expected 1 thinking:delta, got {len(thinking_delta_events)}"
    )
    assert thinking_delta_events[0]["data"] == {
        "index": 0,
        "delta": "Step 1: consider X...",
    }


# ---------------------------------------------------------------------------
# Test 25: thinking:final emitted after thinking:delta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_thinking_final() -> None:
    """thinking:final emitted for thinking blocks with the complete text."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    response_with_thinking = {
        "content": "Answer.",
        "text": "Answer.",
        "tool_calls": None,
        "usage": None,
        "finish_reason": None,
        "content_blocks": [
            {"type": "thinking", "thinking": "I need to reason..."},
            {"type": "text", "text": "Answer."},
        ],
    }

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": response_with_thinking,
        }
    )

    await orch.execute("Reason", {}, client)

    thinking_final_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "thinking:final"
    ]

    assert len(thinking_final_events) == 1, (
        f"Expected 1 thinking:final, got {len(thinking_final_events)}"
    )
    assert thinking_final_events[0]["data"] == {
        "index": 0,
        "text": "I need to reason...",
    }

    # thinking:delta must come before thinking:final in call_log
    hook_events = [
        params["event"]
        for kind, method, params in client.call_log
        if kind == "request"
        and method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event", "").startswith("thinking:")
    ]
    assert hook_events == ["thinking:delta", "thinking:final"], (
        f"Expected [thinking:delta, thinking:final], got {hook_events}"
    )
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_thinking_delta tests/test_orchestrator.py::test_orchestrator_emits_thinking_final -v && cd ../..
```
Expected: 2 FAIL — no `thinking:delta` or `thinking:final` events.

### Step 3: Add thinking:delta and thinking:final emissions

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, find the thinking notification block inside the content blocks loop. After Task 5, it looks like:

```python
                    if thinking_text:
                        await client.send_notification(
                            STREAM_THINKING, {"thinking": thinking_text}
                        )
```

Replace with:

```python
                    if thinking_text:
                        await self._hook_emit(
                            client,
                            THINKING_DELTA,
                            {"index": _block_idx, "delta": thinking_text},
                        )
                        await self._hook_emit(
                            client,
                            THINKING_FINAL,
                            {"index": _block_idx, "text": thinking_text},
                        )
                        await client.send_notification(
                            STREAM_THINKING, {"thinking": thinking_text}
                        )
```

### Step 4: Run tests to verify they pass

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_thinking_delta tests/test_orchestrator.py::test_orchestrator_emits_thinking_final -v && cd ../..
```
Expected: 2 PASS.

### Step 5: Run full test suite

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```
Expected: All 25 tests pass. The existing `test_orchestrator_emits_stream_thinking_for_thinking_blocks` (Test 5) must still pass — the `STREAM_THINKING` notification is preserved after the new hook emissions.

### Step 6: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat(events): emit thinking:delta and thinking:final alongside STREAM_THINKING"
```

---

## Task 7: Emit `provider:throttle`

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` — thread `provider_name` through `_apply_rate_limit_delay()`, add emission
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py` — 1 test

### Step 1: Write the failing test

Append to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
# ---------------------------------------------------------------------------
# Test 26: provider:throttle emitted during rate limit delay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_provider_throttle() -> None:
    """provider:throttle emitted when rate limit delay is applied."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    # Two iterations: first returns tool call, second returns final text.
    # Rate limit delay triggers on second iteration (after first provider call).
    tool_call_response = chat_response(
        text="",
        tool_calls=[{"id": "tc1", "tool": "read_file", "arguments": {"path": "x"}}],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok("file content"),
        }
    )

    # Use a very large min_delay so throttle definitely triggers
    config = {
        "provider_name": "anthropic",
        "min_delay_between_calls_ms": 999999,
    }

    await orch.execute("Read file", config, client)

    throttle_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "provider:throttle"
    ]

    assert len(throttle_events) == 1, (
        f"Expected 1 provider:throttle, got {len(throttle_events)}"
    )

    data = throttle_events[0]["data"]
    assert data["provider"] == "anthropic"
    assert data["reason"] == "rate_limit"
    assert "delay_ms" in data
    assert isinstance(data["delay_ms"], (int, float))
    assert data["delay_ms"] > 0
```

### Step 2: Run test to verify it fails

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_provider_throttle -v --timeout=10 && cd ../..
```
Expected: FAIL — no `provider:throttle` event (or timeout if the huge delay kicks in — but `asyncio.sleep` should be fast in mock).

**Note:** This test will actually sleep for ~1000 seconds because of the 999999ms delay. We need to also patch `asyncio.sleep` in the test OR use a smaller delay. Let's update the test to patch asyncio.sleep:

Update the test above — replace the function body with this version that patches sleep:

```python
@pytest.mark.asyncio
async def test_orchestrator_emits_provider_throttle() -> None:
    """provider:throttle emitted when rate limit delay is applied."""
    import unittest.mock

    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator  # type: ignore[import]

    orch = StreamingOrchestrator()

    # Two iterations: first returns tool call, second returns final text.
    tool_call_response = chat_response(
        text="",
        tool_calls=[{"id": "tc1", "tool": "read_file", "arguments": {"path": "x"}}],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok("file content"),
        }
    )

    # Use a very large min_delay so throttle definitely triggers
    config = {
        "provider_name": "anthropic",
        "min_delay_between_calls_ms": 999999,
    }

    # Patch asyncio.sleep to avoid actually waiting
    with unittest.mock.patch(
        "amplifier_foundation.orchestrators.streaming.asyncio.sleep",
        new_callable=unittest.mock.AsyncMock,
    ):
        await orch.execute("Read file", config, client)

    throttle_events = [
        params
        for method, params in client.requests
        if method == "request.hook_emit"
        and isinstance(params, dict)
        and params.get("event") == "provider:throttle"
    ]

    assert len(throttle_events) == 1, (
        f"Expected 1 provider:throttle, got {len(throttle_events)}"
    )

    data = throttle_events[0]["data"]
    assert data["provider"] == "anthropic"
    assert data["reason"] == "rate_limit"
    assert "delay_ms" in data
    assert isinstance(data["delay_ms"], (int, float))
    assert data["delay_ms"] > 0
```

### Step 3: Thread `provider_name` through `_apply_rate_limit_delay()`

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, find the method signature at line 581:

```python
    async def _apply_rate_limit_delay(
        self, client: Any, min_delay_ms: int, iteration: int
    ) -> None:
```

Replace with:

```python
    async def _apply_rate_limit_delay(
        self, client: Any, min_delay_ms: int, iteration: int, provider_name: str = "unknown"
    ) -> None:
```

### Step 4: Add provider:throttle emission

In the same `_apply_rate_limit_delay()` method, find the existing `ORCHESTRATOR_RATE_LIMIT_DELAY` emission:

```python
        if remaining_ms > 0:
            await self._hook_emit(
                client,
                ORCHESTRATOR_RATE_LIMIT_DELAY,
                {
                    "delay_ms": remaining_ms,
                    "configured_ms": min_delay_ms,
                    "elapsed_ms": elapsed_ms,
                    "iteration": iteration,
                },
            )
            await asyncio.sleep(remaining_ms / 1000)
```

Replace with:

```python
        if remaining_ms > 0:
            await self._hook_emit(
                client,
                ORCHESTRATOR_RATE_LIMIT_DELAY,
                {
                    "delay_ms": remaining_ms,
                    "configured_ms": min_delay_ms,
                    "elapsed_ms": elapsed_ms,
                    "iteration": iteration,
                },
            )
            await self._hook_emit(
                client,
                PROVIDER_THROTTLE,
                {
                    "provider": provider_name,
                    "delay_ms": remaining_ms,
                    "reason": "rate_limit",
                },
            )
            await asyncio.sleep(remaining_ms / 1000)
```

### Step 5: Update the call site to pass `provider_name`

Find the call to `_apply_rate_limit_delay` in `execute()` (around line 194):

```python
            await self._apply_rate_limit_delay(client, min_delay_ms, iteration)
```

Replace with:

```python
            await self._apply_rate_limit_delay(client, min_delay_ms, iteration, provider_name)
```

### Step 6: Run test to verify it passes

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py::test_orchestrator_emits_provider_throttle -v && cd ../..
```
Expected: PASS.

### Step 7: Run full test suite

```bash
cd services/amplifier-foundation && python -m pytest tests/test_orchestrator.py -v && cd ../..
```
Expected: All 26 tests pass. The `_apply_rate_limit_delay` signature change is backward-compatible (new param has a default).

### Step 8: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat(events): emit provider:throttle in rate limit delay with provider_name"
```

---

## Post-Implementation Verification

After all 7 tasks are complete, run the full test suite:

```bash
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..
```

Expected: All tests pass with zero failures.

### Summary of Changes

**`streaming.py` import block** — expanded from 3 to 12 constants:
- Added: `CONTENT_BLOCK_DELTA`, `EXECUTION_END`, `EXECUTION_START`, `LLM_REQUEST`, `LLM_RESPONSE`, `PROVIDER_RESOLVE`, `PROVIDER_THROTTLE`, `THINKING_DELTA`, `THINKING_FINAL`

**`streaming.py` emission sites** — 9 new hook events:

| Event | Location | Payload |
|---|---|---|
| `execution:start` | Top of `execute()`, before config overrides | `{"prompt": str}` |
| `execution:end` | `finally` block wrapping `execute()` body | `{"response": str, "status": "completed"\|"cancelled"\|"error"}` |
| `provider:resolve` | After `provider_name` read from config | `{"provider": str}` |
| `llm:request` | Before `request.provider_complete` call | `{"provider": str, "message_count": int, "iteration": int}` |
| `llm:response` | After `ChatResponse.model_validate`, before `provider:response` | `{"provider": str, "usage": dict\|None, "status": "ok"}` |
| `content_block:delta` | Inside block loop, between `start` and `end` | `{"index": int, "block_type": str, "delta": str}` |
| `thinking:delta` | Before `STREAM_THINKING` notification | `{"index": int, "delta": str}` |
| `thinking:final` | After `thinking:delta`, before `STREAM_THINKING` | `{"index": int, "text": str}` |
| `provider:throttle` | In `_apply_rate_limit_delay()`, after `ORCHESTRATOR_RATE_LIMIT_DELAY` | `{"provider": str, "delay_ms": float, "reason": "rate_limit"}` |

**`streaming.py` structural changes:**
- `execute()` body wrapped in `try/except/finally` for `execution:end` on all paths
- `_apply_rate_limit_delay()` gained `provider_name` parameter

**`test_orchestrator.py`** — 11 new tests (Tests 16–26), total: 26 tests.

### What's Now Covered

After Phase 1 + Phase 2, the orchestrator emits all turn-level events:
- **Execution lifecycle:** `execution:start`, `execution:end`
- **Provider:** `provider:request`, `provider:response`, `provider:resolve`, `provider:throttle`, `provider:retry`, `provider:error`
- **LLM:** `llm:request`, `llm:response`
- **Content:** `content_block:start`, `content_block:delta`, `content_block:end`
- **Thinking:** `thinking:delta`, `thinking:final`
- **Prompt:** `prompt:submit`, `prompt:complete`
- **Tool:** `tool:pre`, `tool:post`, `tool:error`
- **Orchestrator:** `orchestrator:complete`

### What's NOT in This Phase (Deferred)

- `provider:tool_sequence_repaired` — belongs at the provider service layer, not the orchestrator
- Session events (`session:start/end/fork/resume`) — Host-emitted, covered in Phase 1 / Phase 3
- Cancellation, context, planning, artifact, policy, delegation events — Phases 3–5