"""MachineDriver — abstract base class for all machine backend drivers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ExecResult:
    """Result of a subprocess execution."""

    stdout: str
    stderr: str
    exit_code: int


@dataclass
class FileReadResult:
    """Result of a file read operation."""

    content: str
    total_lines: int


@dataclass
class FileEditResult:
    """Result of a file edit operation."""

    success: bool
    replacements_made: int


@dataclass
class FileGlobResult:
    """Result of a file glob operation."""

    matches: list[str]
    total_files: int


class MachineDriver(ABC):
    """Abstract base class defining the contract for all machine backend drivers.

    All methods are async to support both local and remote (SSH) backends
    through a single uniform interface.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish a connection to the machine backend."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection to the machine backend."""

    @abstractmethod
    async def exec(
        self,
        command: str,
        timeout: int = 30,
        working_dir: str | None = None,
    ) -> ExecResult:
        """Execute a shell command and return the result."""

    @abstractmethod
    async def exec_background(
        self,
        command: str,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        """Spawn a background process and return its PID and status."""

    @abstractmethod
    async def file_read(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> FileReadResult | None:
        """Read a file and return its content with line information."""

    @abstractmethod
    async def file_write(self, path: str, content: str) -> bool:
        """Write content to a file, returning True on success."""

    @abstractmethod
    async def file_edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileEditResult | None:
        """Replace string(s) in a file and return the edit result."""

    @abstractmethod
    async def file_list(self, path: str = ".") -> list[dict[str, Any]] | None:
        """List directory entries at the given path."""

    @abstractmethod
    async def file_glob(
        self,
        pattern: str,
        path: str = ".",
        exclude: list[str] | None = None,
        type_filter: str = "file",
        include_ignored: bool = False,
    ) -> FileGlobResult | None:
        """Match files using a glob pattern and return results."""

    @abstractmethod
    async def file_grep(
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
        """Search file contents using a regex pattern and return matches."""
