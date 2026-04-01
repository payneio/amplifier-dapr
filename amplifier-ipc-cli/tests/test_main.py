"""Tests for CLI entry point (main.py)."""

from __future__ import annotations

from click.testing import CliRunner

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
