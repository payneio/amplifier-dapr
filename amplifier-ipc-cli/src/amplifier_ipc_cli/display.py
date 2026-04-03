"""Streaming display for SSE events using Rich console."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.errors import MarkupError
from rich.panel import Panel
from rich.text import Text

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

_TODO_BAR_WIDTH = 20
_TODO_FULL_MODE_THRESHOLD = 7
_TODO_PANEL_MAX_WIDTH = 60

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
        """Render a Rich Panel with color-coded todo items (<=7) or summary (>7) plus progress bar."""
        if not isinstance(data, dict):
            return
        todos: list[dict[str, Any]] = data.get("todos", [])
        if not todos:
            return

        total = len(todos)
        completed_count = sum(1 for t in todos if t.get("status") == "completed")
        in_progress_count = sum(1 for t in todos if t.get("status") == "in_progress")
        pending_count = sum(1 for t in todos if t.get("status") == "pending")

        panel_width = min(self._console.width, _TODO_PANEL_MAX_WIDTH)

        content = Text()

        if total <= _TODO_FULL_MODE_THRESHOLD:
            # Full mode: one line per item with color-coded symbol
            for i, todo in enumerate(todos):
                status = todo.get("status", "pending")
                text_content = str(todo.get("content", ""))
                if i > 0:
                    content.append("\n")
                if status == "completed":
                    content.append("\u2713", style="green")  # ✓
                    content.append(" ")
                    content.append(text_content, style="dim strike")
                elif status == "in_progress":
                    content.append("\u2192", style="bold cyan")  # →
                    content.append(" ")
                    content.append(text_content, style="bold")
                else:
                    content.append("\u25cb", style="dim")  # ○
                    content.append(" ")
                    content.append(text_content, style="dim")
        else:
            # Condensed mode: summary count for each status
            content.append("\u2713", style="green")  # ✓
            content.append(f" {completed_count}  ", style="dim")
            content.append("\u2192", style="bold cyan")  # →
            content.append(f" {in_progress_count}  ", style="dim")
            content.append("\u25cb", style="dim")  # ○
            content.append(f" {pending_count}", style="dim")

        # Progress bar
        filled = int(_TODO_BAR_WIDTH * completed_count / total) if total > 0 else 0
        empty = _TODO_BAR_WIDTH - filled
        content.append("\n")
        content.append("\u2588" * filled, style="green")  # █ filled
        content.append("\u2591" * empty, style="dim")  # ░ empty
        content.append(f" {completed_count}/{total}", style="dim")

        self._console.print(Panel(content, border_style="dim", width=panel_width))

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
