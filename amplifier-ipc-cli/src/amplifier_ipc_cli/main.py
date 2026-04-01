"""CLI entry point for the Amplifier IPC CLI."""

from __future__ import annotations

import click


@click.group()
def main() -> None:
    """Amplifier IPC CLI - interact with the Amplifier session service."""
