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

    def _resolve_path(self, relative_path: str) -> Path | None:
        """Resolve a path within the workspace, returning None if it escapes."""
        resolved = (self.workspace_dir / relative_path).resolve()
        try:
            resolved.relative_to(self.workspace_dir)
        except ValueError:
            return None
        return resolved

    def file_read(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> FileReadResult | None:
        """Read a file within the workspace with 1-based offset and optional line limit.

        Args:
            path: Relative path within the workspace.
            offset: 1-based line number to start reading from (default 1).
            limit: Maximum number of lines to return (default: all remaining).

        Returns:
            FileReadResult with content and total_lines, or None if the file
            does not exist or path escapes the workspace.
        """
        resolved = self._resolve_path(path)
        if resolved is None or not resolved.exists():
            return None

        text = resolved.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)

        start = offset - 1
        selected = lines[start : start + limit] if limit is not None else lines[start:]
        content = "".join(selected)

        return FileReadResult(content=content, total_lines=total_lines)

    def file_write(self, path: str, content: str) -> bool:
        """Write content to a file within the workspace, creating parent directories.

        Args:
            path: Relative path within the workspace.
            content: Text content to write.

        Returns:
            True on success, False if path escapes the workspace.
        """
        resolved = self._resolve_path(path)
        if resolved is None:
            return False

        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return True

    def file_edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileEditResult | None:
        """Replace string(s) in a file within the workspace.

        Args:
            path: Relative path within the workspace.
            old_string: String to search for.
            new_string: Replacement string.
            replace_all: Replace all occurrences when True; only the first when False.

        Returns:
            FileEditResult with success and replacements_made, or None if the file
            does not exist or path escapes the workspace.
        """
        resolved = self._resolve_path(path)
        if resolved is None or not resolved.exists():
            return None

        content = resolved.read_text(encoding="utf-8", errors="replace")

        if replace_all:
            replacements_made = content.count(old_string)
            new_content = content.replace(old_string, new_string)
        else:
            replacements_made = 1 if old_string in content else 0
            new_content = content.replace(old_string, new_string, 1)

        if replacements_made > 0:
            resolved.write_text(new_content, encoding="utf-8")

        return FileEditResult(
            success=replacements_made > 0, replacements_made=replacements_made
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
