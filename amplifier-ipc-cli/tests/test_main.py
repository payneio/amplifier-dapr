"""Tests for CLI entry point (main.py)."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from amplifier_ipc_cli.client import SSEEvent
from amplifier_ipc_cli.main import cli


class TestHelp:
    def test_help(self) -> None:
        """CLI group --help exits 0 and mentions 'Amplifier'."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Amplifier" in result.output


class TestVersion:
    def test_version(self) -> None:
        """version command exits 0 and prints '0.1.0'."""
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestRunHelp:
    def test_run_help(self) -> None:
        """run --help exits 0 and mentions MESSAGE argument."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "MESSAGE" in result.output


class TestRunWithMessage:
    def test_run_with_message_requires_service(self) -> None:
        """run with MESSAGE argument exits gracefully on connection error (no service)."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "hello world"])
        # Should not crash with unhandled exception - exit_code != 0 is expected
        # since there's no service running, but it should be graceful
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            f"Unexpected exception: {result.exception}"
        )
        # Should not contain a Python traceback
        assert "Traceback" not in result.output


class TestJsonModeStreamError:
    def test_json_mode_stream_error_returns_exit_code_1(self) -> None:
        """JSON mode should return exit code 1 when stream delivers an error event."""

        async def mock_stream(*args: Any, **kwargs: Any) -> AsyncIterator[SSEEvent]:
            yield SSEEvent(event="error", data={"message": "stream error occurred"})

        mock_client = MagicMock()
        mock_client.stream_turn = mock_stream
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class = MagicMock(return_value=mock_client)

        runner = CliRunner()
        with patch("amplifier_ipc_cli.main.SessionClient", mock_client_class):
            result = runner.invoke(
                cli, ["run", "--output-format", "json", "test message"]
            )

        # Output should be a JSON error payload
        output = json.loads(result.output.strip())
        assert output["status"] == "error"
        assert "stream error occurred" in output["error"]
        # Exit code must be 1, not 0
        assert result.exit_code == 1, (
            f"Expected exit code 1 on stream error event, got {result.exit_code}"
        )
