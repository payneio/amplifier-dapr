"""Streaming display for SSE events using Rich console."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_token(self, data: Any) -> None:
        """Print token text without markup or syntax highlighting."""
        text = data.get("text", "") if isinstance(data, dict) else str(data)
        if text:
            self._tokens_received = True
            self._console.print(text, end="", highlight=False, markup=False)

    def _handle_thinking(self, data: Any) -> None:
        """Print thinking text in 'cyan dim' style (skipped when show_thinking=False)."""
        if not self._show_thinking:
            return
        text = data.get("text", "") if isinstance(data, dict) else str(data)
        self._console.print(text, style="cyan dim")

    def _handle_content_block_start(self, data: Any) -> None:
        """Print thinking block header with unicode border."""
        self._console.print(
            "╭─ Thinking ─────────────────────────────────╮",
            style="cyan dim",
        )

    def _handle_content_block_end(self, data: Any) -> None:
        """Print thinking block footer with unicode border."""
        self._console.print(
            "╰────────────────────────────────────────────╯",
            style="cyan dim",
        )

    def _handle_tool_call_start(self, data: Any) -> None:
        """Print tool name dimly to signal the start of a tool call."""
        name = data.get("name", "") if isinstance(data, dict) else str(data)
        self._console.print(f"⚙ {name}", style="dim")

    def _handle_tool_call(self, data: Any) -> None:
        """Print tool name bold followed by up to 10 truncated argument values."""
        if not isinstance(data, dict):
            return
        name = data.get("name", "")
        arguments = data.get("arguments", {})

        self._console.print(f"[bold]{name}[/bold]")

        if isinstance(arguments, dict):
            for count, (key, value) in enumerate(arguments.items()):
                if count >= _DEFAULT_TOOL_ARGS_COUNT:
                    break
                str_value = str(value)
                if len(str_value) > _DEFAULT_TOOL_ARG_VALUE_LEN:
                    str_value = str_value[:_DEFAULT_TOOL_ARG_VALUE_LEN] + "…"
                self._console.print(
                    f"  {key}: {str_value}", markup=False, highlight=False, no_wrap=True
                )

    def _handle_tool_result(self, data: Any) -> None:
        """Print success (green ✓) or failure (red ✗), then truncated output."""
        if not isinstance(data, dict):
            return
        success = data.get("success", True)
        output = data.get("output", "")
        name = data.get("name", "")

        if success:
            self._console.print(f"[green]✓[/green] {name}")
        else:
            self._console.print(f"[red]✗[/red] {name}")

        if output:
            lines = str(output).splitlines()
            for line in lines[:_DEFAULT_TOOL_RESULT_LINES]:
                if len(line) > _DEFAULT_TOOL_RESULT_LINE_LEN:
                    line = line[:_DEFAULT_TOOL_RESULT_LINE_LEN] + "…"
                self._console.print(f"  {line}", markup=False, highlight=False)

    def _handle_todo_update(self, data: Any) -> None:
        """Render a todo box with individual items (<=7) or a summary (>7) plus progress bar."""
        if not isinstance(data, dict):
            return
        todos: list[dict[str, Any]] = data.get("todos", [])
        total = len(todos)
        completed = sum(1 for t in todos if t.get("status") == "completed")

        self._console.print()
        self._console.print("┌─ Tasks ──────────────────────────────────┐")

        if total <= 7:
            for todo in todos:
                status = todo.get("status", "pending")
                content = todo.get("content", "")
                if status == "completed":
                    marker = "[green]✓[/green]"
                elif status == "in_progress":
                    marker = "[yellow]→[/yellow]"
                else:
                    marker = "○"
                self._console.print(f"  {marker} {content}")
        else:
            self._console.print(f"  {completed}/{total} tasks completed")
            in_progress = [t for t in todos if t.get("status") == "in_progress"]
            if in_progress:
                current = in_progress[0].get("content", "")
                self._console.print(f"  → {current}")

        # Progress bar
        if total > 0:
            bar_width = 30
            filled = int(bar_width * completed / total)
            bar = "█" * filled + "░" * (bar_width - filled)
            self._console.print(f"  [{bar}] {completed}/{total}", markup=False)

        self._console.print("└──────────────────────────────────────────┘")

    def _handle_child_session_start(self, data: Any) -> None:
        """Print a delegation header indented according to session depth."""
        if not isinstance(data, dict):
            return
        depth = data.get("depth", 0)
        name = data.get("name", "sub-agent")
        indent = "  " * depth
        self._console.print(f"{indent}┌─ Delegating to: {name}")

    def _handle_child_session_end(self, data: Any) -> None:
        """No-op: child session end is handled silently."""

    def _handle_error(self, data: Any) -> None:
        """Print a red error message."""
        message = (
            data.get("message", str(data)) if isinstance(data, dict) else str(data)
        )
        self._console.print(f"[red]Error: {message}[/red]")

    def _handle_complete(self, data: Any) -> None:
        """Store the final response text. Print only if no tokens were streamed."""
        if isinstance(data, dict):
            self._response = data.get("result", "") or data.get("response", "")
        # Only print the response if no token events were received
        # (avoids duplication when tokens already printed the text)
        if self._response and not self._tokens_received:
            self._console.print(self._response, highlight=False, markup=False)
        self._console.print()
