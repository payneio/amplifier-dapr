"""Slash command dispatcher for the Amplifier IPC REPL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from rich.console import Console

    from amplifier_ipc_cli.client import SessionClient

_HELP_TEXT = """\
Available slash commands:
  /exit, /quit    Exit the REPL
  /help           Show this help text
  /status         Show current session status
  /tools          List available tools
  /clear          Clear the current session history
  /modes          List available modes
  /mode NAME on   Activate a mode by name
  /mode NAME off  Deactivate the current mode
"""


@dataclass
class SlashResult:
    """Result of dispatching a slash command."""

    should_exit: bool = False
    inline_prompt: str | None = None
    new_mode: str | None = None


async def dispatch_slash(
    raw: str,
    client: SessionClient,
    session_id: str,
    console: Console,
) -> SlashResult:
    """Parse and dispatch a slash command.

    Returns a SlashResult indicating how the REPL should proceed.
    """
    parts = raw.strip().split()
    if not parts:
        return SlashResult()

    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("/exit", "/quit"):
        return SlashResult(should_exit=True)

    if cmd == "/help":
        console.print(_HELP_TEXT)
        return SlashResult()

    if cmd == "/status":
        return await _handle_status(client, session_id, console)

    if cmd == "/tools":
        return await _handle_tools(client, session_id, console)

    if cmd == "/clear":
        return await _handle_clear(client, session_id, console)

    if cmd == "/modes":
        return await _handle_modes(client, session_id, console)

    if cmd == "/mode":
        return _handle_mode(args, console)

    console.print(
        f"[yellow]Unknown command: {cmd}. Type /help for available commands.[/yellow]"
    )
    return SlashResult()


async def _handle_status(
    client: SessionClient,
    session_id: str,
    console: Console,
) -> SlashResult:
    """Handle the /status command."""
    try:
        info: dict[str, Any] = await client.get_session_info(session_id)

        table = Table(show_header=True, header_style="bold")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("Session ID", str(info.get("id", session_id)))
        table.add_row("Status", str(info.get("status", "unknown")))
        table.add_row("Turn Count", str(info.get("turn_count", "unknown")))

        console.print(Panel(table, title="Session Status"))
    except Exception as exc:
        console.print(f"[yellow]Could not retrieve session status: {exc}[/yellow]")

    return SlashResult()


async def _handle_tools(
    client: SessionClient,
    session_id: str,
    console: Console,
) -> SlashResult:
    """Handle the /tools command."""
    try:
        tools: list[dict[str, Any]] = await client.get_tools(session_id)

        table = Table(show_header=True, header_style="bold")
        table.add_column("Name")
        table.add_column("Description")

        for tool in tools:
            name = str(tool.get("name", ""))
            description = str(tool.get("description", ""))
            if len(description) > 80:
                description = description[:77] + "..."
            table.add_row(name, description)

        console.print(table)
    except Exception as exc:
        console.print(f"[yellow]Could not retrieve tools: {exc}[/yellow]")

    return SlashResult()


async def _handle_clear(
    client: SessionClient,
    session_id: str,
    console: Console,
) -> SlashResult:
    """Handle the /clear command."""
    try:
        await client.clear_session(session_id)
        console.print("[green]Session cleared.[/green]")
    except Exception as exc:
        console.print(f"[yellow]Could not clear session: {exc}[/yellow]")

    return SlashResult()


async def _handle_modes(
    client: SessionClient,
    session_id: str,
    console: Console,
) -> SlashResult:
    """Handle the /modes command."""
    try:
        modes: list[dict[str, Any]] = await client.get_modes(session_id)

        table = Table(show_header=True, header_style="bold")
        table.add_column("Name")
        table.add_column("Description")

        for mode in modes:
            name = str(mode.get("name", ""))
            description = str(mode.get("description", ""))
            if len(description) > 80:
                description = description[:77] + "..."
            table.add_row(name, description)

        console.print(table)
    except Exception as exc:
        console.print(f"[yellow]Could not retrieve modes: {exc}[/yellow]")

    return SlashResult()


def _handle_mode(args: list[str], console: Console) -> SlashResult:
    """Handle the /mode command.

    Usage:
        /mode NAME on   - activate the named mode
        /mode NAME off  - deactivate the mode (returns new_mode=None)
    """
    try:
        if len(args) < 2:
            console.print("[yellow]Usage: /mode NAME on|off[/yellow]")
            return SlashResult()

        name = args[0]
        action = args[1].lower()

        if action == "on":
            console.print(f"[green]Mode '{name}' activated.[/green]")
            return SlashResult(new_mode=name)
        elif action == "off":
            console.print(f"[green]Mode '{name}' deactivated.[/green]")
            return SlashResult(new_mode=None)
        else:
            console.print(
                f"[yellow]Unknown mode action '{action}'. Use 'on' or 'off'.[/yellow]"
            )
            return SlashResult()
    except Exception as exc:
        console.print(f"[yellow]Could not set mode: {exc}[/yellow]")
        return SlashResult()
