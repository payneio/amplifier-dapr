"""Tests for LocalBackend — async subprocess execution."""

from pathlib import Path

import pytest

from svc_machine.local_backend import ExecResult, LocalBackend


class TestExec:
    """Tests for LocalBackend.exec()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    async def test_echo(self, backend: LocalBackend) -> None:
        """exec() captures stdout from a simple echo command."""
        result = await backend.exec("echo hello")
        assert isinstance(result, ExecResult)
        assert result.stdout.strip() == "hello"
        assert result.exit_code == 0

    async def test_exit_code_nonzero(self, backend: LocalBackend) -> None:
        """exec() captures non-zero exit codes."""
        result = await backend.exec("exit 42", timeout=5)
        assert result.exit_code == 42

    async def test_stderr(self, backend: LocalBackend) -> None:
        """exec() captures stderr output separately."""
        result = await backend.exec("echo error_output >&2")
        assert "error_output" in result.stderr
        assert result.exit_code == 0

    async def test_timeout(self, backend: LocalBackend) -> None:
        """exec() kills the process and returns exit_code=124 on timeout."""
        result = await backend.exec("sleep 60", timeout=1)
        assert result.exit_code == 124
        assert (
            "timed out" in result.stdout.lower() or "timed out" in result.stderr.lower()
        )

    async def test_working_dir(self, backend: LocalBackend, tmp_path: Path) -> None:
        """exec() runs command in the specified working directory."""
        # working_dir is a path relative to workspace_dir or an absolute path within it
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        result = await backend.exec("pwd", working_dir=str(subdir))
        assert str(subdir) in result.stdout.strip()
        assert result.exit_code == 0

    async def test_working_dir_outside_workspace_raises(
        self, backend: LocalBackend
    ) -> None:
        """exec() raises ValueError when working_dir is outside workspace_dir."""
        with pytest.raises(ValueError, match="outside workspace"):
            await backend.exec("echo hi", working_dir="/etc")
