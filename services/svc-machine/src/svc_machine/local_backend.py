"""LocalBackend — async subprocess execution within a workspace directory."""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from pathlib import Path


_KILL_DRAIN_TIMEOUT = 2  # seconds to wait for process to exit after SIGKILL


@dataclass
class ExecResult:
    """Result of a subprocess execution."""

    stdout: str
    stderr: str
    exit_code: int


class LocalBackend:
    """Execute shell commands in a sandboxed workspace directory."""

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir.resolve()

    async def exec(
        self,
        command: str,
        timeout: int = 30,
        working_dir: str | None = None,
    ) -> ExecResult:
        """Execute a shell command asynchronously.

        Args:
            command: Shell command to run via /bin/bash.
            timeout: Maximum seconds to wait (default 30). Returns exit_code=124 on timeout.
            working_dir: Working directory for the command. Must resolve within workspace_dir.

        Returns:
            ExecResult with stdout, stderr, and exit_code.

        Raises:
            ValueError: If working_dir resolves outside workspace_dir.
        """
        cwd = self._resolve_working_dir(working_dir)

        process = await asyncio.create_subprocess_shell(
            command,
            executable="/bin/bash",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            start_new_session=True,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # Kill the entire process group
            try:
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            # Drain any remaining output
            try:
                await asyncio.wait_for(process.wait(), timeout=_KILL_DRAIN_TIMEOUT)
            except asyncio.TimeoutError:
                pass
            return ExecResult(
                stdout="Command timed out",
                stderr="",
                exit_code=124,
            )

        return ExecResult(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=process.returncode if process.returncode is not None else -1,
        )

    def _resolve_working_dir(self, working_dir: str | None) -> Path:
        """Resolve working_dir and verify it is within workspace_dir."""
        if working_dir is None:
            return self.workspace_dir

        resolved = Path(working_dir).resolve()

        # Check that resolved path is within workspace_dir
        try:
            resolved.relative_to(self.workspace_dir)
        except ValueError:
            raise ValueError(
                f"working_dir '{working_dir}' resolves to '{resolved}' which is "
                f"outside workspace '{self.workspace_dir}'"
            )

        return resolved
