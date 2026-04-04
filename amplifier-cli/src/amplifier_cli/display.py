"""Streaming display for SSE events using Rich console."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from rich.errors import MarkupError
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console

from amplifier_cli.client import SSEEvent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TODO_BAR_WIDTH = 24
_TODO_FULL_MODE_THRESHOLD = 7
_TODO_PANEL_MAX_WIDTH = 60

_TODO_STYLES: dict[str, str] = {
    "completed": "dim green",
    "in_progress": "bold cyan",
    "pending": "dim",
}

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

        Colons in event names are normalised to underscores so that names like
        ``content_block:start`` map to ``_handle_content_block_start``.
        Unknown event types are silently ignored.
        """
        safe_name = event.event.replace(":", "_")
        handler = getattr(self, f"_handle_{safe_name}", None)
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
        text = data.get("thinking", "") if isinstance(data, dict) else str(data)
        self._console.print(text, end="", style="cyan dim", markup=False)

    def _handle_content_block_start(self, data: Any) -> None:
        """Print thinking block header with unicode double-line border."""
        # Support both legacy ``type`` key and new ``block_type`` key.
        block_type = (
            data.get("block_type") or data.get("type", "")
            if isinstance(data, dict)
            else ""
        )
        if block_type != "thinking" or not self._show_thinking:
            return
        self._in_thinking_block = True
        border = "\u2554" + "\u2550" * 50 + "\u2557"  # ╔══...══╗
        self._console.print("\U0001f9e0 Thinking...", style="dim", markup=False)
        self._console.print(border, style="dim", markup=False)

    def _handle_content_block_end(self, data: Any) -> None:
        """Print closing double-line border for thinking blocks."""
        # Support both legacy ``type`` key and new ``block_type`` key.
        block_type = (
            data.get("block_type") or data.get("type", "")
            if isinstance(data, dict)
            else ""
        )
        if block_type != "thinking" or not self._in_thinking_block:
            return
        self._in_thinking_block = False
        border = "\u255a" + "\u2550" * 50 + "\u255d"  # ╚══...══╝
        self._console.print("\n" + border, style="dim", markup=False)

    def _handle_thinking_delta(self, data: Any) -> None:
        """Print thinking delta text in 'cyan dim' style (skipped when show_thinking=False)."""
        if not self._show_thinking:
            return
        text = data.get("delta", "") if isinstance(data, dict) else str(data)
        if text:
            self._console.print(text, end="", style="cyan dim", markup=False)

    def _handle_thinking_final(self, data: Any) -> None:
        """No-op: thinking:final marks end of thinking content, no display action needed."""

    def _handle_content_block_delta(self, data: Any) -> None:
        """Print delta text for text-type content blocks."""
        if not isinstance(data, dict):
            return
        block_type = data.get("block_type", "")
        if block_type != "text":
            return
        delta = data.get("delta", "")
        if delta:
            self._console.print(delta, end="", highlight=False, markup=False)

    def _handle_tool_call_start(self, data: Any) -> None:
        """Print tool name dimly to signal the start of a tool call."""
        name = data.get("tool_name", "") if isinstance(data, dict) else str(data)
        self._safe_print(f"\n[dim]\U0001f527 {name}[/dim]")
        self._saw_tool_call_start = True

    def _handle_tool_call(self, data: Any) -> None:
        """Print a tool-specific one-liner for bash/read_file/todo; suppress all others."""
        self._saw_tool_call_start = False
        if not isinstance(data, dict):
            return
        name = data.get("tool_name", "")
        arguments = data.get("arguments", {})
        if not isinstance(arguments, dict):
            return

        if name == "bash":
            command = str(arguments.get("command", ""))[:120]
            self._console.print(f"   $ {command}", markup=False, highlight=False)
        elif name == "read_file":
            file_path = str(arguments.get("file_path", ""))
            self._console.print(f"   {file_path}", markup=False, highlight=False)
        elif name == "todo":
            action = str(arguments.get("action", ""))
            todos = arguments.get("todos", [])
            first_content = ""
            if isinstance(todos, list) and todos:
                first_item = todos[0]
                if isinstance(first_item, dict):
                    first_content = str(first_item.get("content", ""))
            if first_content:
                truncated = first_content[:80]
                self._console.print(
                    f'   {action}: "{truncated}"', markup=False, highlight=False
                )
            else:
                self._console.print(f"   {action}", markup=False, highlight=False)
        # All other tools: no-op (suppress args entirely)

    def _handle_tool_result(self, data: Any) -> None:
        """Print tool-specific compact output on success, or clean error on failure."""
        if not isinstance(data, dict):
            return
        success = data.get("success", True)
        name = data.get("tool_name", "")
        raw_output = data.get("output")

        # Parse output if it arrives as a JSON string.
        output: Any = raw_output
        if isinstance(raw_output, str) and raw_output:
            try:
                output = json.loads(raw_output)
            except (json.JSONDecodeError, ValueError):
                output = raw_output

        if name == "bash":
            if success:
                self._console.print("\u2705 bash", markup=False)
                text = (
                    output.get("stdout", "")
                    if isinstance(output, dict)
                    else str(output or "")
                )
                self._print_indented_lines(text, max_lines=3, max_line_len=200)
            else:
                self._console.print("\u2717 bash", style="red", markup=False)
                text = (
                    output.get("stderr", "")
                    if isinstance(output, dict)
                    else str(output or "")
                )
                self._print_indented_lines(
                    text, max_lines=3, max_line_len=200, style="red"
                )

        elif name == "read_file":
            if success:
                self._console.print("\u2705 read_file", markup=False)
                text = (
                    output.get("content", "")
                    if isinstance(output, dict)
                    else str(output or "")
                )
                self._print_indented_lines(text, max_lines=3, max_line_len=200)
            else:
                error = self._extract_output_error(output)
                self._console.print("\u2717 read_file", style="red", markup=False)
                self._console.print(
                    f"   {error}", style="red", markup=False, highlight=False
                )

        elif name == "todo":
            if success:
                self._console.print("\u2705 todo", markup=False)
                summary = self._build_todo_result_summary(output)
                if summary:
                    self._console.print(f"   {summary}", markup=False, highlight=False)
            else:
                error = self._extract_output_error(output)
                self._console.print(f"\u2717 todo: {error}", style="red", markup=False)

        else:
            if success:
                self._console.print(f"\u2705 {name}", markup=False)
            else:
                error = self._extract_output_error(output)
                self._console.print(
                    f"\u2717 {name}: {error}", style="red", markup=False
                )

    def _print_indented_lines(
        self,
        text: str,
        max_lines: int = 3,
        max_line_len: int = 200,
        style: str | None = None,
    ) -> None:
        """Print up to ``max_lines`` of ``text``, each indented and truncated."""
        if not text:
            return
        for line in str(text).splitlines()[:max_lines]:
            self._console.print(
                f"   {line[:max_line_len]}",
                style=style,
                markup=False,
                highlight=False,
            )

    def _extract_output_error(self, output: Any) -> str:
        """Return a clean error string from a tool result output value."""
        if isinstance(output, dict):
            return str(output.get("error") or output.get("message") or "failed")
        if isinstance(output, str) and output:
            return output
        return "failed"

    def _build_todo_result_summary(self, output: Any) -> str:
        """Build a human-readable summary line from a todo tool result output."""
        if not isinstance(output, dict):
            return ""
        status = output.get("status", "")
        count = output.get("count")
        completed = output.get("completed")
        in_progress = output.get("in_progress")
        pending = output.get("pending")

        if status == "created" and count is not None:
            return f"created {count} items"
        parts: list[str] = []
        if completed is not None:
            parts.append(f"{completed} completed")
        if in_progress is not None:
            parts.append(f"{in_progress} in_progress")
        if pending is not None:
            parts.append(f"{pending} pending")
        if parts:
            return "updated: " + ", ".join(parts)
        if count is not None:
            return f"{count} items"
        return ""

    def _build_progress_bar(self, completed: int, total: int) -> Text:
        """Return a Rich Text progress bar: filled █ + empty ░ + count."""
        filled = int(_TODO_BAR_WIDTH * completed / total) if total > 0 else 0
        bar = Text()
        bar.append("█" * filled, style="green")
        bar.append("░" * (_TODO_BAR_WIDTH - filled), style="dim")
        bar.append(f" {completed}/{total}", style="dim")
        return bar

    def _todo_line(self, inner: Text, box_width: int) -> Text:
        """Return a bordered line ``│ {inner padded to box_width-4} │`` as a Rich Text."""
        inner_width = box_width - 4
        # Clip if the inner content is wider than the box allows
        if len(inner) > inner_width:
            inner = inner[:inner_width]
        padding = inner_width - len(inner)
        line = Text()
        line.append("│ ")
        line.append_text(inner)
        line.append(" " * padding + " │")
        return line

    def _handle_todo_update(self, data: Any) -> None:
        """Render todo items matching the foundation hooks-todo-display visual format.

        Uses manual box-drawing so the title appears inside the top border:
        ``┌─ Todo ─────────────────────┐``

        Full mode (≤7 items): padding + per-item lines + padding + progress bar + padding.
        Condensed mode (>7 items): single progress-bar line with current in-progress task.
        All-complete: single fully-filled bar line with "✓ Complete".
        """
        # Defensive parse: session-service relay may send data as a JSON string.
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                return
        if not isinstance(data, dict):
            return
        todos: list[dict[str, Any]] = data.get("todos", [])
        if not todos:
            return

        total = len(todos)
        completed_count = sum(1 for t in todos if t.get("status") == "completed")
        in_progress_item = next(
            (t for t in todos if t.get("status") == "in_progress"), None
        )
        all_complete = completed_count == total

        box_width = min(self._console.width, _TODO_PANEL_MAX_WIDTH)

        # ┌─ Todo ─...─┐  (title embedded in top border)
        top_border = "┌─ Todo " + "─" * (box_width - 9) + "┐"
        bottom_border = "└" + "─" * (box_width - 2) + "┘"
        empty_line = "│" + " " * (box_width - 2) + "│"

        self._console.print(top_border, markup=False)

        if all_complete:
            # Single line: fully filled green bar + count + ✓ Complete
            bar_inner = Text()
            bar_inner.append("█" * _TODO_BAR_WIDTH, style="green")
            bar_inner.append(f" {completed_count}/{total} ", style="green")
            bar_inner.append("✓ Complete", style="green")
            self._console.print(self._todo_line(bar_inner, box_width))

        elif total <= _TODO_FULL_MODE_THRESHOLD:
            # Full mode: empty padding, one line per item, padding, progress bar, padding
            self._console.print(empty_line, markup=False)

            for todo in todos:
                status = todo.get("status", "pending")
                content = str(todo.get("content", ""))
                active_form = str(todo.get("activeForm", "") or content)
                style = _TODO_STYLES.get(status, "dim")

                if status == "completed":
                    symbol, label = "✓", content
                elif status == "in_progress":
                    symbol, label = "▶", active_form
                else:
                    symbol, label = "○", content

                item_inner = Text()
                item_inner.append(f"{symbol} {label}", style=style)
                self._console.print(self._todo_line(item_inner, box_width))

            self._console.print(empty_line, markup=False)

            # Progress bar line
            self._console.print(
                self._todo_line(
                    self._build_progress_bar(completed_count, total), box_width
                )
            )

            self._console.print(empty_line, markup=False)

        else:
            # Condensed mode: single line — bar + count + current in-progress task
            content_inner = self._build_progress_bar(completed_count, total)

            if in_progress_item is not None:
                active_form = str(
                    in_progress_item.get("activeForm", "")
                    or in_progress_item.get("content", "")
                )
                content_inner.append(" ▶ ", style="bold cyan")
                content_inner.append(active_form, style="bold cyan")

            self._console.print(self._todo_line(content_inner, box_width))

        self._console.print(bottom_border, markup=False)

    def _handle_delegate_agent_spawned(self, data: Any) -> None:
        """Print a 🔧 delegation header indented according to session depth."""
        if not isinstance(data, dict):
            return
        depth = data.get("depth", 0)
        # Prefer "agent" field (forwarded child events); fall back to legacy "name".
        name = data.get("agent") or data.get("name", "sub-agent")
        indent = _NESTING_INDENT * (depth - 1) if depth > 0 else ""
        self._safe_print(
            f"{indent}\U0001f527 delegate -> [bold cyan]{name}[/bold cyan]"
        )

    def _handle_delegate_agent_completed(self, data: Any) -> None:
        """Print ✅ or ❌ based on success status when a delegate agent completes."""
        if not isinstance(data, dict):
            return
        success = data.get("success", True)
        # Prefer "agent" field (forwarded child events); fall back to legacy "name".
        name = data.get("agent") or data.get("name", "sub-agent")
        if success:
            icon = "\u2705"  # ✅
            style = "green"
        else:
            icon = "\u274c"  # ❌
            style = "red"
        self._console.print(f"  {icon} {name}", style=style, markup=False)

    def _handle_delegate_agent_resumed(self, data: Any) -> None:
        """Print a 🔄 resumption header with agent name and session_id."""
        if not isinstance(data, dict):
            return
        agent = data.get("agent") or data.get("name", "sub-agent")
        session_id = data.get("session_id", "")
        self._safe_print(
            f"\U0001f504 resume -> [bold cyan]{agent}[/bold cyan]"
            + (f" [dim]({session_id})[/dim]" if session_id else "")
        )

    def _handle_delegate_error(self, data: Any) -> None:
        """Print ✗ error with agent prefix in red style."""
        if not isinstance(data, dict):
            return
        agent = data.get("agent") or data.get("name", "")
        error = data.get("error", str(data))
        prefix = f"[{agent}] " if agent else ""
        self._console.print(f"  \u2717 {prefix}{error}", style="red", markup=False)

    def _handle_error(self, data: Any) -> None:
        """Print a red error message with ✗ icon.

        Accepts two formats:
        - Orchestrator format: {"error": "..."} or {"error": {"type": str, "msg": str}}
        - Session-service format (legacy): {"message": "..."}

        For structured errors (dict with "type" and "msg"), only "msg" is displayed.
        The "type" field is intentionally discarded to keep user-facing output concise.
        """
        if isinstance(data, dict):
            error = data.get("error")
            if error is not None:
                # Orchestrator format: prefer "error" field
                if isinstance(error, dict):
                    # Structured error: {"type": str, "msg": str}
                    message = error.get("msg", str(error))
                else:
                    message = str(error)
            else:
                # Legacy session-service format: fall back to "message";
                # unknown dict shape — surface raw representation as last resort
                message = str(data.get("message", str(data)))
        else:
            message = str(data)
        self._console.print(f"  \u2717 {message}", style="red", markup=False)

    def _handle_complete(self, data: Any) -> None:
        """Store the final response text. Print only if no tokens were streamed."""
        if isinstance(data, dict):
            self._response = data.get("result", "") or data.get("response", "")
        # Only print the response if no token events were received
        # (avoids duplication when tokens already printed the text)
        if self._response and not self._tokens_received:
            self._console.print(self._response, highlight=False, markup=False)
        if isinstance(data, dict) and "usage" in data:
            usage = data["usage"]
            input_t = usage.get("input_tokens", 0)
            output_t = usage.get("output_tokens", 0)
            self._console.print(f"tokens: {input_t} in / {output_t} out", style="dim")
        self._console.print()
