"""Tests for StreamingDisplay - SSE Event Renderer using Rich console."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from amplifier_cli.client import SSEEvent
from amplifier_cli.display import StreamingDisplay


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_console(width: int = 10_000) -> tuple[Console, StringIO]:
    """Create a Rich console that captures output in a StringIO buffer.

    Uses a very wide width (10 000) by default so Rich never wraps long strings,
    making substring assertions on raw content reliable. Pass a smaller ``width``
    to simulate a narrow terminal.
    """
    buf: StringIO = StringIO()
    console = Console(
        file=buf,
        force_terminal=False,
        markup=True,
        highlight=False,
        width=width,
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
        event = SSEEvent(event="thinking", data={"thinking": "I think carefully..."})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "I think carefully..." in output

    def test_handle_thinking_hidden_when_disabled(self) -> None:
        """_handle_thinking skips output when show_thinking=False."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=False)
        event = SSEEvent(event="thinking", data={"thinking": "hidden thought"})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "hidden thought" not in output

    def test_handle_tool_call_event(self) -> None:
        """_handle_tool_call prints tool name and argument key/value pairs."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_call",
            data={"tool_name": "bash", "arguments": {"command": "echo hello"}},
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
            data={"tool_name": "write_file", "arguments": {"content": long_value}},
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
            event="tool_call", data={"tool_name": "multi_arg", "arguments": args}
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
            data={"tool_name": "bash", "success": True, "output": "hello from bash"},
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
                "tool_name": "bash",
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
            data={"tool_name": "bash", "success": True, "output": "\n".join(lines)},
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
        """_handle_error prints a red error message (orchestrator 'error' field)."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(event="error", data={"error": "something went wrong"})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "something went wrong" in output

    def test_handle_error_event_structured_error_dict(self) -> None:
        """_handle_error handles structured error dicts with 'type' and 'msg' keys."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="error",
            data={"error": {"type": "ToolExecutionError", "msg": "bash failed"}},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "bash failed" in output

    def test_handle_error_event_session_service_compat(self) -> None:
        """_handle_error accepts legacy session-service {'message': ...} format."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(event="error", data={"message": "session service error"})
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "session service error" in output

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
    # Tests for foundation hooks-todo-display format
    # ------------------------------------------------------------------

    def test_handle_todo_update_full_mode_colored_symbols(self) -> None:
        """Full mode (<=7 items) shows ✓, ▶ and ○ symbols for each status."""
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
        assert "▶" in output  # in_progress play symbol (upstream format)
        assert "○" in output  # pending circle symbol
        assert "→" not in output  # old arrow must be gone

    def test_handle_todo_update_condensed_mode_shows_bar_and_current_task(self) -> None:
        """Condensed mode (>7 items) shows progress bar and current in-progress task."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        todos = [
            {
                "content": f"task {i}",
                "activeForm": f"Working on task {i}",
                "status": "pending",
            }
            for i in range(8)
        ]
        todos[0]["status"] = "completed"
        todos[1]["status"] = "in_progress"
        event = SSEEvent(event="todo_update", data={"todos": todos})
        display.handle_sse_event(event)
        output = buf.getvalue()
        # Should show progress count
        assert "1/8" in output
        # Should show ▶ symbol and activeForm of in-progress item
        assert "▶" in output
        assert "Working on task 1" in output
        # Individual task names beyond the in-progress one should NOT appear
        assert "task 7" not in output
        assert "→" not in output  # old arrow must be gone

    def test_full_mode_title_in_border(self) -> None:
        """Full mode box has 'Todo' title embedded in the top border line."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="todo_update",
            data={
                "todos": [
                    {
                        "content": "Set up environment",
                        "activeForm": "Setting up environment",
                        "status": "completed",
                    },
                    {
                        "content": "Run tests",
                        "activeForm": "Running tests",
                        "status": "in_progress",
                    },
                    {
                        "content": "Build project",
                        "activeForm": "Building project",
                        "status": "pending",
                    },
                ]
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # "Todo" must appear in the top-border line (title-in-border style)
        assert "Todo" in output
        # Box-drawing corners must be present
        assert "┌" in output
        assert "└" in output

    def test_full_mode_active_form_for_in_progress(self) -> None:
        """Full mode shows activeForm for in_progress items, NOT content."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="todo_update",
            data={
                "todos": [
                    {
                        "content": "do the work",
                        "activeForm": "doing the work now",
                        "status": "in_progress",
                    },
                    {
                        "content": "finish up",
                        "activeForm": "finishing up",
                        "status": "pending",
                    },
                ]
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # activeForm must appear for in_progress
        assert "doing the work now" in output
        # content must NOT appear for in_progress ("do the work" ≠ prefix of "doing the work now")
        assert "do the work" not in output
        # pending still shows its content text
        assert "finish up" in output

    def test_all_completed_shows_complete_text(self) -> None:
        """All-complete state shows a fully filled bar and '✓ Complete' text."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="todo_update",
            data={
                "todos": [
                    {
                        "content": "task one",
                        "activeForm": "Doing task one",
                        "status": "completed",
                    },
                    {
                        "content": "task two",
                        "activeForm": "Doing task two",
                        "status": "completed",
                    },
                    {
                        "content": "task three",
                        "activeForm": "Doing task three",
                        "status": "completed",
                    },
                ]
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "3/3" in output
        assert "Complete" in output  # "✓ Complete" suffix
        assert "░" not in output  # no empty bar segments when fully done

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
        assert "\u2588" in output  # at least one filled segment
        assert "\u2591" in output  # at least one empty segment

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

    def test_todo_line_clips_long_content(self) -> None:
        """Long task names are clipped to fit within the box width.

        Without clipping, Rich wraps the oversized Text and produces a
        ``│``-starting fragment shorter than box_width (e.g. 38 chars for
        width=40).  After clipping the inner text in ``_todo_line``, every
        ``│``-bordered line must be exactly box_width characters.
        """
        console, buf = make_console(width=40)
        display = StreamingDisplay(console)
        todos = [
            {
                "content": "This is an extremely long task name that should be clipped",
                "status": "in_progress",
                "activeForm": "Working on an extremely long task name that should be clipped",
            }
        ]
        event = SSEEvent(event="todo_update", data={"todos": todos})
        display.handle_sse_event(event)
        output = buf.getvalue()
        # Every line that starts with │ must be exactly box_width (40) chars.
        # A wrapped (unclipped) line would be shorter (e.g. 38), failing here.
        for line in output.splitlines():
            if line.startswith("│"):
                assert len(line) == 40, f"Expected 40 chars, got {len(line)}: {line!r}"

    def test_complete_with_usage_shows_token_counts(self) -> None:
        """_handle_complete with usage data prints token counts."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="complete",
            data={
                "result": "The answer",
                "usage": {"input_tokens": 150, "output_tokens": 42},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "150" in output, f"Expected '150' in output, got: {output!r}"
        assert "42" in output, f"Expected '42' in output, got: {output!r}"

    def test_complete_without_usage_no_token_display(self) -> None:
        """_handle_complete without usage data does not print 'tokens'."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="complete",
            data={"result": "The answer"},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "tokens" not in output.lower(), (
            f"Expected no 'tokens' in output, got: {output!r}"
        )


# ---------------------------------------------------------------------------
# Tests for colon-separated content block event names
# ---------------------------------------------------------------------------


class TestContentBlockEvents:
    """Colon-separated event names dispatch correctly and render expected output."""

    def test_colon_events_dispatch_correctly(self) -> None:
        """content_block:start (colon) dispatches to _handle_content_block_start."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=True)
        # Simulate event with colon in name (as it arrives after stream. prefix strip)
        event = SSEEvent(
            event="content_block:start", data={"block_type": "thinking", "index": 0}
        )
        # Should not raise; should call _handle_content_block_start
        display.handle_sse_event(event)
        output = buf.getvalue()
        # Thinking block should print the border header
        assert "Thinking" in output, (
            f"Expected 'Thinking' header from content_block:start, got: {output!r}"
        )

    def test_thinking_delta_displays_text(self) -> None:
        """thinking:delta prints the delta text in dim style."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=True)
        event = SSEEvent(
            event="thinking:delta",
            data={"index": 0, "delta": "I reason about this..."},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "I reason about this..." in output, (
            f"Expected delta text in output, got: {output!r}"
        )

    def test_thinking_delta_hidden_when_disabled(self) -> None:
        """thinking:delta skips output when show_thinking=False."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=False)
        event = SSEEvent(
            event="thinking:delta",
            data={"index": 0, "delta": "secret thought"},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "secret thought" not in output, (
            f"Expected no output when show_thinking=False, got: {output!r}"
        )

    def test_content_block_delta_displays_text(self) -> None:
        """content_block:delta prints the delta text for text block_type."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="content_block:delta",
            data={"index": 1, "block_type": "text", "delta": "Hello from delta"},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "Hello from delta" in output, (
            f"Expected delta text in output, got: {output!r}"
        )

    def test_content_block_end_closes_thinking_border(self) -> None:
        """content_block:end with block_type thinking closes the border."""
        console, buf = make_console()
        display = StreamingDisplay(console, show_thinking=True)
        # First open the thinking block
        display.handle_sse_event(
            SSEEvent(
                event="content_block:start", data={"block_type": "thinking", "index": 0}
            )
        )
        buf.truncate(0)
        buf.seek(0)
        # Now close it
        display.handle_sse_event(
            SSEEvent(
                event="content_block:end", data={"block_type": "thinking", "index": 0}
            )
        )
        output = buf.getvalue()
        # Bottom border character should appear
        assert "\u255a" in output, (
            f"Expected bottom-border \\u255a in output, got: {output!r}"
        )


# ---------------------------------------------------------------------------
# Tests for delegate:* event handlers (task-6a)
# ---------------------------------------------------------------------------


class TestDelegateEventHandlers:
    """Tests for the delegate:agent_spawned / delegate:agent_completed handlers."""

    def test_delegate_agent_spawned_prints_wrench_icon(self) -> None:
        """delegate:agent_spawned event prints 🔧 icon."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_spawned", data={"name": "my-agent", "depth": 1}
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\U0001f527" in output, (
            f"Expected 🔧 icon in output for delegate:agent_spawned, got: {output!r}"
        )

    def test_delegate_agent_spawned_prints_agent_name(self) -> None:
        """delegate:agent_spawned event prints the agent name."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_spawned", data={"name": "explorer-agent", "depth": 1}
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "explorer-agent" in output, (
            f"Expected agent name in output, got: {output!r}"
        )

    def test_delegate_agent_spawned_indented_by_depth(self) -> None:
        """delegate:agent_spawned event indents by (depth - 1) levels."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_spawned", data={"name": "deep-agent", "depth": 2}
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # depth=2 means (2-1)=1 level of indent (4 spaces)
        assert "    " in output, (
            f"Expected indentation (4 spaces) at depth=2, got: {output!r}"
        )

    def test_delegate_agent_spawned_no_indent_at_depth_one(self) -> None:
        """delegate:agent_spawned at depth=1 has no leading indentation."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_spawned", data={"name": "top-level", "depth": 1}
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # At depth=1 the line should start with 🔧, not indented spaces
        first_line = output.splitlines()[0] if output.splitlines() else ""
        assert not first_line.startswith("    "), (
            f"Expected no leading indent at depth=1, got: {first_line!r}"
        )

    def test_delegate_agent_completed_success_shows_checkmark(self) -> None:
        """delegate:agent_completed with success=True prints ✅."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_completed",
            data={"name": "my-agent", "success": True},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2705" in output, (
            f"Expected ✅ in output for successful delegate:agent_completed, got: {output!r}"
        )

    def test_delegate_agent_completed_failure_shows_cross(self) -> None:
        """delegate:agent_completed with success=False prints ❌."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_completed",
            data={"name": "my-agent", "success": False},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u274c" in output, (
            f"Expected ❌ in output for failed delegate:agent_completed, got: {output!r}"
        )


# ---------------------------------------------------------------------------
# Tests for delegate:* forwarded child events (task-6e)
# ---------------------------------------------------------------------------


class TestDelegationEvents:
    """Tests for delegate:agent_spawned / agent_completed / agent_resumed / error handlers.

    These tests use the ``agent`` field (the canonical field name for forwarded
    child events) rather than the legacy ``name`` field.
    """

    def test_delegate_agent_spawned_shows_agent_name(self) -> None:
        """delegate:agent_spawned with {agent, instruction, depth} shows agent name and 'delegate'."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_spawned",
            data={
                "agent": "foundation:explorer",
                "instruction": "explore the code",
                "depth": 1,
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "foundation:explorer" in output, (
            f"Expected agent name 'foundation:explorer' in output, got: {output!r}"
        )
        assert "delegate" in output, f"Expected 'delegate' in output, got: {output!r}"

    def test_delegate_agent_completed_shows_success(self) -> None:
        """delegate:agent_completed with success=True shows agent name and ✅."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_completed",
            data={"agent": "foundation:explorer", "success": True},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "foundation:explorer" in output, (
            f"Expected agent name in output, got: {output!r}"
        )
        assert "\u2705" in output, (
            f"Expected ✅ in output for success=True, got: {output!r}"
        )

    def test_delegate_agent_completed_failure_shows_cross(self) -> None:
        """delegate:agent_completed with success=False shows ❌."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_completed",
            data={"agent": "foundation:explorer", "success": False},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u274c" in output, (
            f"Expected ❌ in output for success=False, got: {output!r}"
        )

    def test_delegate_error_shows_error(self) -> None:
        """delegate:error with {error, agent} shows the error text."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:error",
            data={
                "error": "delegation failed: timeout",
                "agent": "foundation:explorer",
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "delegation failed: timeout" in output, (
            f"Expected error text in output, got: {output!r}"
        )

    def test_delegate_agent_resumed_shows_resumption_header(self) -> None:
        """delegate:agent_resumed with {agent, session_id} shows 🔄 and agent name."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="delegate:agent_resumed",
            data={"agent": "foundation:explorer", "session_id": "abc-123"},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\U0001f504" in output, (
            f"Expected 🔄 icon in output for delegate:agent_resumed, got: {output!r}"
        )
        assert "foundation:explorer" in output, (
            f"Expected agent name in output, got: {output!r}"
        )
