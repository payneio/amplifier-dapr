"""CLI entry point for the Amplifier IPC CLI."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from amplifier_ipc_cli.client import SessionClient
from amplifier_ipc_cli.workspace import resolve_workspace_content

_VERSION = "amplifier-ipc-cli 0.1.0"


# ---------------------------------------------------------------------------
# JSON error helper
# ---------------------------------------------------------------------------


def _emit_json_error(message: str, session_id: str | None) -> None:
    """Write a JSON error payload to stdout."""
    payload: dict[str, Any] = {
        "status": "error",
        "error": message,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    click.echo(json.dumps(payload))


# ---------------------------------------------------------------------------
# _run_impl
# ---------------------------------------------------------------------------


async def _run_impl(
    url: str,
    session_id: str | None,
    provider: str,
    workspace: str,
    output_format: str,
    message: str | None,
    agent: str | None = None,
) -> int:
    """Async implementation of the run command.

    Returns an exit code: 0 for success, 1 for error.
    """
    from rich.console import Console

    from amplifier_ipc_cli.display import StreamingDisplay

    console = Console(stderr=(output_format == "json"))

    # Resolve session ID
    effective_session_id: str = session_id or str(uuid.uuid4())

    # Resolve workspace content — sent as a dict to the server, which
    # handles formatting into <context_file> blocks for the system prompt.
    workspace_path = Path(workspace)
    workspace_content: dict[str, str] | None = (
        resolve_workspace_content(workspace_path) or None
    )

    # Determine prompt from message or piped stdin
    prompt: str | None = message

    if prompt is None:
        if not sys.stdin.isatty():
            piped = sys.stdin.read()
            if not piped.strip():
                _emit_json_error(
                    "No message provided and stdin is empty.", effective_session_id
                )
                return 1
            prompt = piped.strip()

    async with SessionClient(base_url=url) as client:
        if prompt is not None:
            # Single-turn mode
            if output_format == "json":
                # Accumulate response for JSON output
                accumulated_response = ""
                try:
                    async for event in client.stream_turn(
                        effective_session_id,
                        prompt,
                        workspace_content=workspace_content,
                        provider_name=provider,
                        agent_ref=agent,
                    ):
                        if event.event == "complete" and isinstance(event.data, dict):
                            accumulated_response = event.data.get(
                                "result", ""
                            ) or event.data.get("response", "")
                        elif event.event == "error":
                            error_msg = (
                                event.data.get("message", str(event.data))
                                if isinstance(event.data, dict)
                                else str(event.data)
                            )
                            _emit_json_error(error_msg, effective_session_id)
                            return 1
                except Exception as exc:
                    _emit_json_error(str(exc), effective_session_id)
                    return 1

                result = {
                    "status": "success",
                    "response": accumulated_response,
                    "session_id": effective_session_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                click.echo(json.dumps(result))
            else:
                # Text mode: stream events and render
                try:
                    async with StreamingDisplay(console) as display:
                        async for event in client.stream_turn(
                            effective_session_id,
                            prompt,
                            workspace_content=workspace_content,
                            provider_name=provider,
                            agent_ref=agent,
                        ):
                            await display.handle_event(event)
                except Exception as exc:
                    console.print(f"[red]Error: {exc}[/red]")
                    return 1
        else:
            # REPL mode
            from amplifier_ipc_cli.repl import interactive_repl

            # Check health first
            is_healthy = await client.healthcheck()
            if not is_healthy:
                if output_format == "json":
                    _emit_json_error(
                        f"Service at {url} is not available.", effective_session_id
                    )
                else:
                    console.print(
                        f"[red]Error: Service at {url} is not available.[/red]"
                    )
                return 1

            await interactive_repl(
                client=client,
                session_id=effective_session_id,
                provider_name=provider,
                workspace_content=workspace_content,
                console=console,
                agent_ref=agent,
            )

    return 0


# ---------------------------------------------------------------------------
# CLI group and commands
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """Amplifier CLI."""


@cli.command()
def version() -> None:
    """Print the CLI version."""
    click.echo(_VERSION)


@cli.command()
@click.option(
    "--url",
    default="http://localhost:8090",
    envvar="AMPLIFIER_URL",
    show_default=True,
    help="URL of the Amplifier session service.",
)
@click.option(
    "--session",
    "-s",
    default=None,
    help="Session ID to use (auto-generated if not provided).",
)
@click.option(
    "--provider",
    "-p",
    default="mock",
    show_default=True,
    help="Provider name to use for AI turns.",
)
@click.option(
    "--workspace",
    "-w",
    default=lambda: os.getcwd(),
    type=click.Path(file_okay=False, resolve_path=True),
    show_default="<cwd>",
    help="Workspace directory path.",
)
@click.option(
    "--output-format",
    "-o",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--agent",
    "-a",
    default=None,
    help="Agent to use (e.g. 'foundation'). Determines service set and default provider.",
)
@click.argument("message", required=False)
def run(
    url: str,
    session: str | None,
    provider: str,
    workspace: str,
    output_format: str,
    agent: str | None,
    message: str | None,
) -> None:
    """Send MESSAGE to the Amplifier session service.

    If MESSAGE is omitted and stdin is piped, reads from stdin.
    If MESSAGE is omitted and stdin is a tty, enters interactive REPL mode.
    """
    exit_code = asyncio.run(
        _run_impl(
            url=url,
            session_id=session,
            provider=provider,
            workspace=workspace,
            output_format=output_format,
            message=message,
            agent=agent,
        )
    )
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point for the amplifier CLI."""
    cli()
