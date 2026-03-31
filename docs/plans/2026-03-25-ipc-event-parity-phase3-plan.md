# IPC Event Parity — Phase 3 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Emit the 4 session lifecycle and cancellation events (`session:fork`, `session:resume`, `cancel:requested`, `cancel:completed`) from the Host, completing the session-level event surface.

**Architecture:** All 4 events are emitted by the Host using the `_emit_hook_event()` helper (added in Phase 1). Event constants already exist in `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py`. The import line in `host.py` (line 63) is expanded from `SESSION_END, SESSION_START` to include `CANCEL_COMPLETED, CANCEL_REQUESTED, SESSION_FORK, SESSION_RESUME`. No new files are created — all changes go into existing `host.py` and `test_session_events.py`.

**Tech Stack:** Python 3.11+, pytest with `asyncio_mode="auto"` (but existing tests use `@pytest.mark.asyncio` — match that convention), `unittest.mock`.

**Design doc:** `docs/plans/2026-03-25-ipc-event-parity-design.md`
**Phase 1 plan:** `docs/plans/2026-03-25-ipc-event-parity-phase1-plan.md`

**Prerequisite:** Phase 1 must be complete. The `_emit_hook_event()` method, `SESSION_START`/`SESSION_END` emissions, and the test infrastructure in `test_session_events.py` are already in place.

---

## Task 1: Expand event constant imports

**Files:**
- Modify: `src/amplifier_ipc/host/host.py:63` — expand import line

**Step 1: Update the events import**

In `src/amplifier_ipc/host/host.py`, find this import on line 63:

```python
from amplifier_ipc_protocol.events import SESSION_END, SESSION_START
```

Replace with:

```python
from amplifier_ipc_protocol.events import (
    CANCEL_COMPLETED,
    CANCEL_REQUESTED,
    SESSION_END,
    SESSION_FORK,
    SESSION_RESUME,
    SESSION_START,
)
```

**Step 2: Verify the import works**

```bash
python -c "from amplifier_ipc.host.host import Host; print('import ok')"
```
Expected: `import ok`

**Step 3: Commit**

```bash
git add src/amplifier_ipc/host/host.py
git commit -m "feat: import SESSION_FORK, SESSION_RESUME, CANCEL_REQUESTED, CANCEL_COMPLETED in Host"
```

---

## Task 2: Emit session:fork in _handle_spawn()

**Files:**
- Modify: `src/amplifier_ipc/host/host.py` — add `session:fork` emission in `_handle_spawn` closure
- Modify: `tests/host/test_session_events.py` — add test

**Step 1: Write the failing test**

Append to `tests/host/test_session_events.py`. Add `SESSION_FORK` to the import from `amplifier_ipc_protocol.events` at the top of the file (line 16), then append the test:

First, update line 16 from:
```python
from amplifier_ipc_protocol.events import SESSION_END, SESSION_START
```
to:
```python
from amplifier_ipc_protocol.events import (
    CANCEL_COMPLETED,
    CANCEL_REQUESTED,
    SESSION_END,
    SESSION_FORK,
    SESSION_RESUME,
    SESSION_START,
)
```

Then append this test at the end of the file:

```python


# ---------------------------------------------------------------------------
# Phase 3 — session:fork
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_spawn_emits_session_fork(tmp_path: Path) -> None:
    """_handle_spawn emits SESSION_FORK with child_session_id, parent, and agent."""
    host = _make_host_with_registry(session_dir=tmp_path)
    host._session_id = "parent-abc"

    # Build the spawn handler with a known parent session_id
    handler = host._build_spawn_handler("parent-abc", current_depth=0)

    # Track _emit_hook_event calls
    emitted: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        emitted.append((event_name, data))

    host._emit_hook_event = capture_emit  # type: ignore[assignment]

    # Mock spawn_child_session to avoid real subprocess spawning
    with patch(
        "amplifier_ipc.host.host.spawn_child_session",
        new_callable=AsyncMock,
        return_value="child result",
    ):
        result = await handler({"agent": "code-review", "instruction": "review this"})

    assert result == "child result"

    # Verify session:fork was emitted
    fork_events = [(e, d) for e, d in emitted if e == SESSION_FORK]
    assert len(fork_events) == 1, f"Expected 1 session:fork, got {len(fork_events)}"

    data = fork_events[0][1]
    assert data["parent_id"] == "parent-abc"
    assert "session_id" in data  # child_session_id is generated
    assert data["agent"] == "code-review"
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/host/test_session_events.py::test_handle_spawn_emits_session_fork -v
```
Expected: FAIL — `emitted` list has no `SESSION_FORK` entry (0 events captured, or only non-fork events)

**Step 3: Add session:fork emission to _handle_spawn**

In `src/amplifier_ipc/host/host.py`, inside the `_handle_spawn` closure (within `_build_spawn_handler`), find this line (around line 565):

```python
            child_session_id = generate_child_session_id(session_id, agent_name)
```

Add the following **immediately after** that line (before the `_forward_child_event` def):

```python

            await self._emit_hook_event(
                SESSION_FORK,
                {
                    "session_id": child_session_id,
                    "parent_id": session_id,
                    "agent": agent_name,
                },
            )
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/host/test_session_events.py::test_handle_spawn_emits_session_fork -v
```
Expected: PASS

**Step 5: Run existing tests to check for regressions**

```bash
python -m pytest tests/host/test_session_events.py -v
```
Expected: All tests pass (9 total — 8 existing + 1 new)

**Step 6: Commit**

```bash
git add src/amplifier_ipc/host/host.py tests/host/test_session_events.py
git commit -m "feat: emit session:fork hook event when spawning child sessions"
```

---

## Task 3: Emit session:resume for top-level resume (Pattern A)

**Files:**
- Modify: `src/amplifier_ipc/host/host.py:434-442` — make session:start/session:resume conditional
- Modify: `tests/host/test_session_events.py` — add test

The current code (lines 434-442) unconditionally emits `SESSION_START`. When `self._resume_session_id` is set, it should emit `SESSION_RESUME` instead.

**Step 1: Write the failing test**

Append to `tests/host/test_session_events.py`:

```python


# ---------------------------------------------------------------------------
# Phase 3 — session:resume (top-level, Pattern A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_emits_session_resume_instead_of_start(tmp_path: Path) -> None:
    """When resuming, Host.run() emits SESSION_RESUME instead of SESSION_START."""
    host = _make_host_with_registry(session_dir=tmp_path)

    # Simulate a resume by setting _resume_session_id
    host._resume_session_id = "prev-session-999"

    # Capture events, but also need to mock _restore_from_session
    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        captured.append((event_name, data))

    async def noop_orchestrator_loop(*args: Any, **kwargs: Any) -> Any:
        return
        yield  # type: ignore[misc]  # noqa: unreachable

    async def fake_restore() -> str:
        return "prev-session-999"

    with (
        patch.object(host, "_emit_hook_event", capture_emit),
        patch.object(host, "_orchestrator_loop", noop_orchestrator_loop),
        patch.object(host, "_restore_from_session", fake_restore),
        patch(
            "amplifier_ipc.host.host.assemble_system_prompt",
            AsyncMock(return_value="system prompt"),
        ),
    ):
        async for _ in host.run("continue"):
            pass

    # SESSION_RESUME should be present, SESSION_START should NOT
    resume_events = [(e, d) for e, d in captured if e == SESSION_RESUME]
    start_events = [(e, d) for e, d in captured if e == SESSION_START]

    assert len(resume_events) == 1, (
        f"Expected 1 session:resume, got {len(resume_events)}"
    )
    assert len(start_events) == 0, (
        f"Expected 0 session:start when resuming, got {len(start_events)}"
    )

    data = resume_events[0][1]
    assert data["session_id"] is not None
    assert data["parent_id"] == host._parent_session_id
    assert "raw" in data
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/host/test_session_events.py::test_run_emits_session_resume_instead_of_start -v
```
Expected: FAIL — `start_events` has 1 entry (session:start still emits unconditionally), `resume_events` has 0

**Step 3: Make session:start / session:resume conditional**

In `src/amplifier_ipc/host/host.py`, find this block (lines 434-442):

```python
            # 5a. Emit session:start hook event
            await self._emit_hook_event(
                SESSION_START,
                {
                    "session_id": self._session_id,
                    "parent_id": self._parent_session_id,
                    "raw": self._config.model_dump(),
                },
            )
```

Replace with:

```python
            # 5a. Emit session:start or session:resume hook event
            _lifecycle_event = (
                SESSION_RESUME
                if self._resume_session_id is not None
                else SESSION_START
            )
            await self._emit_hook_event(
                _lifecycle_event,
                {
                    "session_id": self._session_id,
                    "parent_id": self._parent_session_id,
                    "raw": self._config.model_dump(),
                },
            )
```

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/host/test_session_events.py::test_run_emits_session_resume_instead_of_start -v
```
Expected: PASS

**Step 5: Verify the original session:start tests still pass**

The existing `test_run_emits_session_start` test creates a host without `_resume_session_id`, so the conditional should still pick `SESSION_START`.

```bash
python -m pytest tests/host/test_session_events.py -v
```
Expected: All tests pass (10 total)

**Step 6: Commit**

```bash
git add src/amplifier_ipc/host/host.py tests/host/test_session_events.py
git commit -m "feat: emit session:resume instead of session:start when resuming (top-level)"
```

---

## Task 4: Emit session:resume for child resume (Pattern B)

**Files:**
- Modify: `src/amplifier_ipc/host/host.py` — add `session:resume` emission in `_handle_resume` closure
- Modify: `tests/host/test_session_events.py` — add test

The `_handle_resume` closure (inside `_build_resume_handler`, lines 634-687) handles `request.session_resume` from the orchestrator. It resumes a child session — this should emit `SESSION_RESUME`, not `SESSION_FORK`.

**Step 1: Write the failing test**

Append to `tests/host/test_session_events.py`:

```python


# ---------------------------------------------------------------------------
# Phase 3 — session:resume (child resume, Pattern B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_resume_emits_session_resume(tmp_path: Path) -> None:
    """_handle_resume emits SESSION_RESUME with child_session_id and parent."""
    host = _make_host_with_registry(session_dir=tmp_path)
    host._session_id = "parent-xyz"

    # Pre-create a child session directory with a transcript so
    # load_transcript() doesn't fail
    child_dir = tmp_path / "child-session-42"
    child_dir.mkdir(parents=True)
    (child_dir / "transcript.jsonl").write_text("")
    (child_dir / "state.json").write_text("{}")

    handler = host._build_resume_handler("parent-xyz")

    emitted: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        emitted.append((event_name, data))

    host._emit_hook_event = capture_emit  # type: ignore[assignment]

    with patch(
        "amplifier_ipc.host.host._run_child_session",
        new_callable=AsyncMock,
        return_value="resumed child result",
    ):
        result = await handler({
            "session_id": "child-session-42",
            "instruction": "keep going",
        })

    assert result == "resumed child result"

    resume_events = [(e, d) for e, d in emitted if e == SESSION_RESUME]
    assert len(resume_events) == 1, (
        f"Expected 1 session:resume, got {len(resume_events)}"
    )

    data = resume_events[0][1]
    assert data["session_id"] == "child-session-42"
    assert data["parent_id"] == "parent-xyz"
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/host/test_session_events.py::test_handle_resume_emits_session_resume -v
```
Expected: FAIL — `emitted` list has no `SESSION_RESUME` entry

**Step 3: Add session:resume emission to _handle_resume**

In `src/amplifier_ipc/host/host.py`, inside the `_handle_resume` closure (within `_build_resume_handler`), find this line (around line 639):

```python
            child_session_id: str = p.get("session_id", "")
```

Add the following **after** the child_session_id assignment and **before** the "Create SessionPersistence" comment (so after line 640, `instruction: str = p.get("instruction", "")`):

```python

            await self._emit_hook_event(
                SESSION_RESUME,
                {
                    "session_id": child_session_id,
                    "parent_id": session_id,
                },
            )
```

Note: `session_id` here is the parent session ID captured in the closure from `_build_resume_handler(self, session_id: str)`.

**Step 4: Run test to verify it passes**

```bash
python -m pytest tests/host/test_session_events.py::test_handle_resume_emits_session_resume -v
```
Expected: PASS

**Step 5: Run all session event tests**

```bash
python -m pytest tests/host/test_session_events.py -v
```
Expected: All tests pass (11 total)

**Step 6: Commit**

```bash
git add src/amplifier_ipc/host/host.py tests/host/test_session_events.py
git commit -m "feat: emit session:resume hook event when resuming child sessions"
```

---

## Task 5: Emit cancel:requested and cancel:completed

**Files:**
- Modify: `src/amplifier_ipc/host/host.py:505-507` — add cancellation event emissions in `except asyncio.CancelledError`
- Modify: `tests/host/test_session_events.py` — add test

Both `cancel:requested` and `cancel:completed` are emitted from the Host's `except asyncio.CancelledError` block. The ordering is: `cancel:requested` → `cancel:completed` → (then the existing `session:end(status="cancelled")` in the `finally` block).

**Step 1: Write the failing test**

Append to `tests/host/test_session_events.py`:

```python


# ---------------------------------------------------------------------------
# Phase 3 — cancel:requested + cancel:completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_emits_cancel_events_on_cancellation(tmp_path: Path) -> None:
    """CancelledError triggers cancel:requested, cancel:completed, then session:end."""
    host = _make_host_with_registry(session_dir=tmp_path)

    captured: list[tuple[str, dict[str, Any]]] = []

    async def capture_emit(event_name: str, data: dict[str, Any]) -> None:
        captured.append((event_name, data))

    async def cancelled_loop(*args: Any, **kwargs: Any) -> Any:
        raise asyncio.CancelledError()
        yield  # type: ignore[misc]  # noqa: unreachable

    with (
        patch.object(host, "_emit_hook_event", capture_emit),
        patch.object(host, "_orchestrator_loop", cancelled_loop),
        patch(
            "amplifier_ipc.host.host.assemble_system_prompt",
            AsyncMock(return_value="system prompt"),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        async for _ in host.run("hello"):
            pass

    # Extract cancel events
    cancel_req = [(e, d) for e, d in captured if e == CANCEL_REQUESTED]
    cancel_done = [(e, d) for e, d in captured if e == CANCEL_COMPLETED]
    end_events = [(e, d) for e, d in captured if e == SESSION_END]

    assert len(cancel_req) == 1, (
        f"Expected 1 cancel:requested, got {len(cancel_req)}"
    )
    assert len(cancel_done) == 1, (
        f"Expected 1 cancel:completed, got {len(cancel_done)}"
    )

    # Verify payloads
    assert cancel_req[0][1]["session_id"] == host._session_id
    assert cancel_req[0][1]["was_immediate"] is False

    assert cancel_done[0][1]["session_id"] == host._session_id
    assert cancel_done[0][1]["was_immediate"] is False

    # Verify ordering: cancel:requested → cancel:completed → session:end
    event_names = [e for e, _ in captured]
    req_idx = event_names.index(CANCEL_REQUESTED)
    done_idx = event_names.index(CANCEL_COMPLETED)
    end_idx = event_names.index(SESSION_END)

    assert req_idx < done_idx < end_idx, (
        f"Expected cancel:requested ({req_idx}) < cancel:completed ({done_idx}) "
        f"< session:end ({end_idx}), events: {event_names}"
    )


@pytest.mark.asyncio
async def test_normal_exit_does_not_emit_cancel_events(tmp_path: Path) -> None:
    """Normal (non-cancelled) exit does NOT emit cancel:requested or cancel:completed."""
    host = _make_host_with_registry(session_dir=tmp_path)

    calls = await _drain(host)

    cancel_events = [
        (e, d) for e, d in calls
        if e in (CANCEL_REQUESTED, CANCEL_COMPLETED)
    ]
    assert len(cancel_events) == 0, (
        f"Expected 0 cancel events on normal exit, got {cancel_events}"
    )
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/host/test_session_events.py::test_run_emits_cancel_events_on_cancellation -v
python -m pytest tests/host/test_session_events.py::test_normal_exit_does_not_emit_cancel_events -v
```
Expected: First test FAILS — no `cancel:requested` or `cancel:completed` events captured. Second test should PASS already (no cancel events emitted on normal path).

**Step 3: Add cancel:requested and cancel:completed emissions**

In `src/amplifier_ipc/host/host.py`, find the `except asyncio.CancelledError` block (lines 505-507):

```python
        except asyncio.CancelledError:
            _session_status = "cancelled"
            raise
```

Replace with:

```python
        except asyncio.CancelledError:
            _session_status = "cancelled"
            await self._emit_hook_event(
                CANCEL_REQUESTED,
                {"session_id": self._session_id, "was_immediate": False},
            )
            await self._emit_hook_event(
                CANCEL_COMPLETED,
                {"session_id": self._session_id, "was_immediate": False},
            )
            raise
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/host/test_session_events.py::test_run_emits_cancel_events_on_cancellation tests/host/test_session_events.py::test_normal_exit_does_not_emit_cancel_events -v
```
Expected: Both PASS

**Step 5: Verify the existing cancellation test still passes**

The existing `test_run_emits_session_end_cancelled` (lines 284-314) should still pass — it checks for `session:end` with `status="cancelled"`, which still fires in the `finally` block after the new cancel events.

```bash
python -m pytest tests/host/test_session_events.py -v
```
Expected: All tests pass (13 total)

**Step 6: Commit**

```bash
git add src/amplifier_ipc/host/host.py tests/host/test_session_events.py
git commit -m "feat: emit cancel:requested and cancel:completed on session cancellation"
```

---

## Post-Implementation Verification

After all 5 tasks are complete, run the full test suites:

```bash
# Host test suite
python -m pytest tests/host/ -v

# Root test suite
python -m pytest tests/ -v
```

All tests should pass with zero failures.

### Event Emission Summary

After Phase 3, the Host emits these events at these sites:

| Event | Location | Trigger |
|---|---|---|
| `session:start` | `run()`, line ~434 | Normal (non-resume) session start |
| `session:resume` | `run()`, line ~434 | Top-level resume (`_resume_session_id` is set) |
| `session:resume` | `_handle_resume()` | Child session resume via orchestrator |
| `session:fork` | `_handle_spawn()` | Child session spawn, after `generate_child_session_id()` |
| `cancel:requested` | `run()`, `except CancelledError` | `asyncio.CancelledError` caught |
| `cancel:completed` | `run()`, `except CancelledError` | Immediately after `cancel:requested` |
| `session:end` | `run()`, `finally` | Always — with status `completed`, `cancelled`, or `failed` |

### Cancellation Event Ordering

On cancellation, events fire in this order:
1. `cancel:requested` — `{session_id, was_immediate: false}`
2. `cancel:completed` — `{session_id, was_immediate: false}`
3. `session:end` — `{session_id, status: "cancelled"}`

The `was_immediate` field starts as `false` — it can be refined later when `CancellationState` is threaded to the Host.

### What Remains

- **`user:notification`** is **deferred** — it's an app-layer/tool-layer event, not a lifecycle event. The constant exists in `amplifier_ipc_protocol.events`; any service can emit it through `request.hook_emit` when needed.
- **Phase 4** covers subsystem events (`context:*`, `plan:*`, `artifact:*`).
- **Phase 5** covers policy and delegation events.