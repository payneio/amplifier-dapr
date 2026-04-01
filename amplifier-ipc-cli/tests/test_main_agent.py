"""Tests for the --agent / -a CLI flag in the run command."""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from amplifier_ipc_cli.client import SSEEvent
from amplifier_ipc_cli.main import cli


def _make_mock_client(events: list[SSEEvent]) -> MagicMock:
    """Return a mock SessionClient that yields the given events from stream_turn."""

    async def mock_stream(*args: Any, **kwargs: Any) -> AsyncIterator[SSEEvent]:
        for e in events:
            yield e

    mock = MagicMock()
    mock.stream_turn = mock_stream
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


class TestAgentFlag:
    def test_agent_flag_appears_in_help(self) -> None:
        """--agent flag is documented in run --help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "--agent" in result.output or "-a" in result.output

    def test_agent_flag_threads_through_to_stream_turn(self) -> None:
        """--agent value reaches client.stream_turn as agent_ref kwarg."""
        received_kwargs: dict[str, Any] = {}

        async def capturing_stream(*args: Any, **kwargs: Any) -> AsyncIterator[SSEEvent]:
            received_kwargs.update(kwargs)
            yield SSEEvent(event="complete", data={"result": "done", "messages": []})

        mock_client = MagicMock()
        mock_client.stream_turn = capturing_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        runner = CliRunner()
        with patch("amplifier_ipc_cli.main.SessionClient", return_value=mock_client):
            runner.invoke(cli, ["run", "--agent", "foundation", "hello"])

        assert received_kwargs.get("agent_ref") == "foundation"

    def test_short_agent_flag(self) -> None:
        """-a shorthand works identically to --agent."""
        received_kwargs: dict[str, Any] = {}

        async def capturing_stream(*args: Any, **kwargs: Any) -> AsyncIterator[SSEEvent]:
            received_kwargs.update(kwargs)
            yield SSEEvent(event="complete", data={"result": "done", "messages": []})

        mock_client = MagicMock()
        mock_client.stream_turn = capturing_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        runner = CliRunner()
        with patch("amplifier_ipc_cli.main.SessionClient", return_value=mock_client):
            runner.invoke(cli, ["run", "-a", "foundation", "hello"])

        assert received_kwargs.get("agent_ref") == "foundation"

    def test_no_agent_flag_sends_none(self) -> None:
        """When --agent is omitted, agent_ref=None is passed to stream_turn."""
        received_kwargs: dict[str, Any] = {}

        async def capturing_stream(*args: Any, **kwargs: Any) -> AsyncIterator[SSEEvent]:
            received_kwargs.update(kwargs)
            yield SSEEvent(event="complete", data={"result": "done", "messages": []})

        mock_client = MagicMock()
        mock_client.stream_turn = capturing_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        runner = CliRunner()
        with patch("amplifier_ipc_cli.main.SessionClient", return_value=mock_client):
            runner.invoke(cli, ["run", "hello"])

        assert received_kwargs.get("agent_ref") is None

    def test_agent_and_provider_together(self) -> None:
        """--agent and --provider can be combined and both reach stream_turn."""
        received_kwargs: dict[str, Any] = {}

        async def capturing_stream(*args: Any, **kwargs: Any) -> AsyncIterator[SSEEvent]:
            received_kwargs.update(kwargs)
            yield SSEEvent(event="complete", data={"result": "done", "messages": []})

        mock_client = MagicMock()
        mock_client.stream_turn = capturing_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        runner = CliRunner()
        with patch("amplifier_ipc_cli.main.SessionClient", return_value=mock_client):
            runner.invoke(
                cli,
                ["run", "--agent", "foundation", "--provider", "anthropic", "hello"],
            )

        assert received_kwargs.get("agent_ref") == "foundation"
        assert received_kwargs.get("provider_name") == "anthropic"
