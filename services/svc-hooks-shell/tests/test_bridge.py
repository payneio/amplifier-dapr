"""Tests for ShellHookBridge."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from svc_hooks_shell.bridge import ShellHookBridge


# --- Test 1: no hooks_dir, unknown event returns CONTINUE ---
@pytest.mark.asyncio
async def test_no_hooks_dir_unknown_event_continues():
    bridge = ShellHookBridge(hooks_dir=None)
    result = await bridge.handle("unknown:event", {})
    assert result.action == "CONTINUE"


# --- Test 2: no hooks_dir, tool:pre returns CONTINUE ---
@pytest.mark.asyncio
async def test_no_hooks_dir_tool_pre_continues():
    bridge = ShellHookBridge(hooks_dir=None)
    result = await bridge.handle("tool:pre", {"tool_name": "bash"})
    assert result.action == "CONTINUE"


# --- Test 3: no hooks_dir, tool:post returns CONTINUE ---
@pytest.mark.asyncio
async def test_no_hooks_dir_tool_post_continues():
    bridge = ShellHookBridge(hooks_dir=None)
    result = await bridge.handle("tool:post", {"tool_name": "bash"})
    assert result.action == "CONTINUE"


# --- Test 4: with script, exit code 0 -> CONTINUE ---
@pytest.mark.asyncio
async def test_with_script_exit_0_continues(tmp_path: Path):
    script = tmp_path / "pre-tool"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    bridge = ShellHookBridge(hooks_dir=tmp_path)
    result = await bridge.handle("tool:pre", {"tool_name": "bash"})
    assert result.action == "CONTINUE"


# --- Test 5: with script, exit code 2 -> DENY with reason ---
@pytest.mark.asyncio
async def test_with_script_exit_2_denies(tmp_path: Path):
    script = tmp_path / "pre-tool"
    script.write_text("#!/bin/sh\necho 'Access denied'\nexit 2\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    bridge = ShellHookBridge(hooks_dir=tmp_path)
    result = await bridge.handle("tool:pre", {"tool_name": "bash"})
    assert result.action == "DENY"
    assert result.reason is not None
    assert len(result.reason) > 0
