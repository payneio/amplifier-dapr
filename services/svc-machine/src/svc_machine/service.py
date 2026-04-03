"""FastAPI service for svc-machine — exposes /exec, /healthz, /describe endpoints."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_machine.local_backend import LocalBackend
from svc_machine.safety import SafetyValidator
from svc_machine.truncation import truncate_output


class ExecRequest(BaseModel):
    """Request body for POST /exec."""

    command: str
    timeout: int = 30
    working_dir: str | None = None
    run_in_background: bool = False


class ExecResponse(BaseModel):
    """Response body for POST /exec."""

    stdout: str
    stderr: str
    exit_code: int
    truncated: bool = False


class FileReadRequest(BaseModel):
    """Request body for POST /files/read."""

    path: str
    offset: int = 1
    limit: int | None = None


class FileWriteRequest(BaseModel):
    """Request body for POST /files/write."""

    path: str
    content: str


class FileEditRequest(BaseModel):
    """Request body for POST /files/edit."""

    path: str
    old_string: str
    new_string: str
    replace_all: bool = False


class FileListRequest(BaseModel):
    """Request body for POST /files/list."""

    path: str = "."


class FileGlobRequest(BaseModel):
    """Request body for POST /files/glob."""

    pattern: str
    path: str = "."
    exclude: list[str] | None = None
    type: str = "file"
    include_ignored: bool = False


class FileGrepRequest(BaseModel):
    """Request body for POST /files/grep."""

    pattern: str
    path: str = "."
    output_mode: str = "files_with_matches"
    glob: str | None = None
    type: str | None = None
    after_context: int | None = None
    before_context: int | None = None
    context: int | None = None
    case_insensitive: bool = False
    line_numbers: bool = True
    head_limit: int | None = None
    offset: int = 0
    include_ignored: bool = False
    multiline: bool = False


def create_machine_app(workspace_dir: Path) -> FastAPI:
    """Create the svc-machine FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    machine-specific /exec endpoint.

    Args:
        workspace_dir: Root directory for all subprocess execution.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(name="svc-machine")
    app = create_app(config)

    backend = LocalBackend(workspace_dir=workspace_dir)
    safety = SafetyValidator()

    @app.post("/exec", response_model=None)
    async def exec_command(request: ExecRequest) -> ExecResponse | JSONResponse:
        """Execute a shell command within the workspace directory."""
        # Safety check
        allowed, reason = safety.validate(request.command)
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail={"denied": True, "reason": reason},
            )

        # Background execution
        if request.run_in_background:
            try:
                result_bg = await backend.exec_background(
                    command=request.command,
                    working_dir=request.working_dir,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return JSONResponse(content=result_bg)

        # Normal execution with truncation
        try:
            result = await backend.exec(
                command=request.command,
                timeout=request.timeout,
                working_dir=request.working_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        stdout, stdout_truncated = truncate_output(result.stdout)
        stderr, stderr_truncated = truncate_output(result.stderr)

        return ExecResponse(
            stdout=stdout,
            stderr=stderr,
            exit_code=result.exit_code,
            truncated=stdout_truncated or stderr_truncated,
        )

    @app.post("/files/read")
    def read_file(request: FileReadRequest) -> dict:
        """Read a file within the workspace."""
        result = backend.file_read(
            request.path, offset=request.offset, limit=request.limit
        )
        if result is None:
            raise HTTPException(status_code=404, detail="File not found")
        return {"content": result.content, "total_lines": result.total_lines}

    @app.post("/files/write")
    def write_file(request: FileWriteRequest) -> dict:
        """Write content to a file within the workspace."""
        success = backend.file_write(request.path, request.content)
        if not success:
            raise HTTPException(status_code=403, detail="Path escapes workspace")
        return {"success": True}

    @app.post("/files/edit")
    def edit_file(request: FileEditRequest) -> dict:
        """Replace string(s) in a file within the workspace."""
        result = backend.file_edit(
            request.path, request.old_string, request.new_string, request.replace_all
        )
        if result is None:
            raise HTTPException(status_code=404, detail="File not found")
        return {
            "success": result.success,
            "replacements_made": result.replacements_made,
        }

    @app.post("/files/list")
    def list_files(request: FileListRequest) -> dict:
        """List directory entries within the workspace."""
        entries = backend.file_list(request.path)
        if entries is None:
            raise HTTPException(
                status_code=404, detail="Path not found or not a directory"
            )
        return {"entries": entries}

    @app.post("/files/glob")
    def glob_files(request: FileGlobRequest) -> dict:
        """Match files using a glob pattern within the workspace."""
        result = backend.file_glob(
            request.pattern,
            request.path,
            exclude=request.exclude,
            type_filter=request.type,
            include_ignored=request.include_ignored,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Base path not found")
        return {"matches": result.matches, "total_files": result.total_files}

    @app.post("/files/grep")
    async def grep_files(request: FileGrepRequest) -> dict:
        """Search file contents with a regex pattern within the workspace."""
        result = await backend.file_grep(
            pattern=request.pattern,
            path=request.path,
            output_mode=request.output_mode,
            glob_pattern=request.glob,
            file_type=request.type,
            after_context=request.after_context,
            before_context=request.before_context,
            context=request.context,
            case_insensitive=request.case_insensitive,
            line_numbers=request.line_numbers,
            head_limit=request.head_limit,
            offset=request.offset,
            include_ignored=request.include_ignored,
            multiline=request.multiline,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Path not found")
        return result

    return app


_workspace = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
app = create_machine_app(workspace_dir=_workspace)
