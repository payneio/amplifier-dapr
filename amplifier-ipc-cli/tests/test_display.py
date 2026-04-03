"""Tests for StreamingDisplay - SSE Event Renderer using Rich console."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from amplifier_ipc_cli.client import SSEEvent
from amplifier_ipc_cli.display import StreamingDisplay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_console() -> tuple[Console, StringIO]:
    """Create a Rich console that captures output in a StringIO buffer.

    Uses a very wide width (10 000) so Rich never wraps long strings, making
    substring assertions on raw content reliable.
    """
    buf: StringIO = StringIO()
    console = Console(
        file=buf,
        force_terminal=False,
        markup=True,
        highlight=False,
        width=10_000,
    )
    return console, buf


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStreamingDisplay:
    def test_handle_token_event(self) -> None:
        """_handle_token prints token text without markup or syntax highlighting."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(event="token", data={"text": "hello world"})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "hello world" in output

    def test_handle_thinking_event(self) -> None:
        """_handle_thinking prints thinking text (when show_thinking=True)."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=True)
        event = SSEEvent(event="thinking", data={"text": "I think carefully..."})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "I think carefully..." in output

    def test_handle_thinking_hidden_when_disabled(self) -> None:
        """_handle_thinking skips output when show_thinking=False."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=False)
        event = SSEEvent(event="thinking", data={"text": "hidden thought"})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "hidden thought" not in output

    def test_handle_tool_call_event(self) -> None:
        """_handle_tool_call prints tool name and argument key/value pairs."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_call",
            data={"name": "bash", "arguments": {"command": "echo hello"}},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "bash" in output
        assert "echo hello" in output

    def test_handle_tool_call_truncates_long_values(self) -> None:
        """_handle_tool_call truncates argument values longer than 200 chars."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        long_value = "x" * 300
        event = SSEEvent(
            event="tool_call",
            data={"name": "write_file", "arguments": {"content": long_value}},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # Should contain 200 chars of the value but not all 300
        assert "x" * 200 in output
        assert "x" * 300 not in output

    def test_handle_tool_call_limits_arg_count(self) -> None:
        """_handle_tool_call shows at most 10 arguments."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        # 12 arguments, only 10 should appear
        args = {f"arg{i}": f"value{i}" for i in range(12)}
        event = SSEEvent(
            event="tool_call", data={"name": "multi_arg", "arguments": args}
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # First 10 should appear
        for i in range(10):
            assert f"value{i}" in output
        # 11th and 12th should NOT appear
        assert "value10" not in output
        assert "value11" not in output

    def test_handle_tool_result_success(self) -> None:
        """_handle_tool_result prints green ✅ emoji for successful result."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={"name": "bash", "success": True, "output": "hello from bash"},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2705" in output  # ✅ green checkmark emoji
        assert "hello from bash" in output

    def test_handle_tool_result_failure(self) -> None:
        """_handle_tool_result prints red ❌ emoji for failed result."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "name": "bash",
                "success": False,
                "output": "error: command not found",
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u274c" in output  # ❌ red cross emoji
        assert "error: command not found" in output

    def test_handle_tool_result_truncates_output(self) -> None:
        """_handle_tool_result shows at most 10 lines, each at most 200 chars."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        # 12 lines, each with 250 chars
        lines = [f"line{i}: " + "a" * 242 for i in range(12)]
        event = SSEEvent(
            event="tool_result",
            data={"name": "bash", "success": True, "output": "\n".join(lines)},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # First 10 lines should appear
        assert "line0:" in output
        assert "line9:" in output
        # Line 11 and 12 should NOT appear
        assert "line10:" not in output
        assert "line11:" not in output

    def test_handle_complete_event(self) -> None:
        """_handle_complete stores final response and the response property returns it."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        assert display.response is None
        event = SSEEvent(event="complete", data={"response": "the final answer"})
        display.handle_sse_event(event)
        assert display.response == "the final answer"

    def test_handle_error_event(self) -> None:
        """_handle_error prints a red error message."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(event="error", data={"message": "something went wrong"})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "something went wrong" in output

    def test_handle_todo_update(self) -> None:
        """_handle_todo_update renders individual todo items when count <= 7."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="todo_update",
            data={
                "todos": [
                    {"content": "task one", "status": "completed"},
                    {"content": "task two", "status": "in_progress"},
                    {"content": "task three", "status": "pending"},
                ]
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "task one" in output
        assert "task two" in output
        assert "task three" in output

    def test_handle_todo_update_summary_for_many_items(self) -> None:
        """_handle_todo_update renders a summary when count > 7."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        todos = [{"content": f"task {i}", "status": "pending"} for i in range(8)]
        todos[0]["status"] = "completed"
        event = SSEEvent(event="todo_update", data={"todos": todos})
        display.handle_sse_event(event)
        output = buf.getvalue()
        # Should show summary (e.g., "1/8") rather than individual task names
        assert "1/8" in output
        # Individual tasks should NOT all appear by name
        # (we don't list all 8 individually)
        assert "task 7" not in output

    def test_unknown_event_ignored(self) -> None:
        """Unknown SSE events are silently ignored (no output, no error)."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="completely_unknown_event_xyz", data={"text": "some data"}
        )
        # Should not raise
        display.handle_sse_event(event)
        output = buf.getvalue()
        # Nothing should be printed for unknown events
        assert output == ""

    # ------------------------------------------------------------------
    # New tests for improved _handle_todo_update (Rich Panel + colors)
    # ------------------------------------------------------------------

    def test_handle_todo_update_full_mode_colored_symbols(self) -> None:
        """Full mode (<=7 items) shows ✓, → and ○ symbols for each status."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="todo_update",
            data={
                "todos": [
                    {"content": "task one", "status": "completed"},
                    {"content": "task two", "status": "in_progress"},
                    {"content": "task three", "status": "pending"},
                ]
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "✓" in output  # completed symbol
        assert "→" in output  # in_progress arrow symbol (not ▶)
        assert "○" in output  # pending circle symbol
        assert "▶" not in output  # old play symbol must be gone

    def test_handle_todo_update_condensed_mode_shows_status_counts(self) -> None:
        """Condensed mode (>7 items) shows symbol counts for each status."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        todos = [{"content": f"task {i}", "status": "pending"} for i in range(8)]
        todos[0]["status"] = "completed"
        todos[1]["status"] = "in_progress"
        event = SSEEvent(event="todo_update", data={"todos": todos})
        display.handle_sse_event(event)
        output = buf.getvalue()
        # All three status symbols should appear in condensed summary
        assert "✓" in output
        assert "→" in output  # new arrow (not ▶)
        assert "○" in output
        assert "▶" not in output  # old play symbol must be gone

    def test_handle_todo_update_progress_bar_counts(self) -> None:
        """Progress bar shows N/total format with correct completed count."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        todos = [{"content": f"done {i}", "status": "completed"} for i in range(3)] + [
            {"content": f"todo {i}", "status": "pending"} for i in range(5)
        ]
        event = SSEEvent(event="todo_update", data={"todos": todos})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "3/8" in output

    def test_handle_todo_update_empty_list_no_output(self) -> None:
        """Empty todos list produces no output at all."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(event="todo_update", data={"todos": []})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert output == ""

    def test_handle_todo_update_all_completed_no_empty_bar_segments(self) -> None:
        """When all todos are completed the progress bar has no empty (░) segments."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="todo_update",
            data={
                "todos": [
                    {"content": "task one", "status": "completed"},
                    {"content": "task two", "status": "completed"},
                    {"content": "task three", "status": "completed"},
                ]
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "3/3" in output
        assert "░" not in output  # no empty segments when fully complete
