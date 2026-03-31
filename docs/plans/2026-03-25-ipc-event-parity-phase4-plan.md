# IPC Event Parity — Phase 4 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Add the 6 subsystem-level event emissions (`artifact:write`, `artifact:read`, `context:include`, `context:pre_compact`, `context:post_compact`, `context:compaction`) so that RedactionHook, ShellHook, and LoggingHook receive the artifact and compaction events they subscribe to.

**Architecture:** Three subsystems gain event emission: (1) Filesystem tools (`WriteTool`, `EditTool`, `ReadTool`) emit `artifact:write`/`artifact:read` via the IPC client already injected by the protocol server for tools with a `client` attribute; (2) The Host emits `context:include` during working-directory content loading and @mention resolution; (3) `SimpleContextManager` emits compaction events via a newly-injected IPC client, following the same injection pattern the server already uses for tools.

**Tech Stack:** Python 3.11+, Pydantic, pytest with `@pytest.mark.asyncio`, uv for package management.

**Design doc:** `docs/plans/2026-03-25-ipc-event-parity-design.md`
**Phase 1 plan:** `docs/plans/2026-03-25-ipc-event-parity-phase1-plan.md`
**Phase 2 plan:** `docs/plans/2026-03-25-ipc-event-parity-phase2-plan.md`

---

## Context for the Implementer

### Files You'll Touch

| Action | Path |
|---|---|
| **Modify** | `services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/write.py` (101 lines) |
| **Modify** | `services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/edit.py` (186 lines) |
| **Modify** | `services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/read.py` (183 lines) |
| **Modify** | `src/amplifier_ipc/host/mentions.py` (337 lines) |
| **Modify** | `src/amplifier_ipc/host/host.py` (1283 lines) |
| **Modify** | `src/amplifier_ipc/protocol/server.py` (875 lines) |
| **Modify** | `services/amplifier-foundation/src/amplifier_foundation/context_managers/simple.py` (1018 lines) |
| **Create** | `services/amplifier-foundation/tests/test_artifact_events.py` |
| **Modify** | `tests/host/test_mentions.py` (451 lines) |
| **Modify** | `services/amplifier-foundation/tests/test_context_manager.py` (69 lines) |

### Existing Patterns You Must Follow

**Client injection into tools** — The protocol server (`src/amplifier_ipc/protocol/server.py` line 575–579) automatically injects an IPC client into any tool that has a `client` attribute:
```python
if (
    hasattr(tool_instance, "client")
    and self._current_orchestrator_client is not None
):
    tool_instance.client = self._current_orchestrator_client
```
Add `client: Any = None` to a tool class and the server does the rest. The `DelegateTool` and `TaskTool` already use this pattern.

**Hook emission from tools** — Tools with an injected client emit hook events via:
```python
await self.client.request("request.hook_emit", {"event": EVENT_CONSTANT, "data": {...}})
```
This is handled locally by `_OrchestratorLocalClient.request()` which routes to `self._server._handle_hook_emit()` — no IPC round-trip.

**Event constants** — All 6 constants are already defined in `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py`:
- `ARTIFACT_WRITE = "artifact:write"` (line 66)
- `ARTIFACT_READ = "artifact:read"` (line 67)
- `CONTEXT_INCLUDE = "context:include"` (line 55)
- `CONTEXT_PRE_COMPACT = "context:pre_compact"` (line 52)
- `CONTEXT_POST_COMPACT = "context:post_compact"` (line 53)
- `CONTEXT_COMPACTION = "context:compaction"` (line 54)

**Filesystem tool proxy pattern** — The actual tool implementations live in `tools/filesystem/write.py` etc. without `@tool` decorators. They're exposed to `scan_package()` via proxy subclasses in `tools/filesystem_tools.py` that inherit from the base classes and add `@tool`. Adding `client: Any = None` to the base class is sufficient — the proxy subclass inherits it.

**Test pattern (foundation service tests)** — Tests use `@pytest.mark.asyncio`, local imports inside test functions, and direct instantiation:
```python
@pytest.mark.asyncio
async def test_something() -> None:
    from amplifier_foundation.tools.filesystem.write import WriteTool
    tool = WriteTool(config={"working_dir": str(tmp_path)})
    ...
```

**Test pattern (host tests)** — Tests in `tests/host/` use `@pytest.mark.asyncio` with `async def`, and import directly from `amplifier_ipc.host.*`.

### Running Tests

```bash
# Foundation service tests (artifact events, context manager)
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..

# Host tests (mention events)
python -m pytest tests/host/ -v
```

---

## Task 1: Add `client` Attribute and `artifact:write` Emission to WriteTool

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/write.py`
- Create: `services/amplifier-foundation/tests/test_artifact_events.py`

### Step 1: Write the failing test

Create `services/amplifier-foundation/tests/test_artifact_events.py`:

```python
"""Tests for artifact:write and artifact:read hook event emissions from filesystem tools."""

from __future__ import annotations

from typing import Any

import pytest


# ---------------------------------------------------------------------------
# MockClient — records hook_emit calls
# ---------------------------------------------------------------------------


class MockClient:
    """Minimal mock IPC client that records request calls."""

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
# Test 1: WriteTool emits artifact:write on successful write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_tool_emits_artifact_write(tmp_path: Any) -> None:
    """WriteTool emits artifact:write with path and bytes after successful write."""
    from amplifier_foundation.tools.filesystem.write import WriteTool  # type: ignore[import]

    tool = WriteTool(config={"working_dir": str(tmp_path)})
    mock_client = MockClient()
    tool.client = mock_client

    result = await tool.execute({"file_path": "hello.txt", "content": "Hello, world!"})

    assert result.success is True

    events = _hook_emits(mock_client, "artifact:write")
    assert len(events) == 1, f"Expected 1 artifact:write, got {len(events)}"
    assert events[0]["path"] == str(tmp_path / "hello.txt")
    assert events[0]["bytes"] == len("Hello, world!".encode("utf-8"))


# ---------------------------------------------------------------------------
# Test 2: WriteTool does NOT emit artifact:write on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_tool_no_event_on_failure() -> None:
    """WriteTool does not emit artifact:write when the write fails."""
    from amplifier_foundation.tools.filesystem.write import WriteTool  # type: ignore[import]

    tool = WriteTool(config={"working_dir": "/tmp"})
    mock_client = MockClient()
    tool.client = mock_client

    # Missing file_path → validation failure
    result = await tool.execute({"file_path": "", "content": "test"})

    assert result.success is False
    events = _hook_emits(mock_client, "artifact:write")
    assert len(events) == 0, "artifact:write should not fire on failed write"


# ---------------------------------------------------------------------------
# Test 3: WriteTool works without client (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_tool_works_without_client(tmp_path: Any) -> None:
    """WriteTool still works correctly when client is None (no server injection)."""
    from amplifier_foundation.tools.filesystem.write import WriteTool  # type: ignore[import]

    tool = WriteTool(config={"working_dir": str(tmp_path)})
    assert tool.client is None  # No client injected

    result = await tool.execute({"file_path": "test.txt", "content": "content"})

    assert result.success is True
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-foundation && python -m pytest tests/test_artifact_events.py -v && cd ../..
```
Expected: FAIL — `AttributeError: 'WriteTool' object has no attribute 'client'`

### Step 3: Add `client` attribute and artifact:write emission to WriteTool

In `services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/write.py`:

Add the import at the top (after existing imports):
```python
from amplifier_ipc_protocol.events import ARTIFACT_WRITE
```

Add the `client` attribute to the `WriteTool` class (after line 13, `description = ...`):
```python
    # Injected by the protocol server's _handle_tool_execute when the
    # orchestrator is active (allows IPC calls back to the host).
    client: Any = None
```

In the `execute()` method, after the successful write block (after line 82 `bytes_written = len(content.encode("utf-8"))`), add artifact:write emission before the return statement. Find:

```python
            bytes_written = len(content.encode("utf-8"))

            return ToolResult(
                success=True, output={"file_path": str(path), "bytes": bytes_written}
            )
```

Replace with:

```python
            bytes_written = len(content.encode("utf-8"))

            # Emit artifact:write hook event (fire-and-forget)
            if self.client is not None:
                try:
                    await self.client.request(
                        "request.hook_emit",
                        {
                            "event": ARTIFACT_WRITE,
                            "data": {"path": str(path), "bytes": bytes_written},
                        },
                    )
                except Exception:
                    pass  # Hook emission must never affect tool result

            return ToolResult(
                success=True, output={"file_path": str(path), "bytes": bytes_written}
            )
```

### Step 4: Run tests to verify they pass

```bash
cd services/amplifier-foundation && python -m pytest tests/test_artifact_events.py::test_write_tool_emits_artifact_write tests/test_artifact_events.py::test_write_tool_no_event_on_failure tests/test_artifact_events.py::test_write_tool_works_without_client -v && cd ../..
```
Expected: 3 PASS

### Step 5: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/write.py services/amplifier-foundation/tests/test_artifact_events.py
git commit -m "feat(events): emit artifact:write from WriteTool on successful file write"
```

---

## Task 2: Add `client` Attribute and `artifact:write` Emission to EditTool

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/edit.py`
- Modify: `services/amplifier-foundation/tests/test_artifact_events.py`

### Step 1: Write the failing test

Append to `services/amplifier-foundation/tests/test_artifact_events.py`:

```python
# ---------------------------------------------------------------------------
# Test 4: EditTool emits artifact:write on successful edit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_tool_emits_artifact_write(tmp_path: Any) -> None:
    """EditTool emits artifact:write with path and bytes after successful edit."""
    from amplifier_foundation.tools.filesystem.edit import EditTool  # type: ignore[import]

    # Create a file to edit
    test_file = tmp_path / "greet.txt"
    test_file.write_text("Hello, world!", encoding="utf-8")

    tool = EditTool(config={"working_dir": str(tmp_path)})
    mock_client = MockClient()
    tool.client = mock_client

    result = await tool.execute({
        "file_path": str(test_file),
        "old_string": "world",
        "new_string": "Python",
    })

    assert result.success is True

    events = _hook_emits(mock_client, "artifact:write")
    assert len(events) == 1, f"Expected 1 artifact:write, got {len(events)}"
    assert events[0]["path"] == str(test_file)
    assert events[0]["bytes"] == len("Hello, Python!".encode("utf-8"))


# ---------------------------------------------------------------------------
# Test 5: EditTool does NOT emit artifact:write on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_tool_no_event_on_failure(tmp_path: Any) -> None:
    """EditTool does not emit artifact:write when the edit fails."""
    from amplifier_foundation.tools.filesystem.edit import EditTool  # type: ignore[import]

    tool = EditTool(config={"working_dir": str(tmp_path)})
    mock_client = MockClient()
    tool.client = mock_client

    # File doesn't exist → failure
    result = await tool.execute({
        "file_path": str(tmp_path / "nonexistent.txt"),
        "old_string": "a",
        "new_string": "b",
    })

    assert result.success is False
    events = _hook_emits(mock_client, "artifact:write")
    assert len(events) == 0, "artifact:write should not fire on failed edit"
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-foundation && python -m pytest tests/test_artifact_events.py::test_edit_tool_emits_artifact_write tests/test_artifact_events.py::test_edit_tool_no_event_on_failure -v && cd ../..
```
Expected: FAIL — `AttributeError: 'EditTool' object has no attribute 'client'`

### Step 3: Add `client` attribute and artifact:write emission to EditTool

In `services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/edit.py`:

Add the import at the top (after existing imports):
```python
from amplifier_ipc_protocol.events import ARTIFACT_WRITE
```

Add the `client` attribute to the `EditTool` class (after line 13, `description = ...`):
```python
    # Injected by the protocol server's _handle_tool_execute when the
    # orchestrator is active (allows IPC calls back to the host).
    client: Any = None
```

In the `execute()` method, after the successful edit block (after line 150 `bytes_written = len(new_content.encode("utf-8"))`), add artifact:write emission before the return statement. Find:

```python
            path.write_text(new_content, encoding="utf-8")
            bytes_written = len(new_content.encode("utf-8"))

            return ToolResult(
                success=True,
                output={
                    "file_path": str(path),
                    "replacements_made": replacements_made,
                    "bytes_written": bytes_written,
                },
            )
```

Replace with:

```python
            path.write_text(new_content, encoding="utf-8")
            bytes_written = len(new_content.encode("utf-8"))

            # Emit artifact:write hook event (fire-and-forget)
            if self.client is not None:
                try:
                    await self.client.request(
                        "request.hook_emit",
                        {
                            "event": ARTIFACT_WRITE,
                            "data": {"path": str(path), "bytes": bytes_written},
                        },
                    )
                except Exception:
                    pass  # Hook emission must never affect tool result

            return ToolResult(
                success=True,
                output={
                    "file_path": str(path),
                    "replacements_made": replacements_made,
                    "bytes_written": bytes_written,
                },
            )
```

### Step 4: Run tests to verify they pass

```bash
cd services/amplifier-foundation && python -m pytest tests/test_artifact_events.py::test_edit_tool_emits_artifact_write tests/test_artifact_events.py::test_edit_tool_no_event_on_failure -v && cd ../..
```
Expected: 2 PASS

### Step 5: Run all artifact tests

```bash
cd services/amplifier-foundation && python -m pytest tests/test_artifact_events.py -v && cd ../..
```
Expected: 5 PASS

### Step 6: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/edit.py services/amplifier-foundation/tests/test_artifact_events.py
git commit -m "feat(events): emit artifact:write from EditTool on successful file edit"
```

---

## Task 3: Add `client` Attribute and `artifact:read` Emission to ReadTool

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/read.py`
- Modify: `services/amplifier-foundation/tests/test_artifact_events.py`

### Step 1: Write the failing test

Append to `services/amplifier-foundation/tests/test_artifact_events.py`:

```python
# ---------------------------------------------------------------------------
# Test 6: ReadTool emits artifact:read on successful file read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_tool_emits_artifact_read(tmp_path: Any) -> None:
    """ReadTool emits artifact:read with path and line count after successful read."""
    from amplifier_foundation.tools.filesystem.read import ReadTool  # type: ignore[import]

    test_file = tmp_path / "data.txt"
    test_file.write_text("line one\nline two\nline three\n", encoding="utf-8")

    tool = ReadTool(config={"working_dir": str(tmp_path)})
    mock_client = MockClient()
    tool.client = mock_client

    result = await tool.execute({"file_path": str(test_file)})

    assert result.success is True

    events = _hook_emits(mock_client, "artifact:read")
    assert len(events) == 1, f"Expected 1 artifact:read, got {len(events)}"
    assert events[0]["path"] == str(test_file)
    assert events[0]["lines_read"] == 3


# ---------------------------------------------------------------------------
# Test 7: ReadTool emits artifact:read on directory listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_tool_emits_artifact_read_for_directory(tmp_path: Any) -> None:
    """ReadTool emits artifact:read for directory listings."""
    from amplifier_foundation.tools.filesystem.read import ReadTool  # type: ignore[import]

    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    tool = ReadTool(config={"working_dir": str(tmp_path)})
    mock_client = MockClient()
    tool.client = mock_client

    result = await tool.execute({"file_path": str(tmp_path)})

    assert result.success is True

    events = _hook_emits(mock_client, "artifact:read")
    assert len(events) == 1, f"Expected 1 artifact:read, got {len(events)}"
    assert events[0]["path"] == str(tmp_path)
    assert events[0]["is_directory"] is True


# ---------------------------------------------------------------------------
# Test 8: ReadTool does NOT emit artifact:read on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_tool_no_event_on_failure() -> None:
    """ReadTool does not emit artifact:read when the read fails."""
    from amplifier_foundation.tools.filesystem.read import ReadTool  # type: ignore[import]

    tool = ReadTool(config={"working_dir": "/tmp"})
    mock_client = MockClient()
    tool.client = mock_client

    result = await tool.execute({"file_path": "/nonexistent/path/to/file.txt"})

    assert result.success is False
    events = _hook_emits(mock_client, "artifact:read")
    assert len(events) == 0, "artifact:read should not fire on failed read"
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-foundation && python -m pytest tests/test_artifact_events.py::test_read_tool_emits_artifact_read tests/test_artifact_events.py::test_read_tool_emits_artifact_read_for_directory tests/test_artifact_events.py::test_read_tool_no_event_on_failure -v && cd ../..
```
Expected: FAIL — `AttributeError: 'ReadTool' object has no attribute 'client'`

### Step 3: Add `client` attribute and artifact:read emission to ReadTool

In `services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/read.py`:

Add the import at the top (after existing imports):
```python
from amplifier_ipc_protocol.events import ARTIFACT_READ
```

Add the `client` attribute to the `ReadTool` class (after line 10, `description = ...`):
```python
    # Injected by the protocol server's _handle_tool_execute when the
    # orchestrator is active (allows IPC calls back to the host).
    client: Any = None
```

In the `execute()` method, add artifact:read emission for **directory listings**. Find the successful directory return (around line 122):

```python
                return ToolResult(
                    success=True,
                    output={
                        "file_path": str(path),
                        "content": output_text,
                        "is_directory": True,
                        "entry_count": len(entries),
                    },
                )
```

Replace with:

```python
                # Emit artifact:read hook event (fire-and-forget)
                if self.client is not None:
                    try:
                        await self.client.request(
                            "request.hook_emit",
                            {
                                "event": ARTIFACT_READ,
                                "data": {
                                    "path": str(path),
                                    "is_directory": True,
                                    "entry_count": len(entries),
                                },
                            },
                        )
                    except Exception:
                        pass

                return ToolResult(
                    success=True,
                    output={
                        "file_path": str(path),
                        "content": output_text,
                        "is_directory": True,
                        "entry_count": len(entries),
                    },
                )
```

Add artifact:read emission for **file reads**. Find the successful file read return (around line 163):

```python
            return ToolResult(success=True, output=output)
```

(This is the one right after the `output` dict is built with `file_path`, `content`, `total_lines`, `lines_read`, `offset`.)

Replace with:

```python
            # Emit artifact:read hook event (fire-and-forget)
            if self.client is not None:
                try:
                    await self.client.request(
                        "request.hook_emit",
                        {
                            "event": ARTIFACT_READ,
                            "data": {
                                "path": str(path),
                                "is_directory": False,
                                "lines_read": len(selected_lines),
                            },
                        },
                    )
                except Exception:
                    pass

            return ToolResult(success=True, output=output)
```

### Step 4: Run tests to verify they pass

```bash
cd services/amplifier-foundation && python -m pytest tests/test_artifact_events.py -v && cd ../..
```
Expected: 8 PASS

### Step 5: Run the full foundation test suite

```bash
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..
```
Expected: All tests pass.

### Step 6: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/tools/filesystem/read.py services/amplifier-foundation/tests/test_artifact_events.py
git commit -m "feat(events): emit artifact:read from ReadTool on successful file/directory read"
```

---

## Task 4: Add `on_include` Callback to `resolve_and_load` and Emit `context:include`

**Files:**
- Modify: `src/amplifier_ipc/host/mentions.py` — add `on_include` callback parameter to `resolve_and_load()`
- Modify: `src/amplifier_ipc/host/host.py` — make `_load_working_dir_content` async, emit `context:include`
- Modify: `tests/host/test_mentions.py` — add tests for `on_include` callback

### Step 1: Write the failing tests

Append to `tests/host/test_mentions.py`:

```python
# ---------------------------------------------------------------------------
# Tests for on_include callback in resolve_and_load
# ---------------------------------------------------------------------------


def test_resolve_and_load_calls_on_include() -> None:
    """resolve_and_load calls on_include for each resolved mention."""
    chain = MentionResolverChain()
    chain.append(lambda m: "content" if m == "@project:test.md" else None)

    included: list[str] = []

    resolve_and_load(
        "Check @project:test.md for details",
        chain,
        on_include=included.append,
    )

    assert included == ["project:test.md"], f"Expected ['project:test.md'], got {included}"


def test_resolve_and_load_on_include_with_nested() -> None:
    """on_include fires for both parent and nested resolutions."""
    chain = MentionResolverChain()

    def resolver(mention: str) -> str | None:
        files = {
            "@project:parent.md": "See @project:child.md",
            "@project:child.md": "Child content",
        }
        return files.get(mention)

    chain.append(resolver)

    included: list[str] = []

    resolve_and_load(
        "Read @project:parent.md",
        chain,
        on_include=included.append,
    )

    assert included == ["project:parent.md", "project:child.md"], (
        f"Expected parent then child, got {included}"
    )


def test_resolve_and_load_on_include_not_called_for_unresolved() -> None:
    """on_include is NOT called when a mention cannot be resolved."""
    chain = MentionResolverChain()
    chain.append(lambda m: None)  # Always returns None

    included: list[str] = []

    resolve_and_load(
        "See @unknown:file.md",
        chain,
        on_include=included.append,
    )

    assert included == [], f"Expected empty list, got {included}"
```

### Step 2: Run tests to verify they fail

```bash
python -m pytest tests/host/test_mentions.py::test_resolve_and_load_calls_on_include tests/host/test_mentions.py::test_resolve_and_load_on_include_with_nested tests/host/test_mentions.py::test_resolve_and_load_on_include_not_called_for_unresolved -v
```
Expected: FAIL — `TypeError: resolve_and_load() got an unexpected keyword argument 'on_include'`

### Step 3: Add `on_include` parameter to `resolve_and_load()`

In `src/amplifier_ipc/host/mentions.py`, add the `Callable` import at the top. Find:

```python
from typing import Any, Protocol, runtime_checkable
```

Replace with:

```python
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable
```

Then update the `resolve_and_load` function signature and body. Find the function signature (line 271):

```python
def resolve_and_load(
    text: str,
    chain: _ResolvableChain,
    *,
    seen_hashes: set[str] | None = None,
    max_depth: int = 3,
) -> list[ResolvedContent]:
```

Replace with:

```python
def resolve_and_load(
    text: str,
    chain: _ResolvableChain,
    *,
    seen_hashes: set[str] | None = None,
    max_depth: int = 3,
    on_include: Callable[[str], None] | None = None,
) -> list[ResolvedContent]:
```

In the function body, add the `on_include` call after a mention is resolved. Find (around line 326):

```python
        resolved = ResolvedContent(key=mention.removeprefix("@"), content=content)
        results.append(resolved)
```

Replace with:

```python
        resolved = ResolvedContent(key=mention.removeprefix("@"), content=content)
        results.append(resolved)

        if on_include is not None:
            on_include(resolved.key)
```

Also pass `on_include` through to the recursive call. Find (around line 329):

```python
        nested = resolve_and_load(
            content,
            chain,
            seen_hashes=seen_hashes,
            max_depth=max_depth - 1,
        )
```

Replace with:

```python
        nested = resolve_and_load(
            content,
            chain,
            seen_hashes=seen_hashes,
            max_depth=max_depth - 1,
            on_include=on_include,
        )
```

### Step 4: Run tests to verify they pass

```bash
python -m pytest tests/host/test_mentions.py::test_resolve_and_load_calls_on_include tests/host/test_mentions.py::test_resolve_and_load_on_include_with_nested tests/host/test_mentions.py::test_resolve_and_load_on_include_not_called_for_unresolved -v
```
Expected: 3 PASS

### Step 5: Make `_load_working_dir_content` async and emit `context:include`

In `src/amplifier_ipc/host/host.py`, add the event constant import. Find the existing `amplifier_ipc_protocol.events` import (added in Phase 1):

```python
from amplifier_ipc_protocol.events import SESSION_START, SESSION_END
```

Replace with:

```python
from amplifier_ipc_protocol.events import CONTEXT_INCLUDE, SESSION_END, SESSION_START
```

Now make `_load_working_dir_content` async. Find (line 1120):

```python
    def _load_working_dir_content(self) -> str:
```

Replace with:

```python
    async def _load_working_dir_content(self) -> str:
```

Inside `_load_working_dir_content`, add `context:include` emission for each file loaded. Find the block where a file is added to parts (around line 1173–1174):

```python
            rel_path = file_path.relative_to(self._working_dir)
            parts.append(f'<context_file path="{rel_path}">\n{text}\n</context_file>')
```

Replace with:

```python
            rel_path = file_path.relative_to(self._working_dir)
            parts.append(f'<context_file path="{rel_path}">\n{text}\n</context_file>')

            await self._emit_hook_event(CONTEXT_INCLUDE, {
                "path": str(rel_path),
                "source": "file",
            })
```

Still inside `_load_working_dir_content`, add `on_include` callback and emission for nested mentions. Find (around line 1177):

```python
            # Resolve @mentions found in the file (shared dedup via seen_hashes)
            nested = resolve_and_load(
                text, self.mention_resolver, seen_hashes=seen_hashes
            )
```

Replace with:

```python
            # Resolve @mentions found in the file (shared dedup via seen_hashes)
            included_mentions: list[str] = []
            nested = resolve_and_load(
                text,
                self.mention_resolver,
                seen_hashes=seen_hashes,
                on_include=included_mentions.append,
            )
```

Then after the nested loop (after line 1183), emit `context:include` for each resolved mention. Find:

```python
            for resolved in nested:
                parts.append(
                    f'<context_file path="{resolved.key}">\n{resolved.content}\n</context_file>'
                )
```

Replace with:

```python
            for resolved in nested:
                parts.append(
                    f'<context_file path="{resolved.key}">\n{resolved.content}\n</context_file>'
                )
            for mention_key in included_mentions:
                await self._emit_hook_event(CONTEXT_INCLUDE, {
                    "path": mention_key,
                    "source": "mention",
                })
```

### Step 6: Update the caller of `_load_working_dir_content` to use `await`

In `src/amplifier_ipc/host/host.py`, find the call site (line 475):

```python
            working_dir_content = self._load_working_dir_content()
```

Replace with:

```python
            working_dir_content = await self._load_working_dir_content()
```

### Step 7: Run the full mention and host test suites

```bash
python -m pytest tests/host/test_mentions.py -v
python -m pytest tests/host/ -v
```
Expected: All tests pass (the new `on_include` parameter has a default value of `None` so existing callers are unaffected; `_load_working_dir_content` becoming async only requires the one caller to add `await`).

### Step 8: Commit

```bash
git add src/amplifier_ipc/host/mentions.py src/amplifier_ipc/host/host.py tests/host/test_mentions.py
git commit -m "feat(events): emit context:include during working-dir content loading and @mention resolution"
```

---

## Task 5: Inject Client into SimpleContextManager via Protocol Server

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/context_managers/simple.py` — add `client` attribute
- Modify: `src/amplifier_ipc/protocol/server.py` — inject client in `_handle_context_get_messages`
- Modify: `services/amplifier-foundation/tests/test_context_manager.py` — add test

### Step 1: Write the failing test

Append to `services/amplifier-foundation/tests/test_context_manager.py`:

```python
# ---------------------------------------------------------------------------
# Test 4: SimpleContextManager accepts client attribute
# ---------------------------------------------------------------------------


def test_context_manager_has_client_attribute() -> None:
    """SimpleContextManager must have a client attribute (defaults to None)."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]

    cm = SimpleContextManager()
    assert hasattr(cm, "client"), "SimpleContextManager must have a 'client' attribute"
    assert cm.client is None, "client should default to None"

    # Verify client can be set (server injection pattern)
    cm.client = "mock_client"
    assert cm.client == "mock_client"
```

### Step 2: Run test to verify it fails

```bash
cd services/amplifier-foundation && python -m pytest tests/test_context_manager.py::test_context_manager_has_client_attribute -v && cd ../..
```
Expected: FAIL — `AttributeError: 'SimpleContextManager' object has no attribute 'client'`

### Step 3: Add `client` attribute to SimpleContextManager

In `services/amplifier-foundation/src/amplifier_foundation/context_managers/simple.py`, find the `__init__` method (line 52):

```python
    def __init__(self) -> None:
        """Initialize the context manager with sensible defaults."""
        self.messages: list[Message] = []
```

Add the `client` attribute after `self.messages`:

```python
    def __init__(self) -> None:
        """Initialize the context manager with sensible defaults."""
        self.messages: list[Message] = []
        # Injected by the protocol server before get_messages() is called.
        # Enables hook event emission (e.g. compaction events).
        self.client: Any = None
```

### Step 4: Add client injection in `_handle_context_get_messages`

In `src/amplifier_ipc/protocol/server.py`, find `_handle_context_get_messages` (line 645). After the context manager is retrieved and before `get_messages()` is called, inject the client. Find:

```python
        ctx = ctx_managers[0]

        provider_info: dict[str, Any] = dict(params) if params else {}
        messages = await ctx.get_messages(provider_info)
```

Replace with:

```python
        ctx = ctx_managers[0]

        # Inject orchestrator client so the context manager can emit hook events
        if (
            hasattr(ctx, "client")
            and self._current_orchestrator_client is not None
        ):
            ctx.client = self._current_orchestrator_client

        provider_info: dict[str, Any] = dict(params) if params else {}
        messages = await ctx.get_messages(provider_info)
```

### Step 5: Run test to verify it passes

```bash
cd services/amplifier-foundation && python -m pytest tests/test_context_manager.py -v && cd ../..
```
Expected: 4 PASS (3 existing + 1 new)

### Step 6: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/context_managers/simple.py src/amplifier_ipc/protocol/server.py services/amplifier-foundation/tests/test_context_manager.py
git commit -m "feat(events): add client attribute to SimpleContextManager + server injection"
```

---

## Task 6: Emit Compaction Events from SimpleContextManager

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/context_managers/simple.py` — add helper + emissions in `get_messages()`
- Modify: `services/amplifier-foundation/tests/test_context_manager.py` — add compaction event tests

### Step 1: Write the failing tests

Append to `services/amplifier-foundation/tests/test_context_manager.py`:

```python
from typing import Any


# ---------------------------------------------------------------------------
# MockClient for compaction event tests
# ---------------------------------------------------------------------------


class MockClient:
    """Minimal mock IPC client that records request calls."""

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
# Test 5: Compaction events emitted when compaction triggers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compaction_events_emitted_when_compaction_occurs() -> None:
    """context:pre_compact, context:post_compact, context:compaction all fire during compaction."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]

    cm = SimpleContextManager()
    mock_client = MockClient()
    cm.client = mock_client

    # Set very low token budget so compaction triggers easily
    cm.max_tokens = 100
    cm.compact_threshold = 0.50  # compact at 50% usage
    cm.target_usage = 0.30
    cm.compaction_notice_enabled = False

    # Add enough messages to exceed the threshold (100 * 0.50 = 50 token budget).
    # Token estimation is len(content) // 4, so ~200 chars = ~50 tokens.
    await cm.add_message(Message(role="user", content="A" * 200))
    await cm.add_message(Message(role="assistant", content="B" * 200))
    await cm.add_message(Message(role="user", content="C" * 200))
    await cm.add_message(Message(role="assistant", content="D" * 200))

    # get_messages should trigger compaction
    messages = await cm.get_messages(provider_info={})

    # Check pre_compact
    pre_events = _hook_emits(mock_client, "context:pre_compact")
    assert len(pre_events) == 1, f"Expected 1 context:pre_compact, got {len(pre_events)}"
    assert "message_count" in pre_events[0]
    assert "token_count" in pre_events[0]
    assert pre_events[0]["message_count"] == 4  # 4 messages before compaction

    # Check post_compact
    post_events = _hook_emits(mock_client, "context:post_compact")
    assert len(post_events) == 1, f"Expected 1 context:post_compact, got {len(post_events)}"
    assert "message_count" in post_events[0]
    assert "token_count" in post_events[0]
    # After compaction, message count should be <= before
    assert post_events[0]["message_count"] <= pre_events[0]["message_count"]

    # Check compaction stats
    compaction_events = _hook_emits(mock_client, "context:compaction")
    assert len(compaction_events) == 1, (
        f"Expected 1 context:compaction, got {len(compaction_events)}"
    )
    stats = compaction_events[0]
    assert "before_tokens" in stats
    assert "after_tokens" in stats
    assert "before_messages" in stats
    assert "after_messages" in stats
    assert "strategy_level" in stats


# ---------------------------------------------------------------------------
# Test 6: NO compaction events when context fits within budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_compaction_events_when_not_needed() -> None:
    """No compaction events fire when messages fit within the token budget."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]

    cm = SimpleContextManager()
    mock_client = MockClient()
    cm.client = mock_client

    # Default max_tokens is 200000 — two short messages won't trigger compaction
    await cm.add_message(Message(role="user", content="Hello"))
    await cm.add_message(Message(role="assistant", content="Hi"))

    messages = await cm.get_messages(provider_info={})
    assert len(messages) == 2

    # No compaction events should have fired
    all_hook_emits = [
        (method, params)
        for method, params in mock_client.requests
        if method == "request.hook_emit"
    ]
    assert len(all_hook_emits) == 0, (
        f"Expected no hook_emit calls, got {len(all_hook_emits)}: "
        f"{[p.get('event') for _, p in all_hook_emits if isinstance(p, dict)]}"
    )


# ---------------------------------------------------------------------------
# Test 7: Compaction events work when client is None (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compaction_works_without_client() -> None:
    """Compaction still works correctly when client is None (no server injection)."""
    from amplifier_foundation.context_managers.simple import SimpleContextManager  # type: ignore[import]

    cm = SimpleContextManager()
    assert cm.client is None

    cm.max_tokens = 100
    cm.compact_threshold = 0.50
    cm.target_usage = 0.30
    cm.compaction_notice_enabled = False

    await cm.add_message(Message(role="user", content="A" * 200))
    await cm.add_message(Message(role="assistant", content="B" * 200))
    await cm.add_message(Message(role="user", content="C" * 200))
    await cm.add_message(Message(role="assistant", content="D" * 200))

    # Must NOT raise even though client is None
    messages = await cm.get_messages(provider_info={})
    assert len(messages) > 0
```

### Step 2: Run tests to verify they fail

```bash
cd services/amplifier-foundation && python -m pytest tests/test_context_manager.py::test_compaction_events_emitted_when_compaction_occurs tests/test_context_manager.py::test_no_compaction_events_when_not_needed tests/test_context_manager.py::test_compaction_works_without_client -v && cd ../..
```
Expected: FAIL — no `context:pre_compact` / `context:post_compact` / `context:compaction` events emitted

### Step 3: Add hook emission helper and compaction events to SimpleContextManager

In `services/amplifier-foundation/src/amplifier_foundation/context_managers/simple.py`, add the event constant imports at the top (after existing imports):

```python
from amplifier_ipc_protocol.events import (
    CONTEXT_COMPACTION,
    CONTEXT_POST_COMPACT,
    CONTEXT_PRE_COMPACT,
)
```

Add a helper method to SimpleContextManager for hook emission. Place it right after `__init__` (after line 66):

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
            logger.debug("Failed to emit hook event %r", event, exc_info=True)
```

Now add compaction event emissions in `get_messages()`. Find the block where compaction is triggered (around line 140):

```python
        # Check if compaction needed (using effective budget with notice reserve deducted)
        if self._should_compact(token_count, effective_budget):
            # Compact EPHEMERALLY - returns new list, working_messages unchanged
            compacted = await self._compact_ephemeral(
                effective_budget, working_messages
            )
```

Replace with:

```python
        # Check if compaction needed (using effective budget with notice reserve deducted)
        if self._should_compact(token_count, effective_budget):
            # --- emit context:pre_compact BEFORE compaction ---
            await self._emit_hook(CONTEXT_PRE_COMPACT, {
                "message_count": len(working_messages),
                "token_count": token_count,
            })

            # Compact EPHEMERALLY - returns new list, working_messages unchanged
            compacted = await self._compact_ephemeral(
                effective_budget, working_messages
            )
```

Then, after the compaction call and the info log (around line 146–147), add the post_compact and compaction events. Find:

```python
            logger.info(
                f"Ephemeral compaction: {len(working_messages)} -> {len(compacted)} messages for this request"
            )
```

Add immediately after it:

```python
            # --- emit context:post_compact and context:compaction AFTER compaction ---
            compacted_token_count = self._estimate_tokens(compacted)
            await self._emit_hook(CONTEXT_POST_COMPACT, {
                "message_count": len(compacted),
                "token_count": compacted_token_count,
            })
            if self._last_compaction_stats:
                await self._emit_hook(CONTEXT_COMPACTION, self._last_compaction_stats)
```

### Step 4: Run tests to verify they pass

```bash
cd services/amplifier-foundation && python -m pytest tests/test_context_manager.py -v && cd ../..
```
Expected: 7 PASS (4 existing + 3 new)

### Step 5: Run the full foundation test suite

```bash
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..
```
Expected: All tests pass.

### Step 6: Commit

```bash
git add services/amplifier-foundation/src/amplifier_foundation/context_managers/simple.py services/amplifier-foundation/tests/test_context_manager.py
git commit -m "feat(events): emit context:pre_compact, context:post_compact, context:compaction from SimpleContextManager"
```

---

## Post-Implementation Verification

After all 6 tasks are complete, run the full test suites:

```bash
# Root test suite (host tests, mention tests)
python -m pytest tests/ -v

# Foundation service tests (artifact events, context manager, orchestrator)
cd services/amplifier-foundation && python -m pytest tests/ -v && cd ../..
```

All tests should pass with zero failures.

### Summary of Changes

**Filesystem tools** — 3 files modified:

| File | Change |
|---|---|
| `tools/filesystem/write.py` | Added `client: Any = None`, emit `artifact:write` after successful write |
| `tools/filesystem/edit.py` | Added `client: Any = None`, emit `artifact:write` after successful edit |
| `tools/filesystem/read.py` | Added `client: Any = None`, emit `artifact:read` after successful read/listing |

**Mention resolution** — 2 files modified:

| File | Change |
|---|---|
| `mentions.py` | `resolve_and_load()` gained `on_include` callback parameter |
| `host.py` | `_load_working_dir_content()` now `async`, emits `context:include` for files and mentions |

**Context manager** — 2 files modified:

| File | Change |
|---|---|
| `simple.py` | Added `client: Any = None`, `_emit_hook()` helper, compaction event emissions in `get_messages()` |
| `server.py` | Inject orchestrator client into context manager in `_handle_context_get_messages()` |

**Event payloads:**

| Event | Payload |
|---|---|
| `artifact:write` | `{"path": str, "bytes": int}` |
| `artifact:read` | `{"path": str, "is_directory": bool, "lines_read": int}` or `{"path": str, "is_directory": bool, "entry_count": int}` |
| `context:include` | `{"path": str, "source": "file" \| "mention"}` |
| `context:pre_compact` | `{"message_count": int, "token_count": int}` |
| `context:post_compact` | `{"message_count": int, "token_count": int}` |
| `context:compaction` | Full stats dict: `{before_tokens, after_tokens, before_messages, after_messages, messages_removed, messages_truncated, user_messages_stubbed, system_messages_preserved, strategy_level, budget, target_tokens, protected_recent, protected_tool_results}` |

**Test files:**
- `services/amplifier-foundation/tests/test_artifact_events.py` — 8 new tests (artifact events)
- `tests/host/test_mentions.py` — 3 new tests (on_include callback)
- `services/amplifier-foundation/tests/test_context_manager.py` — 4 new tests (client attribute + compaction events)

### What's Now Unblocked

After Phase 4, the following hooks receive events they subscribe to:
- **RedactionHook** — receives `context:pre_compact`, `context:post_compact`, `artifact:write`, `artifact:read` → can redact secrets from artifact paths and manage state across compaction boundaries
- **ShellHook** — receives `context:pre_compact` → shell bridge gets compaction lifecycle events
- **LoggingHook** — receives all 6 events → `events.jsonl` audit log now captures artifact operations, context inclusion, and compaction activity

### What's NOT in This Phase (Deferred)

- `plan:start` / `plan:end` — No planning subsystem exists (never implemented in old system either)
- `context:include` from `_preprocess_tool_mentions()` — Tool-arg mention substitution is lower priority; can be added in a future enhancement
- `context:include` from `_resolve_agent_base()` — Agent base resolution is less frequent; can be added later