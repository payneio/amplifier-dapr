"""Interactive REPL using the session-service HTTP API."""

from __future__ import annotations

import asyncio
import html as html_lib
import re
import signal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

    from amplifier_ipc_cli.client import SessionClient


# Maximum file size to inject (512 KB)
_MAX_FILE_BYTES = 512 * 1024

# Regex that matches @path mentions
_MENTION_RE = re.compile(r"@([\w./~-]+)")

BANNER = """\
Amplifier IPC REPL
  Type your message and press Enter to send.
  Press Ctrl-J for a literal newline inside your message.
  Type /help for available slash commands.
  Type exit or quit to leave.
  Press Ctrl-C once to cancel gracefully, twice to cancel immediately.
"""


# ---------------------------------------------------------------------------
# CancellationState
# ---------------------------------------------------------------------------


class CancellationState:
    """Tracks whether and how the current REPL turn should be cancelled."""

    def __init__(self) -> None:
        self.is_cancelled: bool = False
        self.is_immediate: bool = False
        self.current_tool: str | None = None

    def request_graceful(self) -> None:
        """Request a graceful cancellation (finish current tool, then stop)."""
        self.is_cancelled = True
        self.is_immediate = False

    def request_immediate(self) -> None:
        """Request an immediate cancellation (stop as soon as possible)."""
        self.is_cancelled = True
        self.is_immediate = True

    def reset(self) -> None:
        """Clear all cancellation flags back to their initial state."""
        self.is_cancelled = False
        self.is_immediate = False
        self.current_tool = None


# ---------------------------------------------------------------------------
# process_mentions
# ---------------------------------------------------------------------------


def process_mentions(user_input: str, console: Console) -> str:
    """Replace @path mentions with <context_file> blocks.

    For each @path mention found in *user_input*:
    - Attempts to read the file at *path*.
    - Skips files larger than 512 KB.
    - Silently skips files that cannot be read (OSError / UnicodeDecodeError).
    - Prepends a ``<context_file path="…">…</context_file>`` block for each
      successfully loaded file.
    - Strips the @mention from the original user text.

    Returns the transformed string.
    """
    mentions = _MENTION_RE.findall(user_input)
    if not mentions:
        return user_input

    context_blocks: list[str] = []
    stripped_text = user_input

    for path_str in mentions:
        mention_token = f"@{path_str}"
        # Expand ~ to the user's home directory
        resolved = Path(path_str).expanduser()

        try:
            if resolved.stat().st_size > _MAX_FILE_BYTES:
                console.print(
                    f"[yellow]Skipping {path_str}: file exceeds 512 KB[/yellow]"
                )
                stripped_text = stripped_text.replace(mention_token, "", 1)
                continue

            content = resolved.read_text(encoding="utf-8")
            context_blocks.append(
                f'<context_file path="{path_str}">\n{content}\n</context_file>'
            )
        except (OSError, UnicodeDecodeError):
            pass

        stripped_text = stripped_text.replace(mention_token, "", 1)

    if context_blocks:
        prefix = "\n".join(context_blocks) + "\n\n"
        return prefix + stripped_text
    return stripped_text


# ---------------------------------------------------------------------------
# build_prompt_html
# ---------------------------------------------------------------------------


def build_prompt_html(active_mode: str | None):
    """Return a prompt_toolkit HTML object for the REPL prompt.

    - No mode  → green ``>``
    - With mode → cyan ``[mode_name]>``
    - Special HTML characters in *active_mode* are escaped.
    """
    from prompt_toolkit.formatted_text import HTML

    if active_mode is None:
        return HTML("<ansigreen>&gt;</ansigreen> ")

    escaped = (
        html_lib.escape(active_mode, quote=False)
        # html.escape handles & < > by default
    )
    return HTML(f"<ansicyan>[{escaped}]&gt;</ansicyan> ")


# ---------------------------------------------------------------------------
# _create_prompt_session
# ---------------------------------------------------------------------------


def _create_prompt_session(history_path: str | None):
    """Create and return a prompt_toolkit PromptSession.

    - Uses FileHistory when *history_path* is provided, InMemoryHistory otherwise.
    - Binds Ctrl-J to insert a newline and Enter to accept the input.
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory, InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings

    history = FileHistory(history_path) if history_path else InMemoryHistory()

    bindings = KeyBindings()

    @bindings.add("c-j")
    def _insert_newline(event: object) -> None:
        """Insert a literal newline (Ctrl-J)."""

        event.current_buffer.insert_text("\n")  # type: ignore[union-attr]

    @bindings.add("enter")
    def _accept(event: object) -> None:
        """Accept the current input (Enter)."""
        event.current_buffer.validate_and_handle()  # type: ignore[union-attr]

    return PromptSession(history=history, key_bindings=bindings)


# ---------------------------------------------------------------------------
# interactive_repl
# ---------------------------------------------------------------------------


async def interactive_repl(
    client: SessionClient,
    session_id: str,
    provider_name: str | None,
    workspace_content: str | None,
    console: Console,
    history_path: str | None = None,
    agent_ref: str | None = None,
) -> None:
    """Run the interactive REPL loop.

    Reads user input, processes @mentions, dispatches slash commands, and
    streams each AI turn, rendering output live.  Handles SIGINT for graceful
    then immediate cancellation.
    """
    from rich.panel import Panel

    console.print(Panel(BANNER.strip(), title="Amplifier IPC REPL", expand=False))

    session = _create_prompt_session(history_path)
    cancellation = CancellationState()

    def _handle_sigint(sig: int, frame: object) -> None:
        if cancellation.is_cancelled:
            cancellation.request_immediate()
        else:
            cancellation.request_graceful()
            console.print(
                "\n[yellow]Cancelling… press Ctrl-C again to force stop[/yellow]"
            )

    original_sigint = signal.signal(signal.SIGINT, _handle_sigint)

    try:
        while True:
            cancellation.reset()
            try:
                user_input: str = await session.prompt_async(
                    build_prompt_html(None),
                    multiline=False,
                )
            except (EOFError, KeyboardInterrupt):
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.lower() in {"exit", "quit"}:
                break

            if user_input.startswith("/"):
                from amplifier_ipc_cli import slash_commands  # type: ignore[attr-defined]  # lazy import

                handled = await slash_commands.dispatch_slash(
                    user_input, client, session_id, console
                )
                if handled:
                    continue

            # Process @mentions
            user_input = process_mentions(user_input, console)

            # Stream the turn
            try:
                from amplifier_ipc_cli.display import StreamingDisplay  # type: ignore[import-untyped]  # lazy import

                async with StreamingDisplay(console) as display:
                    async for event in client.stream_turn(
                        session_id,
                        user_input,
                        workspace_content=workspace_content,
                        provider_name=provider_name,
                        agent_ref=agent_ref,
                    ):
                        if cancellation.is_immediate:
                            break
                        await display.handle_event(event)
            except asyncio.CancelledError:
                console.print("[yellow]Turn cancelled.[/yellow]")
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]")
    finally:
        signal.signal(signal.SIGINT, original_sigint)
