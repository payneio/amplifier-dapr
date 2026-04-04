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
        """_handle_tool_call for bash shows '$ command' one-liner."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_call",
            data={"tool_name": "bash", "arguments": {"command": "echo hello"}},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "$ echo hello" in output

    def test_handle_tool_call_truncates_long_values(self) -> None:
        """_handle_tool_call for bash truncates command to ~120 chars."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        long_command = "x" * 200
        event = SSEEvent(
            event="tool_call",
            data={"tool_name": "bash", "arguments": {"command": long_command}},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # Should contain 120 chars of the command but not 121
        assert "x" * 120 in output
        assert "x" * 121 not in output

    def test_handle_tool_call_limits_arg_count(self) -> None:
        """_handle_tool_call suppresses all args for unknown tool names."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        args = {f"arg{i}": f"value{i}" for i in range(12)}
        event = SSEEvent(
            event="tool_call", data={"tool_name": "unknown_tool", "arguments": args}
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # Other tools are suppressed — no arg values should appear
        assert "value0" not in output
        assert "value11" not in output

    def test_handle_tool_result_success(self) -> None:
        """_handle_tool_result prints ✅ and stdout for bash success."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "bash",
                "success": True,
                "output": {"stdout": "hello from bash", "stderr": ""},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2705" in output  # ✅ green checkmark
        assert "hello from bash" in output

    def test_handle_tool_result_failure(self) -> None:
        """_handle_tool_result prints \u2717 and stderr for bash failure."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "bash",
                "success": False,
                "output": {"stdout": "", "stderr": "error: command not found"},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2717" in output  # \u2717 ballot x
        assert "error: command not found" in output

    def test_handle_tool_result_truncates_output(self) -> None:
        """_handle_tool_result shows at most 3 lines of stdout for bash."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        # 5 lines of stdout; only first 3 should appear
        stdout_lines = [f"line{i}" for i in range(5)]
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "bash",
                "success": True,
                "output": {"stdout": "\n".join(stdout_lines), "stderr": ""},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # First 3 lines should appear
        assert "line0" in output
        assert "line1" in output
        assert "line2" in output
        # Lines 4 and 5 should NOT appear
        assert "line3" not in output
        assert "line4" not in output

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


# ---------------------------------------------------------------------------
# Tests for CLI display quality improvements (task: CLI Display Quality)
# ---------------------------------------------------------------------------


class TestToolDisplayQuality:
    """Tests for tool-specific display in _handle_tool_call and _handle_tool_result."""

    # -- _handle_tool_call_start --

    def test_handle_tool_call_start_shows_wrench_and_name(self) -> None:
        """_handle_tool_call_start prints 🔧 icon and the tool name."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_call_start",
            data={"tool_name": "edit_file"},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\U0001f527" in output  # 🔧
        assert "edit_file" in output

    # -- _handle_tool_call: tool-specific arg display --

    def test_handle_tool_call_bash_shows_dollar_prefix(self) -> None:
        """_handle_tool_call for bash shows '$ command' format."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_call",
            data={"tool_name": "bash", "arguments": {"command": "ls -la"}},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "$ ls -la" in output

    def test_handle_tool_call_bash_truncates_to_120_chars(self) -> None:
        """_handle_tool_call for bash truncates command at 120 chars."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        long_cmd = "find . " + "x" * 200
        event = SSEEvent(
            event="tool_call",
            data={"tool_name": "bash", "arguments": {"command": long_cmd}},
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # Truncated at 120 chars total command length
        assert long_cmd[:120] in output
        assert long_cmd[:121] not in output

    def test_handle_tool_call_read_file_shows_path(self) -> None:
        """_handle_tool_call for read_file shows the file path."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_call",
            data={
                "tool_name": "read_file",
                "arguments": {"file_path": "./docs/specs/amplifier-spec.md"},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "./docs/specs/amplifier-spec.md" in output

    def test_handle_tool_call_todo_shows_action_and_content(self) -> None:
        """_handle_tool_call for todo shows 'action: content' one-liner."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_call",
            data={
                "tool_name": "todo",
                "arguments": {
                    "action": "create",
                    "todos": [
                        {
                            "content": "Identify all spec files",
                            "status": "pending",
                            "activeForm": "Identifying spec files",
                        }
                    ],
                },
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "create" in output
        assert "Identify all spec files" in output

    def test_handle_tool_call_todo_no_todos_shows_action_only(self) -> None:
        """_handle_tool_call for todo with no todos list shows just action."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_call",
            data={
                "tool_name": "todo",
                "arguments": {"action": "list"},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "list" in output

    def test_handle_tool_call_other_tool_suppressed(self) -> None:
        """_handle_tool_call for tools other than bash/read_file/todo shows nothing."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_call",
            data={
                "tool_name": "edit_file",
                "arguments": {
                    "file_path": "src/foo.py",
                    "old_string": "x",
                    "new_string": "y",
                },
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        # No arg values should appear for other tools
        assert "old_string" not in output
        assert "new_string" not in output

    # -- _handle_tool_result: tool-specific output display --

    def test_handle_tool_result_bash_success_shows_stdout(self) -> None:
        """_handle_tool_result for bash success shows ✅ bash + stdout lines."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "bash",
                "success": True,
                "output": {"stdout": "line one\nline two", "stderr": ""},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2705" in output
        assert "bash" in output
        assert "line one" in output
        assert "line two" in output

    def test_handle_tool_result_bash_failure_shows_stderr(self) -> None:
        """_handle_tool_result for bash failure shows ✗ bash + stderr lines in red."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "bash",
                "success": False,
                "output": {"stdout": "", "stderr": "bash: command not found"},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2717" in output  # ✗ ballot x
        assert "bash: command not found" in output

    def test_handle_tool_result_bash_output_as_json_string(self) -> None:
        """_handle_tool_result parses output when it arrives as a JSON string."""
        import json as _json

        console, buf = make_console()
        display = StreamingDisplay(console)
        raw_output = _json.dumps({"stdout": "parsed stdout line", "stderr": ""})
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "bash",
                "success": True,
                "output": raw_output,
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "parsed stdout line" in output

    def test_handle_tool_result_bash_limits_stdout_to_3_lines(self) -> None:
        """_handle_tool_result for bash shows at most 3 stdout lines."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        stdout = "\n".join(f"line{i}" for i in range(6))
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "bash",
                "success": True,
                "output": {"stdout": stdout, "stderr": ""},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "line0" in output
        assert "line2" in output
        assert "line3" not in output
        assert "line5" not in output

    def test_handle_tool_result_read_file_success_shows_content(self) -> None:
        """_handle_tool_result for read_file success shows ✅ read_file + content."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "read_file",
                "success": True,
                "output": {"content": "# My File\n## Section One\nSome text"},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2705" in output
        assert "read_file" in output
        assert "# My File" in output

    def test_handle_tool_result_read_file_failure_shows_error(self) -> None:
        """_handle_tool_result for read_file failure shows ✗ read_file + error."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "read_file",
                "success": False,
                "output": {"error": "File not found: ./missing.md"},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2717" in output
        assert "read_file" in output
        assert "File not found" in output

    def test_handle_tool_result_todo_success_shows_created_summary(self) -> None:
        """_handle_tool_result for todo success shows 'created N items'."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "todo",
                "success": True,
                "output": {"status": "created", "count": 6},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2705" in output
        assert "todo" in output
        assert "created" in output
        assert "6" in output

    def test_handle_tool_result_todo_success_shows_updated_summary(self) -> None:
        """_handle_tool_result for todo success shows updated summary with counts."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "todo",
                "success": True,
                "output": {
                    "status": "updated",
                    "completed": 2,
                    "in_progress": 1,
                    "pending": 3,
                },
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2705" in output
        assert "2" in output  # completed count
        assert "1" in output  # in_progress count

    def test_handle_tool_result_todo_failure_shows_error(self) -> None:
        """_handle_tool_result for todo failure shows ✗ todo: error message."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "todo",
                "success": False,
                "output": {"error": "invalid action"},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2717" in output
        assert "todo" in output
        assert "invalid action" in output

    def test_handle_tool_result_other_tool_success_shows_name_only(self) -> None:
        """_handle_tool_result for unknown tools on success shows just ✅ name."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "edit_file",
                "success": True,
                "output": {"result": "replaced 3 occurrences"},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2705" in output
        assert "edit_file" in output
        # Result body should NOT appear for other tools
        assert "replaced 3 occurrences" not in output

    def test_handle_tool_result_other_tool_failure_shows_error(self) -> None:
        """_handle_tool_result for unknown tools on failure shows ✗ name: error."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "glob",
                "success": False,
                "output": {"error": "permission denied"},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2717" in output
        assert "glob" in output
        assert "permission denied" in output

    def test_handle_tool_result_other_tool_failure_fallback_message(self) -> None:
        """_handle_tool_result falls back to 'failed' when no error field exists."""
        console, buf = make_console()
        display = StreamingDisplay(console)
        event = SSEEvent(
            event="tool_result",
            data={
                "tool_name": "some_tool",
                "success": False,
                "output": {},
            },
        )
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "\u2717" in output
        assert "some_tool" in output
        assert "failed" in output

    # -- _handle_todo_update: defensive JSON parse --

    def test_handle_todo_update_handles_json_string_data(self) -> None:
        """_handle_todo_update parses data when it arrives as a JSON string."""
        import json as _json

        console, buf = make_console()
        display = StreamingDisplay(console)
        data_as_string = _json.dumps(
            {
                "todos": [
                    {"content": "task alpha", "status": "completed"},
                    {"content": "task beta", "status": "in_progress"},
                ]
            }
        )
        event = SSEEvent(event="todo_update", data=data_as_string)
        display.handle_sse_event(event)
        output = buf.getvalue()
        assert "task alpha" in output
        assert "task beta" in output
