"""SSHDriver — SSH-based machine backend driver using asyncssh."""

from __future__ import annotations

import asyncio
from typing import Any

try:
    import asyncssh  # type: ignore[import-untyped]
except ImportError:
    asyncssh = None  # type: ignore[assignment]

from svc_machine.driver import (
    ExecResult,
    FileEditResult,
    FileGlobResult,
    FileReadResult,
    MachineDriver,
)


class SSHDriver(MachineDriver):
    """SSH-based machine backend driver."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 22,
        username: str | None = None,
        working_dir: str = "/workspace",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.working_dir = working_dir
        self._conn: Any | None = None

    async def connect(self) -> None:  # type: ignore[override]
        """Establish an SSH connection using asyncssh."""
        if self._conn is not None:
            raise RuntimeError(
                "SSHDriver is already connected — call disconnect() first"
            )
        self._conn = await asyncssh.connect(  # type: ignore[union-attr]
            host=self.host,
            port=self.port,
            known_hosts=None,  # Dev/workspace only — host key verification disabled
            username=self.username,
        )

    async def disconnect(self) -> None:  # type: ignore[override]
        """Close the SSH connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _wrap_command(self, command: str, working_dir: str | None = None) -> str:
        """Prepend 'cd {working_dir} && ' to a command."""
        wd = working_dir if working_dir is not None else self.working_dir
        return f"cd {wd} && {command}"

    async def exec(  # type: ignore[override]
        self,
        command: str,
        timeout: int = 30,
        working_dir: str | None = None,
    ) -> ExecResult:
        """Execute a command over SSH and return the result."""
        if self._conn is None:
            raise RuntimeError("SSHDriver is not connected — call connect() first")
        wrapped = self._wrap_command(command, working_dir)
        try:
            result = await asyncio.wait_for(
                self._conn.run(wrapped, check=False),  # type: ignore[union-attr]
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return ExecResult(stdout="", stderr="", exit_code=124)

        return ExecResult(
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            exit_code=result.returncode if result.returncode is not None else -1,
        )

    async def exec_background(  # type: ignore[override]
        self,
        command: str,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        """Spawn a background process via SSH using nohup and return its PID."""
        if self._conn is None:
            raise RuntimeError("SSHDriver is not connected — call connect() first")
        bg_command = f"nohup {command} & echo $!"
        wrapped = self._wrap_command(bg_command, working_dir)
        result = await self._conn.run(wrapped, check=False)  # type: ignore[union-attr]
        pid_str = (result.stdout or "").strip()
        try:
            pid = int(pid_str)
        except (ValueError, TypeError):
            pid = -1
        return {"pid": pid, "status": "running"}

    def file_read(  # type: ignore[override]
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> FileReadResult | None:
        raise NotImplementedError("SSHDriver.file_read() — implement in Task 5")

    def file_write(self, path: str, content: str) -> bool:  # type: ignore[override]
        raise NotImplementedError("SSHDriver.file_write() — implement in Task 5")

    def file_edit(  # type: ignore[override]
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileEditResult | None:
        raise NotImplementedError("SSHDriver.file_edit() — implement in Task 5")

    def file_list(self, path: str = ".") -> list[dict[str, Any]] | None:  # type: ignore[override]
        raise NotImplementedError("SSHDriver.file_list() — implement in Task 5")

    def file_glob(  # type: ignore[override]
        self,
        pattern: str,
        path: str = ".",
        exclude: list[str] | None = None,
        type_filter: str = "file",
        include_ignored: bool = False,
    ) -> FileGlobResult | None:
        raise NotImplementedError("SSHDriver.file_glob() — implement in Task 5")

    def file_grep(  # type: ignore[override]
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob_pattern: str | None = None,
        file_type: str | None = None,
        after_context: int | None = None,
        before_context: int | None = None,
        context: int | None = None,
        case_insensitive: bool = False,
        line_numbers: bool = True,
        head_limit: int | None = None,
        offset: int = 0,
        include_ignored: bool = False,
        multiline: bool = False,
    ) -> dict[str, Any] | None:
        raise NotImplementedError("SSHDriver.file_grep() — implement in Task 5")
