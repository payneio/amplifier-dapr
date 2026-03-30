"""FastAPI service for svc-machine — exposes /exec, /healthz, /describe endpoints."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_machine.local_backend import LocalBackend


class ExecRequest(BaseModel):
    """Request body for POST /exec."""

    command: str
    timeout: int = 30
    working_dir: str | None = None


class ExecResponse(BaseModel):
    """Response body for POST /exec."""

    stdout: str
    stderr: str
    exit_code: int


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


class FileGrepRequest(BaseModel):
    """Request body for POST /files/grep."""

    pattern: str
    path: str = "."


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

    @app.post("/exec")
    async def exec_command(request: ExecRequest) -> ExecResponse:
        """Execute a shell command within the workspace directory."""
        try:
            result = await backend.exec(
                command=request.command,
                timeout=request.timeout,
                working_dir=request.working_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ExecResponse(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
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
        matches = backend.file_glob(request.pattern, request.path)
        if matches is None:
            raise HTTPException(status_code=404, detail="Base path not found")
        return {"matches": matches}

    @app.post("/files/grep")
    def grep_files(request: FileGrepRequest) -> dict:
        """Search file contents with a regex pattern within the workspace."""
        matches = backend.file_grep(request.pattern, request.path)
        if matches is None:
            raise HTTPException(status_code=404, detail="Path not found")
        return {"matches": matches}

    return app


_workspace = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
app = create_machine_app(workspace_dir=_workspace)
