"""Tests for LoggingHook."""

from __future__ import annotations

import json

import pytest

from svc_hooks_async.logging_hook import LoggingHook


# --- Test 1: handle writes JSONL file ---
@pytest.mark.asyncio
async def test_handle_writes_jsonl_file(tmp_path):
    """handle() should write a JSONL record to the log file for a known session."""
    log_file = tmp_path / "{session_id}" / "events.jsonl"
    template = str(log_file)
    hook = LoggingHook(log_template=template)

    result = await hook.handle(
        "tool:post", {"session_id": "test-session-123", "tool": "bash"}
    )

    assert result.action == "CONTINUE"
    written_file = tmp_path / "test-session-123" / "events.jsonl"
    assert written_file.exists(), "JSONL log file should have been created"
    lines = written_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "tool:post"
    assert "timestamp" in record
    assert "data" in record


# --- Test 2: handle without session_id skips write ---
@pytest.mark.asyncio
async def test_handle_without_session_id_skips(tmp_path):
    """handle() without session_id should return CONTINUE and not write any file."""
    log_file = tmp_path / "{session_id}" / "events.jsonl"
    template = str(log_file)
    hook = LoggingHook(log_template=template)

    result = await hook.handle("tool:post", {"tool": "bash"})

    assert result.action == "CONTINUE"
    # No files should have been created in tmp_path
    created = list(tmp_path.iterdir())
    assert len(created) == 0, "No files should be created when session_id is missing"


# --- Test 3: handle returns CONTINUE ---
@pytest.mark.asyncio
async def test_handle_returns_continue(tmp_path):
    """handle() should always return CONTINUE regardless of event type."""
    log_file = tmp_path / "{session_id}" / "events.jsonl"
    template = str(log_file)
    hook = LoggingHook(log_template=template)

    result = await hook.handle("session:start", {"session_id": "sess-abc"})
    assert result.action == "CONTINUE"

    result2 = await hook.handle(
        "provider:error", {"session_id": "sess-abc", "error": "timeout"}
    )
    assert result2.action == "CONTINUE"


# --- Test 4: disabled hook skips write ---
@pytest.mark.asyncio
async def test_disabled_hook_skips_write(tmp_path):
    """When enabled=False, handle() should return CONTINUE and not write any file."""
    log_file = tmp_path / "{session_id}" / "events.jsonl"
    template = str(log_file)
    hook = LoggingHook(log_template=template)
    hook.enabled = False

    result = await hook.handle(
        "tool:post", {"session_id": "test-session-disabled", "tool": "bash"}
    )

    assert result.action == "CONTINUE"
    # No files should have been created
    created = list(tmp_path.iterdir())
    assert len(created) == 0, "No files should be created when hook is disabled"
