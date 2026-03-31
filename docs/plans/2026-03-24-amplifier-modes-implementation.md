# Amplifier Modes Service Completion — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Complete the `amplifier-modes` tool by wiring the stubbed `ModeTool` to the already-functional `ModeHooks`, enabling set/clear/list/current operations end-to-end.

**Architecture:** The hook (`ModeHooks`) already owns all runtime state (`_active_mode`, `_warned_tools`). A thin `ModeServer` subclass in `__main__.py` wires the tool to the hook at startup via `_build_runtime_state()`. The tool delegates all state reads/writes to the hook through this reference. Zero protocol changes.

**Tech Stack:** Python 3.11+, pytest + pytest-asyncio, amplifier-ipc protocol framework, PyYAML

**Design doc:** `docs/designs/amplifier-modes-completion.md`

**Out of scope:** Modifying `src/amplifier_ipc/protocol/server.py`, adding built-in modes, generic tool-to-hook injection, new abstractions or singletons.

---

## How to Run Tests

All tests run from the service directory using `uv`:

```bash
cd services/amplifier-modes && uv run pytest tests/ -v
```

To run a specific test:

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py::test_name -v
```

---

## Files Overview

| File | Action | Description |
|---|---|---|
| `services/amplifier-modes/src/amplifier_modes/hooks/mode.py` | Modify | Add 3 public accessor methods (~10 lines) |
| `services/amplifier-modes/src/amplifier_modes/tools/mode.py` | Modify | Replace 4 stub methods (~40 lines) |
| `services/amplifier-modes/src/amplifier_modes/__main__.py` | Modify | Add `ModeServer` subclass (~15 lines) |
| `services/amplifier-modes/tests/test_mode_operations.py` | Create | All new tests (~200 lines) |

---

### Task 1: Add Hook Accessor Methods

**Files:**
- Modify: `services/amplifier-modes/src/amplifier_modes/hooks/mode.py` (after line 105, inside `ModeHooks`)
- Test: `services/amplifier-modes/tests/test_mode_operations.py` (create)

**Step 1: Create test file with hook accessor tests**

Create `services/amplifier-modes/tests/test_mode_operations.py`:

```python
"""Tests for mode tool operations, hook accessors, and server wiring."""

from __future__ import annotations

import pytest

from amplifier_modes.hooks.mode import ModeDefinition, ModeHooks


# ---------------------------------------------------------------------------
# Task 1: Hook accessor methods
# ---------------------------------------------------------------------------


def test_get_active_mode_returns_none_by_default() -> None:
    """A fresh ModeHooks instance has no active mode."""
    hook = ModeHooks()
    result = hook.get_active_mode()
    assert result is None, f"Expected None, got {result}"


def test_set_active_mode_stores_mode() -> None:
    """set_active_mode stores the mode so get_active_mode returns it."""
    hook = ModeHooks()
    mode = ModeDefinition(name="focus", description="Focus mode")
    hook.set_active_mode(mode)
    result = hook.get_active_mode()
    assert result is mode, f"Expected {mode}, got {result}"


def test_set_active_mode_clears_warned_tools() -> None:
    """set_active_mode resets the warned tools set."""
    hook = ModeHooks()
    # Simulate a prior warning
    hook._warned_tools.add("focus:bash")
    mode = ModeDefinition(name="focus", description="Focus mode")
    hook.set_active_mode(mode)
    assert len(hook._warned_tools) == 0, f"Expected empty warned_tools, got {hook._warned_tools}"


def test_clear_active_mode_removes_mode() -> None:
    """clear_active_mode sets active mode back to None."""
    hook = ModeHooks()
    hook._active_mode = ModeDefinition(name="focus", description="Focus mode")
    hook.clear_active_mode()
    result = hook.get_active_mode()
    assert result is None, f"Expected None after clear, got {result}"


def test_clear_active_mode_clears_warned_tools() -> None:
    """clear_active_mode also resets the warned tools set."""
    hook = ModeHooks()
    hook._warned_tools.add("focus:bash")
    hook._active_mode = ModeDefinition(name="focus", description="Focus mode")
    hook.clear_active_mode()
    assert len(hook._warned_tools) == 0, f"Expected empty warned_tools, got {hook._warned_tools}"


def test_clear_active_mode_is_idempotent() -> None:
    """Clearing when nothing is active does not raise."""
    hook = ModeHooks()
    hook.clear_active_mode()  # should not raise
    result = hook.get_active_mode()
    assert result is None, f"Expected None, got {result}"
```

**Step 2: Run the test to verify it fails**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_get_active_mode or test_set_active_mode or test_clear_active_mode"
```

Expected: FAIL — `AttributeError: 'ModeHooks' object has no attribute 'get_active_mode'` (or similar for set/clear).

**Step 3: Add the three accessor methods to ModeHooks**

In `services/amplifier-modes/src/amplifier_modes/hooks/mode.py`, add these three methods to the `ModeHooks` class, right after the `__init__` method (after line 105):

```python
    def set_active_mode(self, mode: ModeDefinition) -> None:
        """Set the active mode and reset warned-tools state."""
        self._active_mode = mode
        self._warned_tools.clear()

    def clear_active_mode(self) -> None:
        """Clear the active mode and reset warned-tools state."""
        self._active_mode = None
        self._warned_tools.clear()

    def get_active_mode(self) -> ModeDefinition | None:
        """Return the currently active mode, or None."""
        return self._active_mode
```

The exact edit: find the block starting at `def __init__` through the blank line before `async def handle`, and insert the three methods between `__init__` and `handle`.

**Step 4: Run tests to verify they pass**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_get_active_mode or test_set_active_mode or test_clear_active_mode"
```

Expected: All 6 tests PASS.

**Step 5: Commit**

```bash
git add services/amplifier-modes/src/amplifier_modes/hooks/mode.py services/amplifier-modes/tests/test_mode_operations.py && git commit -m "feat(modes): add hook accessor methods for mode state"
```

---

### Task 2: Add ModeServer Wiring Subclass

**Files:**
- Modify: `services/amplifier-modes/src/amplifier_modes/__main__.py`
- Test: `services/amplifier-modes/tests/test_mode_operations.py` (append)

**Step 1: Write the wiring tests**

Append to `services/amplifier-modes/tests/test_mode_operations.py`:

```python
# ---------------------------------------------------------------------------
# Task 2: ModeServer wiring
# ---------------------------------------------------------------------------

import asyncio
import json


class _MockWriter:
    """Collects bytes written via write()/drain() for later assertion."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


@pytest.mark.asyncio
async def test_mode_server_wires_tool_to_hook() -> None:
    """ModeServer._build_runtime_state wires ModeTool._mode_hooks to the ModeHooks instance."""
    from amplifier_modes.__main__ import ModeServer

    server = ModeServer("amplifier_modes")

    # Send configure to trigger instance creation and wiring
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    configure_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "configure", "params": {}}) + "\n"
    reader.feed_data(configure_req.encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    # After configure, the tool should be wired to the hook
    mode_tool = server._tools.get("mode")
    assert mode_tool is not None, f"Expected 'mode' tool in server._tools, got keys: {list(server._tools.keys())}"

    hook_ref = getattr(mode_tool, "_mode_hooks", None)
    assert hook_ref is not None, "Expected ModeTool._mode_hooks to be set after configure"
    assert isinstance(hook_ref, ModeHooks), f"Expected ModeHooks instance, got {type(hook_ref)}"


@pytest.mark.asyncio
async def test_mode_server_describe_still_works() -> None:
    """ModeServer must still respond to describe correctly (no regression)."""
    from amplifier_modes.__main__ import ModeServer

    server = ModeServer("amplifier_modes")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "describe"}) + "\n"
    reader.feed_data(request.encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)

    messages = writer.messages
    assert len(messages) == 1, f"Expected 1 response, got {len(messages)}"
    result = messages[0].get("result", {})
    tool_names = [t["name"] for t in result.get("capabilities", {}).get("tools", [])]
    assert "mode" in tool_names, f"Expected 'mode' tool in describe, got: {tool_names}"
```

**Step 2: Run to verify tests fail**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py::test_mode_server_wires_tool_to_hook -v
```

Expected: FAIL — `ImportError: cannot import name 'ModeServer' from 'amplifier_modes.__main__'`

**Step 3: Implement ModeServer in `__main__.py`**

Replace the entire contents of `services/amplifier-modes/src/amplifier_modes/__main__.py` with:

```python
"""Entry point for amplifier-modes IPC service."""

from __future__ import annotations

from amplifier_ipc.protocol import Server

from amplifier_modes.hooks.mode import ModeHooks
from amplifier_modes.tools.mode import ModeTool


class ModeServer(Server):
    """Server subclass that wires ModeTool to ModeHooks at startup."""

    def _build_runtime_state(self) -> None:
        super()._build_runtime_state()

        # Find the ModeTool and ModeHooks instances and wire them together
        mode_tool = self._tools.get("mode")
        mode_hook = next(
            (h for h in self._hook_instances if isinstance(h, ModeHooks)),
            None,
        )
        if mode_tool is not None and mode_hook is not None:
            mode_tool._mode_hooks = mode_hook


def main() -> None:
    """Start the amplifier-modes IPC service."""
    ModeServer("amplifier_modes").run()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_mode_server"
```

Expected: Both `test_mode_server_wires_tool_to_hook` and `test_mode_server_describe_still_works` PASS.

**Step 5: Run ALL existing tests to verify no regressions**

```bash
cd services/amplifier-modes && uv run pytest tests/ -v
```

Expected: All tests PASS (existing test_scaffolding, test_describe, test_content, plus new tests).

**Step 6: Commit**

```bash
git add services/amplifier-modes/src/amplifier_modes/__main__.py services/amplifier-modes/tests/test_mode_operations.py && git commit -m "feat(modes): add ModeServer subclass with tool-to-hook wiring"
```

---

### Task 3: Implement `_handle_current`

**Files:**
- Modify: `services/amplifier-modes/src/amplifier_modes/tools/mode.py` (lines 75-83)
- Test: `services/amplifier-modes/tests/test_mode_operations.py` (append)

**Step 1: Write the tests**

Append to `services/amplifier-modes/tests/test_mode_operations.py`:

```python
# ---------------------------------------------------------------------------
# Task 3: _handle_current
# ---------------------------------------------------------------------------

from amplifier_modes.tools.mode import ModeTool


@pytest.mark.asyncio
async def test_current_returns_none_when_no_mode_active() -> None:
    """current operation returns active_mode: None when nothing is active."""
    tool = ModeTool()
    tool._mode_hooks = ModeHooks()

    result = await tool.execute({"operation": "current"})
    assert result.success is True, f"Expected success, got error: {result.error}"
    assert result.output.get("active_mode") is None, f"Expected active_mode None, got {result.output}"


@pytest.mark.asyncio
async def test_current_returns_mode_info_when_active() -> None:
    """current operation returns mode name and description when a mode is active."""
    tool = ModeTool()
    hook = ModeHooks()
    hook.set_active_mode(ModeDefinition(name="focus", description="Deep focus"))
    tool._mode_hooks = hook

    result = await tool.execute({"operation": "current"})
    assert result.success is True, f"Expected success, got error: {result.error}"
    assert result.output.get("active_mode") == "focus", f"Expected 'focus', got {result.output}"
    assert result.output.get("description") == "Deep focus", f"Expected 'Deep focus', got {result.output}"


@pytest.mark.asyncio
async def test_current_returns_error_when_hooks_not_wired() -> None:
    """current operation returns error when _mode_hooks is None."""
    tool = ModeTool()
    # Do NOT set _mode_hooks — it should be None

    result = await tool.execute({"operation": "current"})
    assert result.success is False, f"Expected failure, got success: {result.output}"
    assert result.error.get("code") == "not_ready", f"Expected 'not_ready' error, got {result.error}"
```

**Step 2: Run to verify tests fail**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_current"
```

Expected: `test_current_returns_mode_info_when_active` FAILS (stub returns hardcoded None). `test_current_returns_error_when_hooks_not_wired` FAILS (stub doesn't check `_mode_hooks`).

**Step 3: Implement `_handle_current`**

In `services/amplifier-modes/src/amplifier_modes/tools/mode.py`:

1. Add the `_mode_hooks` class attribute after the `input_schema` dict (around line 45):

```python
    _mode_hooks: ModeHooks | None = None
```

2. Add the not-ready guard method (right before `execute`):

```python
    def _not_ready_result(self) -> ToolResult:
        """Return an error result when hooks are not wired."""
        return ToolResult(
            success=False,
            error={"code": "not_ready", "message": "Mode service not ready"},
        )
```

3. Replace the `_handle_current` method (lines 75-83) with:

```python
    async def _handle_current(self) -> ToolResult:
        """Show the currently active mode."""
        if self._mode_hooks is None:
            return self._not_ready_result()

        mode = self._mode_hooks.get_active_mode()
        if mode is None:
            return ToolResult(
                success=True,
                output={"active_mode": None, "message": "No mode is currently active."},
            )
        return ToolResult(
            success=True,
            output={"active_mode": mode.name, "description": mode.description},
        )
```

4. Add the import for `ModeHooks` at the top of the file. Add this line after the existing imports (after line 8):

```python
from amplifier_modes.hooks.mode import ModeHooks
```

**Step 4: Run tests to verify they pass**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_current"
```

Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add services/amplifier-modes/src/amplifier_modes/tools/mode.py services/amplifier-modes/tests/test_mode_operations.py && git commit -m "feat(modes): implement _handle_current operation"
```

---

### Task 4: Implement `_handle_clear`

**Files:**
- Modify: `services/amplifier-modes/src/amplifier_modes/tools/mode.py` (lines 89-97)
- Test: `services/amplifier-modes/tests/test_mode_operations.py` (append)

**Step 1: Write the tests**

Append to `services/amplifier-modes/tests/test_mode_operations.py`:

```python
# ---------------------------------------------------------------------------
# Task 4: _handle_clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_deactivates_active_mode() -> None:
    """clear operation removes the active mode."""
    tool = ModeTool()
    hook = ModeHooks()
    hook.set_active_mode(ModeDefinition(name="focus", description="Focus mode"))
    tool._mode_hooks = hook

    result = await tool.execute({"operation": "clear"})
    assert result.success is True, f"Expected success, got error: {result.error}"
    assert result.output.get("status") == "cleared", f"Expected 'cleared', got {result.output}"

    # Verify the hook state was actually cleared
    assert hook.get_active_mode() is None, f"Expected no active mode, got {hook.get_active_mode()}"


@pytest.mark.asyncio
async def test_clear_is_idempotent() -> None:
    """clear when nothing is active still returns success."""
    tool = ModeTool()
    tool._mode_hooks = ModeHooks()

    result = await tool.execute({"operation": "clear"})
    assert result.success is True, f"Expected success, got error: {result.error}"
    assert result.output.get("status") == "cleared", f"Expected 'cleared', got {result.output}"


@pytest.mark.asyncio
async def test_clear_returns_error_when_hooks_not_wired() -> None:
    """clear operation returns error when _mode_hooks is None."""
    tool = ModeTool()

    result = await tool.execute({"operation": "clear"})
    assert result.success is False, f"Expected failure, got success: {result.output}"
    assert result.error.get("code") == "not_ready", f"Expected 'not_ready' error, got {result.error}"
```

**Step 2: Run to verify tests fail**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_clear"
```

Expected: `test_clear_deactivates_active_mode` FAILS (stub doesn't call hook). `test_clear_returns_error_when_hooks_not_wired` FAILS (stub doesn't check `_mode_hooks`).

**Step 3: Implement `_handle_clear`**

In `services/amplifier-modes/src/amplifier_modes/tools/mode.py`, replace the `_handle_clear` method with:

```python
    async def _handle_clear(self) -> ToolResult:
        """Deactivate the current mode."""
        if self._mode_hooks is None:
            return self._not_ready_result()

        self._mode_hooks.clear_active_mode()
        return ToolResult(
            success=True,
            output={"status": "cleared", "message": "Mode deactivated."},
        )
```

**Step 4: Run tests to verify they pass**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_clear"
```

Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add services/amplifier-modes/src/amplifier_modes/tools/mode.py services/amplifier-modes/tests/test_mode_operations.py && git commit -m "feat(modes): implement _handle_clear operation"
```

---

### Task 5: Add Mode Discovery

**Files:**
- Modify: `services/amplifier-modes/src/amplifier_modes/tools/mode.py`
- Test: `services/amplifier-modes/tests/test_mode_operations.py` (append)

**Step 1: Write the tests**

Append to `services/amplifier-modes/tests/test_mode_operations.py`:

```python
# ---------------------------------------------------------------------------
# Task 5: Mode discovery
# ---------------------------------------------------------------------------

from pathlib import Path

_SAMPLE_MODE_CONTENT = """\
---
mode:
  name: focus
  description: Deep focus mode
  shortcut: f
  tools:
    safe: [read_file, grep]
    warn: [bash]
  default_action: block
---

You are in focus mode. Only read and search.
"""

_SAMPLE_MODE_2_CONTENT = """\
---
mode:
  name: plan
  description: Planning mode
  shortcut: p
  default_action: block
---

You are in planning mode.
"""


def _write_mode_file(base: Path, name: str, content: str) -> None:
    """Write a mode file to base/.amplifier/modes/name.md."""
    mode_dir = base / ".amplifier" / "modes"
    mode_dir.mkdir(parents=True, exist_ok=True)
    (mode_dir / f"{name}.md").write_text(content)


def test_discover_modes_finds_project_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_discover_modes finds .md files in cwd/.amplifier/modes/."""
    _write_mode_file(tmp_path, "focus", _SAMPLE_MODE_CONTENT)
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "fakehome"))

    tool = ModeTool()
    modes = tool._discover_modes()
    names = [m.name for m in modes]
    assert "focus" in names, f"Expected 'focus' in discovered modes, got {names}"


def test_discover_modes_finds_user_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_discover_modes finds .md files in home/.amplifier/modes/."""
    user_home = tmp_path / "home"
    _write_mode_file(user_home, "plan", _SAMPLE_MODE_2_CONTENT)
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path / "project"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))

    tool = ModeTool()
    modes = tool._discover_modes()
    names = [m.name for m in modes]
    assert "plan" in names, f"Expected 'plan' in discovered modes, got {names}"


def test_discover_modes_project_overrides_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When both project and user have a mode with the same name, project wins."""
    project_dir = tmp_path / "project"
    user_home = tmp_path / "home"

    _write_mode_file(project_dir, "focus", _SAMPLE_MODE_CONTENT)

    # User-level mode with same name but different description
    user_focus = _SAMPLE_MODE_CONTENT.replace("Deep focus mode", "User focus mode")
    _write_mode_file(user_home, "focus", user_focus)

    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: project_dir))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))

    tool = ModeTool()
    modes = tool._discover_modes()
    focus_modes = [m for m in modes if m.name == "focus"]
    assert len(focus_modes) == 1, f"Expected exactly 1 'focus' mode, got {len(focus_modes)}"
    assert focus_modes[0].description == "Deep focus mode", (
        f"Expected project-level description, got '{focus_modes[0].description}'"
    )


def test_discover_modes_missing_dirs_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_discover_modes returns empty list when no .amplifier/modes/ dirs exist."""
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path / "empty_project"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "empty_home"))

    tool = ModeTool()
    modes = tool._discover_modes()
    assert modes == [], f"Expected empty list, got {modes}"


def test_discover_modes_merges_both_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_discover_modes merges project-level and user-level modes with distinct names."""
    project_dir = tmp_path / "project"
    user_home = tmp_path / "home"

    _write_mode_file(project_dir, "focus", _SAMPLE_MODE_CONTENT)
    _write_mode_file(user_home, "plan", _SAMPLE_MODE_2_CONTENT)

    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: project_dir))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))

    tool = ModeTool()
    modes = tool._discover_modes()
    names = sorted([m.name for m in modes])
    assert "focus" in names, f"Expected 'focus' in {names}"
    assert "plan" in names, f"Expected 'plan' in {names}"
```

**Step 2: Run to verify tests fail**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_discover"
```

Expected: FAIL — `AttributeError: 'ModeTool' object has no attribute '_discover_modes'`

**Step 3: Implement `_discover_modes`**

In `services/amplifier-modes/src/amplifier_modes/tools/mode.py`, add this import after the `ModeHooks` import:

```python
from amplifier_modes.hooks.mode import ModeDefinition, ModeHooks, parse_mode_file
```

(Replace the existing `from amplifier_modes.hooks.mode import ModeHooks` line with this one.)

Then add the `_discover_modes` method to the `ModeTool` class. Place it after `_not_ready_result` and before `execute`:

```python
    def _discover_modes(self) -> list[ModeDefinition]:
        """Scan project-level and user-level mode directories for .md mode files.

        Project-level modes (cwd/.amplifier/modes/) take priority over
        user-level modes (home/.amplifier/modes/) on name collision.
        """
        from pathlib import Path

        modes_by_name: dict[str, ModeDefinition] = {}

        # User-level first (so project-level overwrites on collision)
        for base in [Path.home(), Path.cwd()]:
            mode_dir = base / ".amplifier" / "modes"
            if not mode_dir.is_dir():
                continue
            for file_path in sorted(mode_dir.glob("*.md")):
                mode = parse_mode_file(file_path)
                if mode is not None:
                    mode.source = str(file_path)
                    modes_by_name[mode.name] = mode

        return list(modes_by_name.values())
```

**Step 4: Run tests to verify they pass**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_discover"
```

Expected: All 5 discovery tests PASS.

**Step 5: Commit**

```bash
git add services/amplifier-modes/src/amplifier_modes/tools/mode.py services/amplifier-modes/tests/test_mode_operations.py && git commit -m "feat(modes): add _discover_modes for filesystem mode scanning"
```

---

### Task 6: Implement `_handle_list`

**Files:**
- Modify: `services/amplifier-modes/src/amplifier_modes/tools/mode.py` (lines 68-73)
- Test: `services/amplifier-modes/tests/test_mode_operations.py` (append)

**Step 1: Write the tests**

Append to `services/amplifier-modes/tests/test_mode_operations.py`:

```python
# ---------------------------------------------------------------------------
# Task 6: _handle_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_discovered_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """list operation returns all discovered modes with name/description/shortcut."""
    _write_mode_file(tmp_path, "focus", _SAMPLE_MODE_CONTENT)
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "fakehome"))

    tool = ModeTool()
    tool._mode_hooks = ModeHooks()

    result = await tool.execute({"operation": "list"})
    assert result.success is True, f"Expected success, got error: {result.error}"

    modes = result.output.get("modes", [])
    assert len(modes) >= 1, f"Expected at least 1 mode, got {modes}"

    focus = next((m for m in modes if m["name"] == "focus"), None)
    assert focus is not None, f"Expected 'focus' in modes list, got {modes}"
    assert focus["description"] == "Deep focus mode", f"Expected description, got {focus}"
    assert focus["shortcut"] == "f", f"Expected shortcut 'f', got {focus}"


@pytest.mark.asyncio
async def test_list_returns_empty_when_no_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """list operation returns empty list when no mode files exist."""
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path / "empty"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "emptyhome"))

    tool = ModeTool()
    tool._mode_hooks = ModeHooks()

    result = await tool.execute({"operation": "list"})
    assert result.success is True, f"Expected success, got error: {result.error}"
    assert result.output.get("modes") == [], f"Expected empty modes list, got {result.output}"


@pytest.mark.asyncio
async def test_list_returns_error_when_hooks_not_wired() -> None:
    """list operation returns error when _mode_hooks is None."""
    tool = ModeTool()

    result = await tool.execute({"operation": "list"})
    assert result.success is False, f"Expected failure, got success: {result.output}"
    assert result.error.get("code") == "not_ready", f"Expected 'not_ready', got {result.error}"
```

**Step 2: Run to verify tests fail**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_list"
```

Expected: `test_list_returns_discovered_modes` FAILS (stub returns hardcoded empty list). `test_list_returns_error_when_hooks_not_wired` FAILS (stub doesn't check `_mode_hooks`).

**Step 3: Implement `_handle_list`**

In `services/amplifier-modes/src/amplifier_modes/tools/mode.py`, replace the `_handle_list` method with:

```python
    async def _handle_list(self) -> ToolResult:
        """List available modes from filesystem."""
        if self._mode_hooks is None:
            return self._not_ready_result()

        modes = self._discover_modes()
        return ToolResult(
            success=True,
            output={
                "modes": [
                    {
                        "name": m.name,
                        "description": m.description,
                        "shortcut": m.shortcut,
                    }
                    for m in modes
                ]
            },
        )
```

**Step 4: Run tests to verify they pass**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_list"
```

Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add services/amplifier-modes/src/amplifier_modes/tools/mode.py services/amplifier-modes/tests/test_mode_operations.py && git commit -m "feat(modes): implement _handle_list operation"
```

---

### Task 7: Implement `_handle_set`

**Files:**
- Modify: `services/amplifier-modes/src/amplifier_modes/tools/mode.py` (lines 85-87)
- Test: `services/amplifier-modes/tests/test_mode_operations.py` (append)

**Step 1: Write the tests**

Append to `services/amplifier-modes/tests/test_mode_operations.py`:

```python
# ---------------------------------------------------------------------------
# Task 7: _handle_set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_activates_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """set operation activates the named mode."""
    _write_mode_file(tmp_path, "focus", _SAMPLE_MODE_CONTENT)
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "fakehome"))

    tool = ModeTool()
    hook = ModeHooks()
    tool._mode_hooks = hook

    result = await tool.execute({"operation": "set", "name": "focus"})
    assert result.success is True, f"Expected success, got error: {result.error}"
    assert result.output.get("name") == "focus", f"Expected name 'focus', got {result.output}"

    # Verify the hook state was actually set
    active = hook.get_active_mode()
    assert active is not None, "Expected active mode to be set"
    assert active.name == "focus", f"Expected active mode 'focus', got '{active.name}'"


@pytest.mark.asyncio
async def test_set_unknown_mode_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """set with unknown mode name returns error with available modes list."""
    _write_mode_file(tmp_path, "focus", _SAMPLE_MODE_CONTENT)
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "fakehome"))

    tool = ModeTool()
    tool._mode_hooks = ModeHooks()

    result = await tool.execute({"operation": "set", "name": "nonexistent"})
    assert result.success is False, f"Expected failure, got success: {result.output}"
    assert "nonexistent" in result.error.get("message", ""), (
        f"Expected error message to mention 'nonexistent', got {result.error}"
    )
    assert "focus" in str(result.error.get("available", [])), (
        f"Expected available modes to include 'focus', got {result.error}"
    )


@pytest.mark.asyncio
async def test_set_replaces_existing_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """set when a mode is already active replaces it."""
    _write_mode_file(tmp_path, "focus", _SAMPLE_MODE_CONTENT)
    _write_mode_file(tmp_path, "plan", _SAMPLE_MODE_2_CONTENT)
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "fakehome"))

    tool = ModeTool()
    hook = ModeHooks()
    tool._mode_hooks = hook

    await tool.execute({"operation": "set", "name": "focus"})
    result = await tool.execute({"operation": "set", "name": "plan"})

    assert result.success is True, f"Expected success, got error: {result.error}"
    active = hook.get_active_mode()
    assert active.name == "plan", f"Expected 'plan', got '{active.name}'"


@pytest.mark.asyncio
async def test_set_missing_name_returns_error() -> None:
    """set without a 'name' parameter returns error."""
    tool = ModeTool()
    tool._mode_hooks = ModeHooks()

    result = await tool.execute({"operation": "set"})
    assert result.success is False, f"Expected failure, got success: {result.output}"
    assert result.error.get("code") == "missing_name", f"Expected 'missing_name', got {result.error}"


@pytest.mark.asyncio
async def test_set_returns_error_when_hooks_not_wired() -> None:
    """set operation returns error when _mode_hooks is None."""
    tool = ModeTool()

    result = await tool.execute({"operation": "set", "name": "focus"})
    assert result.success is False, f"Expected failure, got success: {result.output}"
    assert result.error.get("code") == "not_ready", f"Expected 'not_ready', got {result.error}"


@pytest.mark.asyncio
async def test_set_with_no_modes_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """set when no mode files exist returns error."""
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path / "empty"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "emptyhome"))

    tool = ModeTool()
    tool._mode_hooks = ModeHooks()

    result = await tool.execute({"operation": "set", "name": "focus"})
    assert result.success is False, f"Expected failure, got success: {result.output}"
```

**Step 2: Run to verify tests fail**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_set"
```

Expected: FAIL — `NotImplementedError: ModeTool.set is not yet implemented`

**Step 3: Implement `_handle_set`**

In `services/amplifier-modes/src/amplifier_modes/tools/mode.py`, replace the `_handle_set` method with:

```python
    async def _handle_set(self, input: dict[str, Any]) -> ToolResult:
        """Activate a mode by name."""
        if self._mode_hooks is None:
            return self._not_ready_result()

        name = input.get("name")
        if not name:
            return ToolResult(
                success=False,
                error={"code": "missing_name", "message": "The 'name' parameter is required for set."},
            )

        modes = self._discover_modes()
        mode = next((m for m in modes if m.name == name), None)

        if mode is None:
            available = [m.name for m in modes]
            return ToolResult(
                success=False,
                error={
                    "code": "unknown_mode",
                    "message": f"Mode '{name}' not found.",
                    "available": available,
                },
            )

        self._mode_hooks.set_active_mode(mode)
        return ToolResult(
            success=True,
            output={
                "name": mode.name,
                "description": mode.description,
                "message": f"Mode '{mode.name}' activated.",
            },
        )
```

**Step 4: Run tests to verify they pass**

```bash
cd services/amplifier-modes && uv run pytest tests/test_mode_operations.py -v -k "test_set"
```

Expected: All 6 tests PASS.

**Step 5: Run the FULL test suite**

```bash
cd services/amplifier-modes && uv run pytest tests/ -v
```

Expected: ALL tests PASS — both the new `test_mode_operations.py` and the existing tests.

**Step 6: Commit**

```bash
git add services/amplifier-modes/src/amplifier_modes/tools/mode.py services/amplifier-modes/tests/test_mode_operations.py && git commit -m "feat(modes): implement _handle_set operation — all tool stubs complete"
```

---

## Final File States

After all 7 tasks, here is what each modified file should look like:

### `services/amplifier-modes/src/amplifier_modes/hooks/mode.py`

Unchanged except for 3 new methods added to `ModeHooks` between `__init__` and `handle`:
- `set_active_mode(self, mode: ModeDefinition) -> None`
- `clear_active_mode(self) -> None`
- `get_active_mode(self) -> ModeDefinition | None`

### `services/amplifier-modes/src/amplifier_modes/tools/mode.py`

- New import: `from amplifier_modes.hooks.mode import ModeDefinition, ModeHooks, parse_mode_file`
- New class attribute: `_mode_hooks: ModeHooks | None = None`
- New method: `_not_ready_result(self) -> ToolResult`
- New method: `_discover_modes(self) -> list[ModeDefinition]`
- Replaced stubs: `_handle_current`, `_handle_clear`, `_handle_list`, `_handle_set`

### `services/amplifier-modes/src/amplifier_modes/__main__.py`

- Imports added for `ModeHooks` and `ModeTool`
- `ModeServer(Server)` subclass with `_build_runtime_state` override
- `main()` uses `ModeServer` instead of `Server`

### `services/amplifier-modes/tests/test_mode_operations.py`

New file with ~30 tests covering all operations, wiring, discovery, and error cases.
