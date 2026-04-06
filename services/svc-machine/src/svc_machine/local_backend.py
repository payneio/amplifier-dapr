"""LocalBackend — async subprocess execution within a workspace directory."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import signal
import subprocess as _subprocess_module
from pathlib import Path
from subprocess import DEVNULL
from typing import Any

from svc_machine.driver import (
    ExecResult,
    FileEditResult,
    FileGlobResult,
    FileReadResult,
    MachineDriver,
)

# Re-export for backwards compatibility (callers that imported from local_backend)
__all__ = [
    "ExecResult",
    "FileEditResult",
    "FileGlobResult",
    "FileReadResult",
    "LocalBackend",
]

_KILL_DRAIN_TIMEOUT = 2  # seconds to wait for process to exit after SIGKILL


class LocalBackend(MachineDriver):
    """Execute shell commands in a sandboxed workspace directory."""

    _EXCLUDED_DIRS: list[str] = [
        "node_modules",
        ".venv",
        ".git",
        "__pycache__",
        "build",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".eggs",
    ]
    # Aliases kept so callers referencing either name remain valid
    _GREP_EXCLUDED_DIRS = _EXCLUDED_DIRS
    _GLOB_EXCLUDED_DIRS = _EXCLUDED_DIRS

    _GLOB_MAX_RESULTS = 500

    _GREP_HEAD_LIMITS: dict[str, int] = {
        "files_with_matches": 200,
        "count": 200,
        "content": 500,
    }

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir.resolve()

    async def connect(self) -> None:  # type: ignore[override]
        """No-op — local backend requires no connection setup."""

    async def disconnect(self) -> None:  # type: ignore[override]
        """No-op — local backend requires no connection teardown."""

    async def exec(  # type: ignore[override]
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

    async def exec_background(  # type: ignore[override]
        self,
        command: str,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        """Spawn a fire-and-forget subprocess in a new session.

        Args:
            command: Shell command to run via /bin/bash.
            working_dir: Working directory for the command. Must resolve within workspace_dir.

        Returns:
            Dict with 'pid' (int) and 'status' ('running').

        Raises:
            ValueError: If working_dir resolves outside workspace_dir.
        """
        cwd = self._resolve_working_dir(working_dir)

        process = _subprocess_module.Popen(
            command,
            shell=True,
            executable="/bin/bash",
            stdout=DEVNULL,
            stderr=DEVNULL,
            cwd=str(cwd),
            start_new_session=True,
        )
        return {"pid": process.pid, "status": "running"}

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

    def file_list(self, path: str = ".") -> list[dict[str, Any]] | None:
        """List directory entries within the workspace.

        Args:
            path: Relative path to the directory within the workspace (default '.').

        Returns:
            List of dicts with 'name', 'type' ('file'/'dir'), and 'size' (for files),
            or None if the path is invalid, escapes the workspace, or is not a directory.
        """
        resolved = self._resolve_path(path)
        if resolved is None or not resolved.is_dir():
            return None

        entries: list[dict[str, Any]] = []
        for item in sorted(resolved.iterdir()):
            if item.is_dir():
                entries.append({"name": item.name, "type": "dir"})
            else:
                entries.append(
                    {"name": item.name, "type": "file", "size": item.stat().st_size}
                )
        return entries

    def file_glob(
        self,
        pattern: str,
        path: str = ".",
        exclude: list[str] | None = None,
        type_filter: str = "file",
        include_ignored: bool = False,
    ) -> FileGlobResult | None:
        """Match files using a glob pattern within the workspace.

        Args:
            pattern: Glob pattern (e.g. '*.py', '**/*.py').
            path: Relative path to the base directory (default '.').
            exclude: List of fnmatch patterns to exclude from results.
            type_filter: Filter by entry type: 'file', 'dir', or 'any'.
            include_ignored: Include normally-excluded directories (default False).

        Returns:
            FileGlobResult with matches (capped list) and total_files (real count),
            or None if the base path is not found or escapes workspace.
        """
        resolved = self._resolve_path(path)
        if resolved is None or not resolved.is_dir():
            return None

        excluded_dirs: set[str] = (
            set() if include_ignored else set(self._GLOB_EXCLUDED_DIRS)
        )

        matches: list[str] = []
        total = 0
        for match in sorted(resolved.glob(pattern)):
            rel = match.relative_to(resolved)
            rel_parts = rel.parts

            # Skip entries within excluded directories (check all path parts)
            if any(part in excluded_dirs for part in rel_parts):
                continue

            rel_str = rel.as_posix()

            # Apply custom exclude patterns against both full relative path and filename
            if exclude and any(
                fnmatch.fnmatch(rel_str, pat) or fnmatch.fnmatch(rel.name, pat)
                for pat in exclude
            ):
                continue

            # Apply type_filter
            if type_filter == "file" and not match.is_file():
                continue
            if type_filter == "dir" and not match.is_dir():
                continue
            # type_filter == "any" → no filter

            total += 1
            if total <= self._GLOB_MAX_RESULTS:
                matches.append(rel_str)

        return FileGlobResult(matches=matches, total_files=total)

    async def file_grep(  # type: ignore[override]
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
        """Search file contents using ripgrep within the workspace.

        Args:
            pattern: Regular expression pattern to search for.
            path: Relative path to a file or directory (default '.').
            output_mode: One of 'files_with_matches', 'count', 'content'.
            glob_pattern: Glob pattern to filter files (e.g. '*.py').
            file_type: File type filter (e.g. 'py', 'js').
            after_context: Lines of context after each match (content mode only).
            before_context: Lines of context before each match (content mode only).
            context: Lines of context around each match (content mode only).
            case_insensitive: Perform case-insensitive search.
            line_numbers: Include line numbers in content mode output.
            head_limit: Maximum number of results to return.
            offset: Number of results to skip before returning.
            include_ignored: Include normally-excluded directories in search.
            multiline: Enable multiline matching.

        Returns:
            Dict with 'matches' list and optional 'total_matches' count,
            or None if path escapes the workspace.
        """
        resolved = self._resolve_path(path)
        if resolved is None:
            return None

        # Compute relative path from workspace_dir for rg
        rel_path = resolved.relative_to(self.workspace_dir)

        cmd = ["rg", "--no-heading"]

        # Output mode flags
        if output_mode == "files_with_matches":
            cmd.append("--files-with-matches")
        elif output_mode == "count":
            cmd.append("--count")
        # content mode: default rg output, no extra flag

        # Default exclusions (unless include_ignored)
        if not include_ignored:
            for excluded_dir in self._GREP_EXCLUDED_DIRS:
                cmd.extend(["--glob", f"!{excluded_dir}"])

        # Glob filter
        if glob_pattern is not None:
            cmd.extend(["--glob", glob_pattern])

        # File type filter
        if file_type is not None:
            cmd.extend(["--type", file_type])

        # Case insensitive
        if case_insensitive:
            cmd.append("--ignore-case")

        # Multiline
        if multiline:
            cmd.extend(["--multiline", "--multiline-dotall"])

        # Context options (content mode only)
        if output_mode == "content":
            if line_numbers:
                cmd.append("--line-number")
            if context is not None:
                cmd.extend(["--context", str(context)])
            else:
                if after_context is not None:
                    cmd.extend(["--after-context", str(after_context)])
                if before_context is not None:
                    cmd.extend(["--before-context", str(before_context)])

        # Pattern and search path
        cmd.extend([pattern, str(rel_path)])

        # Execute rg
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workspace_dir),
        )
        stdout_bytes, _ = await process.communicate()
        output = stdout_bytes.decode("utf-8", errors="replace")

        # Parse output into list of matches
        all_matches = self._parse_grep_output(output, output_mode)
        total = len(all_matches)

        if total == 0:
            return {"matches": []}

        # Apply offset + head_limit pagination
        page = all_matches[offset:]
        if head_limit is not None:
            page = page[:head_limit]
        else:
            default_limit = self._GREP_HEAD_LIMITS.get(output_mode, 500)
            page = page[:default_limit]

        return {"matches": page, "total_matches": total}

    def _parse_grep_output(self, output: str, output_mode: str) -> list[Any]:
        """Parse ripgrep output into a list of matches by output mode.

        Args:
            output: Raw stdout from rg.
            output_mode: One of 'files_with_matches', 'count', 'content'.

        Returns:
            For files_with_matches: list of relative path strings.
            For count: list of {'file', 'count'} dicts.
            For content: list of {'file', 'line', 'content'} dicts.
        """
        lines = [line for line in output.splitlines() if line.strip()]
        results: list[Any] = []

        if output_mode == "files_with_matches":
            for line in lines:
                path = line.strip()
                if path.startswith("./"):
                    path = path[2:]
                results.append(path)

        elif output_mode == "count":
            for line in lines:
                line = line.strip()
                if ":" not in line:
                    continue
                # Format: file:count — split from right to handle paths with colons
                colon_idx = line.rfind(":")
                file_path = line[:colon_idx]
                count_str = line[colon_idx + 1 :]
                if file_path.startswith("./"):
                    file_path = file_path[2:]
                try:
                    results.append({"file": file_path, "count": int(count_str)})
                except ValueError:
                    continue

        elif output_mode == "content":
            for line in lines:
                line = line.strip()
                # Format: file:line_number:content (with --no-heading --line-number)
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                file_path = parts[0]
                if file_path.startswith("./"):
                    file_path = file_path[2:]
                try:
                    line_num = int(parts[1])
                except ValueError:
                    continue
                results.append(
                    {"file": file_path, "line": line_num, "content": parts[2]}
                )

        return results

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
