"""SSHDriver — placeholder for SSH-based machine backend driver."""

from __future__ import annotations

from typing import Any

from svc_machine.driver import (
    ExecResult,
    FileEditResult,
    FileGlobResult,
    FileReadResult,
    MachineDriver,
)


class SSHDriver(MachineDriver):
    """SSH-based machine backend driver (stub — not yet fully implemented)."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "",
        working_dir: str = ".",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.working_dir = working_dir

    async def connect(self) -> None:  # type: ignore[override]
        raise NotImplementedError("SSHDriver.connect() is not yet implemented")

    async def disconnect(self) -> None:  # type: ignore[override]
        raise NotImplementedError("SSHDriver.disconnect() is not yet implemented")

    def exec(  # type: ignore[override]
        self,
        command: str,
        timeout: int = 30,
        working_dir: str | None = None,
    ) -> ExecResult:
        raise NotImplementedError("SSHDriver.exec() is not yet implemented")

    def exec_background(  # type: ignore[override]
        self,
        command: str,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError("SSHDriver.exec_background() is not yet implemented")

    def file_read(  # type: ignore[override]
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> FileReadResult | None:
        raise NotImplementedError("SSHDriver.file_read() is not yet implemented")

    def file_write(self, path: str, content: str) -> bool:  # type: ignore[override]
        raise NotImplementedError("SSHDriver.file_write() is not yet implemented")

    def file_edit(  # type: ignore[override]
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileEditResult | None:
        raise NotImplementedError("SSHDriver.file_edit() is not yet implemented")

    def file_list(self, path: str = ".") -> list[dict[str, Any]] | None:  # type: ignore[override]
        raise NotImplementedError("SSHDriver.file_list() is not yet implemented")

    def file_glob(  # type: ignore[override]
        self,
        pattern: str,
        path: str = ".",
        exclude: list[str] | None = None,
        type_filter: str = "file",
        include_ignored: bool = False,
    ) -> FileGlobResult | None:
        raise NotImplementedError("SSHDriver.file_glob() is not yet implemented")

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
        raise NotImplementedError("SSHDriver.file_grep() is not yet implemented")
