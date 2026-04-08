"""SSHDriver — SSH-based machine backend driver using asyncssh."""

from __future__ import annotations

import asyncio
import logging
import posixpath
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

logger = logging.getLogger(__name__)

# Use asyncssh.Error when available; fall back to OSError so the sentinel is
# always a valid exception type even when asyncssh is not installed.
_AsyncSSHError: type[Exception] = (
    asyncssh.Error  # type: ignore[union-attr]
    if asyncssh is not None
    else OSError
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
        self._sftp: Any | None = None

    async def connect(self) -> None:
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

    async def disconnect(self) -> None:
        """Close the SSH connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._sftp = None

    def _wrap_command(self, command: str, working_dir: str | None = None) -> str:
        """Prepend 'cd {working_dir} && ' to a command."""
        wd = working_dir if working_dir is not None else self.working_dir
        return f"cd {wd} && {command}"

    def _resolve_path(self, path: str) -> str:
        """Resolve a relative path against the working directory."""
        if posixpath.isabs(path):
            return path
        return posixpath.join(self.working_dir, path)

    async def _ensure_sftp(self) -> Any:
        """Get or create an SFTP client from the SSH connection."""
        if self._sftp is None:
            self._sftp = await self._conn.start_sftp_client()  # type: ignore[union-attr]
        return self._sftp

    async def exec(
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

    async def exec_background(
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

    # —— File operations ————————————————————————————————————————————————

    async def file_read(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> FileReadResult | None:
        """Read a file via SFTP; apply offset/limit to lines. Returns None on error."""
        if self._conn is None:
            raise RuntimeError("SSHDriver is not connected — call connect() first")
        try:
            sftp = await self._ensure_sftp()
            resolved = self._resolve_path(path)
            f = await sftp.open(resolved, "rb")
            try:
                raw = await f.read()
            finally:
                await f.close()
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            lines = text.splitlines()
            total_lines = len(lines)
            start = max(0, offset - 1)
            selected = lines[start:]
            if limit is not None:
                selected = selected[:limit]
            content = "\n".join(selected)
            return FileReadResult(content=content, total_lines=total_lines)
        except OSError:
            return None

    async def file_write(self, path: str, content: str) -> bool:
        """Create parent dirs (mkdir -p) and write content via SFTP. Returns True on success."""
        if self._conn is None:
            raise RuntimeError("SSHDriver is not connected — call connect() first")
        try:
            resolved = self._resolve_path(path)
            parent = posixpath.dirname(resolved)
            if parent:
                await self._conn.run(f"mkdir -p {parent}", check=False)  # type: ignore[union-attr]
            sftp = await self._ensure_sftp()
            f = await sftp.open(resolved, "wb")
            try:
                await f.write(content.encode("utf-8"))
            finally:
                await f.close()
            return True
        except (OSError, _AsyncSSHError):
            return False
        except Exception:
            logger.exception("Unexpected error in file_write")
            return False

    async def file_edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileEditResult | None:
        """Read file, replace string(s), write back. Returns FileEditResult or None."""
        if self._conn is None:
            raise RuntimeError("SSHDriver is not connected — call connect() first")
        try:
            read_result = await self.file_read(path)
            if read_result is None:
                return None
            count = read_result.content.count(old_string)
            if replace_all:
                new_content = read_result.content.replace(old_string, new_string)
            else:
                new_content = read_result.content.replace(old_string, new_string, 1)
                count = min(count, 1)
            success = await self.file_write(path, new_content)
            return FileEditResult(success=success, replacements_made=count)
        except (OSError, _AsyncSSHError):
            return None
        except Exception:
            logger.exception("Unexpected error in file_edit")
            return None

    async def file_list(self, path: str = ".") -> list[dict[str, Any]] | None:
        """List directory entries via SFTP readdir(). Returns sorted list of dicts."""
        if self._conn is None:
            raise RuntimeError("SSHDriver is not connected — call connect() first")
        try:
            sftp = await self._ensure_sftp()
            resolved = self._resolve_path(path)
            entries = await sftp.readdir(resolved)
            result = []
            for entry in entries:
                name = entry.filename if hasattr(entry, "filename") else str(entry)
                if name in (".", ".."):
                    continue
                attrs = getattr(entry, "attrs", None)
                # Determine type: check permissions bits (stat.S_ISDIR) if available
                import stat as stat_mod

                entry_type = "file"
                if (
                    attrs is not None
                    and hasattr(attrs, "permissions")
                    and attrs.permissions
                ):
                    entry_type = (
                        "dir" if stat_mod.S_ISDIR(attrs.permissions) else "file"
                    )
                result.append({"name": name, "type": entry_type})
            result.sort(key=lambda x: x["name"])
            return result
        except (OSError, _AsyncSSHError):
            return None
        except Exception:
            logger.exception("Unexpected error in file_list")
            return None

    async def file_glob(
        self,
        pattern: str,
        path: str = ".",
        exclude: list[str] | None = None,
        type_filter: str = "file",
        include_ignored: bool = False,
    ) -> FileGlobResult | None:
        """Use SSH exec 'find' command to match files. Returns FileGlobResult."""
        if self._conn is None:
            raise RuntimeError("SSHDriver is not connected — call connect() first")
        try:
            resolved = self._resolve_path(path)
            find_parts = ["find", resolved]
            if type_filter == "file":
                find_parts.extend(["-type", "f"])
            elif type_filter == "dir":
                find_parts.extend(["-type", "d"])
            find_parts.extend(["-name", pattern])
            if exclude:
                for exc in exclude:
                    find_parts.extend(["!", "-name", exc])
            cmd = " ".join(find_parts)
            exec_result = await self.exec(cmd)
            matches = [
                line.strip() for line in exec_result.stdout.splitlines() if line.strip()
            ]
            return FileGlobResult(matches=matches, total_files=len(matches))
        except (OSError, _AsyncSSHError):
            return None
        except Exception:
            logger.exception("Unexpected error in file_glob")
            return None

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
        """Build and execute rg command over SSH. Parse output with _parse_grep_output."""
        if self._conn is None:
            raise RuntimeError("SSHDriver is not connected — call connect() first")
        try:
            resolved_path = self._resolve_path(path)
            cmd_parts = ["rg"]

            if output_mode == "files_with_matches":
                cmd_parts.append("--files-with-matches")
            elif output_mode == "count":
                cmd_parts.append("--count")
            # else: content (default rg output)

            if case_insensitive:
                cmd_parts.append("-i")
            if multiline:
                cmd_parts.append("-U")
            if line_numbers and output_mode == "content":
                cmd_parts.append("-n")
            if glob_pattern:
                cmd_parts.extend(["-g", glob_pattern])
            if file_type:
                cmd_parts.extend(["--type", file_type])
            if context is not None:
                cmd_parts.extend(["-C", str(context)])
            if after_context is not None:
                cmd_parts.extend(["-A", str(after_context)])
            if before_context is not None:
                cmd_parts.extend(["-B", str(before_context)])
            if include_ignored:
                cmd_parts.append("--no-ignore")

            cmd_parts.extend([pattern, resolved_path])
            cmd = " ".join(cmd_parts)

            exec_result = await self.exec(cmd)
            raw_output = exec_result.stdout

            # Apply offset/head_limit on raw lines before parsing
            if head_limit is not None or offset > 0:
                raw_lines = raw_output.splitlines()
                raw_lines = raw_lines[offset:]
                if head_limit is not None:
                    raw_lines = raw_lines[:head_limit]
                raw_output = "\n".join(raw_lines)

            matches = SSHDriver._parse_grep_output(raw_output, output_mode)
            return {
                "matches": matches,
                "total_matches": len(matches),
            }
        except (OSError, _AsyncSSHError):
            return None
        except Exception:
            logger.exception("Unexpected error in file_grep")
            return None

    @staticmethod
    def _parse_grep_output(output: str, output_mode: str) -> list[Any]:
        """Parse rg output into structured results based on output_mode.

        files_with_matches → list of path strings
        count              → list of {"file": str, "count": int}
        content            → list of {"file": str, "line": int, "content": str}
        """
        lines = [line for line in output.splitlines() if line.strip()]

        if output_mode == "files_with_matches":
            return lines

        if output_mode == "count":
            result: list[Any] = []
            for line in lines:
                # rg count format: "path/to/file:N"
                parts = line.rsplit(":", 1)
                if len(parts) == 2:
                    try:
                        result.append({"file": parts[0], "count": int(parts[1])})
                    except ValueError:
                        pass
            return result

        # content mode: "path/to/file:LINE_NUMBER:matched content"
        result = []
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                try:
                    result.append(
                        {
                            "file": parts[0],
                            "line": int(parts[1]),
                            "content": parts[2],
                        }
                    )
                except ValueError:
                    result.append({"file": "", "line": 0, "content": line})
            else:
                result.append({"file": "", "line": 0, "content": line})
        return result
