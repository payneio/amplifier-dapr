"""Streaming display for SSE events using Rich console."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.errors import MarkupError

if TYPE_CHECKING:
    from rich.console import Console

from amplifier_ipc_cli.client import SSEEvent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TOOL_ARG_VALUE_LEN = 200
_DEFAULT_TOOL_ARGS_COUNT = 10
_DEFAULT_TOOL_RESULT_LINES = 10
_DEFAULT_TOOL_RESULT_LINE_LEN = 200

# Indentation applied per child-session nesting level.
_NESTING_INDENT = "    "  # 4 spaces


# ---------------------------------------------------------------------------
# StreamingDisplay
# ---------------------------------------------------------------------------


class StreamingDisplay:
    """Renders streaming SSE events to a Rich console.

    Dispatches each SSEEvent to a ``_handle_<event_type>`` method.
    Unknown event types are silently ignored.
    """

    def __init__(self, console: Console, show_thinking: bool = True) -> None:
        self._console = console
        self._show_thinking = show_thinking
        self._response: str | None = None
        self._tokens_received: bool = False
        self._saw_tool_call_start: bool = False
        self._in_thinking_block: bool = False

    @property
    def response(self) -> str | None:
        """Return the final response text, or None if not yet complete."""
        return self._response

    def handle_sse_event(self, event: SSEEvent) -> None:
        """Dispatch an SSE event to the appropriate ``_handle_*`` method.

        Unknown event types are silently ignored.
        """
        handler = getattr(self, f"_handle_{event.event}", None)
        if handler is not None:
            handler(event.data)

    # Async variant for use with ``async with`` / ``await`` in the REPL.
    async def handle_event(self, event: SSEEvent) -> None:
        """Async wrapper around :meth:`handle_sse_event`."""
        self.handle_sse_event(event)

    # ------------------------------------------------------------------
    # Async context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> StreamingDisplay:
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    # ------------------------------------------------------------------
    # Safe print helper
    # ------------------------------------------------------------------

    def _safe_print(self, *args: Any, **kwargs: Any) -> None:
        """Print to console, retrying with markup=False on MarkupError."""
        try:
            self._console.print(*args, **kwargs)
        except MarkupError:
            kwargs["markup"] = False
            self._console.print(*args, **kwargs)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_token(self, data: Any) -> None:
        """Print token text without markup or syntax highlighting."""
        text = data.get("text", "") if isinstance(data, dict) else str(data)
        if text:
            self._tokens_received = True
            self._console.print(text, end="", highlight=False, markup=False)

    def _handle_thinking(self, data: Any) -> None:
        """Print thinking text inline in 'cyan dim' style (skipped when show_thinking=False)."""
        if not self._show_thinking:
            return
        text = data.get("text", "") if isinstance(data, dict) else str(data)
        self._console.print(text, end="", style="cyan dim", markup=False)

    def _handle_content_block_start(self, data: Any) -> None:
        """Print thinking block header with unicode double-line border."""
        block_type = data.get("type", "") if isinstance(data, dict) else ""
        if block_type != "thinking" or not self._show_thinking:
            return
        self._in_thinking_block = True
        border = "\u2554" + "\u2550" * 50 + "\u2557"  # ╔══...══╗
        self._console.print("\U0001f9e0 Thinking...", style="dim", markup=False)
        self._console.print(border, style="dim", markup=False)

    def _handle_content_block_end(self, data: Any) -> None:
        """Print closing double-line border for thinking blocks."""
        block_type = data.get("type", "") if isinstance(data, dict) else ""
        if block_type != "thinking" or not self._in_thinking_block:
            return
        self._in_thinking_block = False
        border = "\u255a" + "\u2550" * 50 + "\u255d"  # ╚══...══╝
        self._console.print("\n" + border, style="dim", markup=False)

    def _handle_tool_call_start(self, data: Any) -> None:
        """Print tool name dimly to signal the start of a tool call."""
        name = data.get("name", "") if isinstance(data, dict) else str(data)
        self._safe_print(f"\n[dim]\U0001f527 {name}[/dim]")
        self._saw_tool_call_start = True

    def _handle_tool_call(self, data: Any) -> None:
        """Print tool name bold followed by up to 10 truncated argument values.

        If a preceding tool_call_start event already printed the tool name,
        the header is skipped to avoid duplication.
        """
        if not isinstance(data, dict):
            return
        name = data.get("name", "")
        arguments = data.get("arguments", {})

        if not self._saw_tool_call_start:
            # No start event preceded this — show the tool name header.
            self._safe_print(f"\n\U0001f527 [bold]{name}[/bold]")
        self._saw_tool_call_start = False

        if isinstance(arguments, dict):
            items = list(arguments.items())
            display_items = items[:_DEFAULT_TOOL_ARGS_COUNT]
            remaining = len(items) - len(display_items)
            for key, value in display_items:
                truncated = str(value)[:_DEFAULT_TOOL_ARG_VALUE_LEN]
                self._safe_print(
                    f"   [dim]{key}:[/dim] {truncated}",
                    markup=True,
                    highlight=False,
                )
            if remaining > 0:
                self._safe_print(f"   [dim]... ({remaining} more)[/dim]")

    def _handle_tool_result(self, data: Any) -> None:
        """Print success (✅) or failure (❌), then truncated output."""
        if not isinstance(data, dict):
            return
        success = data.get("success", True)
        output = data.get("output", "")
        name = data.get("name", "")

        if success:
            icon = "\u2705"  # ✅
            style = "green"
        else:
            icon = "\u274c"  # ❌
            style = "red"
        self._console.print(f"  {icon} {name}", style=style, markup=False)

        if output:
            lines = str(output).splitlines()
            display_lines = lines[:_DEFAULT_TOOL_RESULT_LINES]
            remaining = len(lines) - len(display_lines)
            for line in display_lines:
                self._console.print(
                    f"   {line[:_DEFAULT_TOOL_RESULT_LINE_LEN]}",
                    style="dim",
                    markup=False,
                    highlight=False,
                )
            if remaining > 0:
                self._console.print(
                    f"   ... ({remaining} more lines)",
                    style="dim",
                    markup=False,
                    highlight=False,
                )

    def _handle_todo_update(self, data: Any) -> None:
        """Render a todo box with individual items (<=7) or a summary (>7) plus progress bar."""
        if not isinstance(data, dict):
            return
        todos: list[dict[str, Any]] = data.get("todos", [])
        if not todos:
            return

        # Status symbols
        symbols: dict[str, str] = {
            "completed": "\u2713",    # ✓ checkmark
            "in_progress": "\u25b6",  # ▶ play
            "pending": "\u25cb",      # ○ circle
        }

        total = len(todos)
        completed_count = sum(1 for t in todos if t.get("status") == "completed")

        # Layout constants
        box_width = 50   # Inner content width (chars between │ borders)
        bar_width = 20   # Width of the progress bar in block chars
        full_mode_threshold = 7

        top_border = "\u250c" + "\u2500" * box_width + "\u2510"     # ┌──...──┐
        bottom_border = "\u2514" + "\u2500" * box_width + "\u2518"  # └──...──┘

        self._console.print(top_border, markup=False)

        if total <= full_mode_threshold:
            # Full mode: show each todo item in a bordered row
            for todo in todos:
                status = todo.get("status", "pending")
                symbol = symbols.get(status, " ")
                content = str(todo.get("content", ""))
                # inner_width accounts for "│ " (2) + symbol (1) + " " (1) = 4 chars overhead
                inner_width = box_width - 4
                if len(content) > inner_width - 3:
                    content = content[: inner_width - 3] + "..."
                line = f"\u2502 {symbol} {content}"
                padding = box_width - len(f" {symbol} {content}")
                if padding > 0:
                    line += " " * padding
                line += "\u2502"
                self._console.print(line, markup=False)
        else:
            # Condensed mode: show symbol counts
            in_progress_count = sum(
                1 for t in todos if t.get("status") == "in_progress"
            )
            pending_count = sum(1 for t in todos if t.get("status") == "pending")
            summary = (
                f"\u2502 {symbols['completed']} {completed_count} completed  "
                f"{symbols['in_progress']} {in_progress_count} in progress  "
                f"{symbols['pending']} {pending_count} pending"
            )
            # summary starts with "│" (1 char border) then inner content;
            # subtract 1 to get inner content length, then pad to box_width.
            padding = box_width - (len(summary) - 1)
            if padding > 0:
                summary += " " * padding
            summary += "\u2502"
            self._console.print(summary, markup=False)

        # Progress bar inside a bordered row
        filled = int(bar_width * completed_count / total) if total > 0 else 0
        empty = bar_width - filled
        bar = "\u2588" * filled + "\u2591" * empty
        progress_text = f"{completed_count}/{total}"
        progress_line = f"\u2502 {bar} {progress_text}"
        padding = box_width - len(f" {bar} {progress_text}")
        if padding > 0:
            progress_line += " " * padding
        progress_line += "\u2502"
        self._console.print(progress_line, markup=False)

        self._console.print(bottom_border, markup=False)

    def _handle_child_session_start(self, data: Any) -> None:
        """Print a 🔧 delegation header indented according to session depth."""
        if not isinstance(data, dict):
            return
        depth = data.get("depth", 0)
        name = data.get("name", "sub-agent")
        indent = _NESTING_INDENT * (depth - 1) if depth > 0 else ""
        self._safe_print(
            f"{indent}\U0001f527 delegate -> [bold cyan]{name}[/bold cyan]"
        )

    def _handle_child_session_event(self, data: Any) -> None:
        """Recursively render a nested child session event.

        If the payload contains an inner ``event`` and ``data`` pair the event
        is dispatched back through :meth:`handle_sse_event` so every inner
        event type is rendered with the same handlers.
        """
        if not isinstance(data, dict):
            return
        inner_event = data.get("event")
        inner_data = data.get("data")
        if inner_event is None:
            return
        nested = SSEEvent(event=inner_event, data=inner_data)
        self.handle_sse_event(nested)

    def _handle_child_session_end(self, data: Any) -> None:
        """No-op: child session end is handled silently."""

    def _handle_error(self, data: Any) -> None:
        """Print a red error message with ✗ icon."""
        message = (
            data.get("message", str(data)) if isinstance(data, dict) else str(data)
        )
        self._console.print(f"  \u2717 {message}", style="red", markup=False)

    def _handle_complete(self, data: Any) -> None:
        """Store the final response text. Print only if no tokens were streamed."""
        if isinstance(data, dict):
            self._response = data.get("result", "") or data.get("response", "")
        # Only print the response if no token events were received
        # (avoids duplication when tokens already printed the text)
        if self._response and not self._tokens_received:
            self._console.print(self._response, highlight=False, markup=False)
        self._console.print()
