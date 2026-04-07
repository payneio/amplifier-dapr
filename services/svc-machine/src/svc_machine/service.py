"""FastAPI service for svc-machine — exposes /exec, /healthz, /describe endpoints."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from amplifier_service_sdk.models import ToolCapability
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_machine.driver import MachineDriver
from svc_machine.instance_manager import InstanceManager, InstanceNotFoundError
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


class CreateInstanceRequest(BaseModel):
    """Request body for POST /instances."""

    driver_type: str = "local"
    config: dict = {}


class CreateInstanceResponse(BaseModel):
    """Response body for POST /instances."""

    instance_id: str


async def _run_exec(
    driver: MachineDriver, request: ExecRequest, safety: SafetyValidator
) -> ExecResponse | JSONResponse:
    """Execute a command on a driver with safety validation, background support, and truncation.

    Shared implementation for both the flat /exec endpoint and the
    instance-scoped /instances/{id}/exec endpoint. The only difference between
    the two callers is the driver they supply (global backend vs instance driver).
    """
    allowed, reason = safety.validate(request.command)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={"denied": True, "reason": reason},
        )

    if request.run_in_background:
        try:
            result_bg = await driver.exec_background(  # type: ignore[misc]
                command=request.command,
                working_dir=request.working_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(content=result_bg)

    try:
        result = await driver.exec(  # type: ignore[misc]
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


def create_machine_app(workspace_dir: Path) -> FastAPI:
    """Create the svc-machine FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    machine-specific /exec endpoint.

    Args:
        workspace_dir: Root directory for all subprocess execution.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(
        name="svc-machine",
        tools=[
            ToolCapability(
                name="bash",
                description="Execute shell commands",
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer", "default": 30},
                        "run_in_background": {"type": "boolean", "default": False},
                    },
                    "required": ["command"],
                },
            ),
            ToolCapability(
                name="read_file",
                description="Read file contents",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["file_path"],
                },
            ),
            ToolCapability(
                name="write_file",
                description="Write content to file",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["file_path", "content"],
                },
            ),
            ToolCapability(
                name="edit_file",
                description="Edit file by string replacement",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                        "replace_all": {"type": "boolean", "default": False},
                    },
                    "required": ["file_path", "old_string", "new_string"],
                },
            ),
            ToolCapability(
                name="grep",
                description="Search file contents with regex",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                        "output_mode": {
                            "type": "string",
                            "enum": ["files_with_matches", "content", "count"],
                        },
                    },
                    "required": ["pattern"],
                },
            ),
            ToolCapability(
                name="glob",
                description="Match files using glob patterns",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["pattern"],
                },
            ),
        ],
    )
    app = create_app(config)

    backend = LocalBackend(workspace_dir=workspace_dir)
    safety = SafetyValidator()
    instance_manager = InstanceManager()

    def _get_driver(instance_id: str) -> MachineDriver:
        """Return driver for an instance or raise HTTP 404."""
        try:
            return instance_manager.get_driver(instance_id)
        except InstanceNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"Instance {instance_id!r} not found",
            )

    @app.post("/instances", response_model=CreateInstanceResponse)
    async def create_instance(request: CreateInstanceRequest) -> CreateInstanceResponse:
        """Create a new machine instance."""
        instance_id = await instance_manager.create_instance(
            driver_type=request.driver_type,
            config=request.config,
        )
        return CreateInstanceResponse(instance_id=instance_id)

    @app.delete("/instances/{instance_id}")
    async def destroy_instance(instance_id: str) -> dict:
        """Destroy an existing machine instance."""
        try:
            await instance_manager.destroy_instance(instance_id)
        except InstanceNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"Instance {instance_id!r} not found",
            )
        return {"success": True}

    @app.post("/instances/{instance_id}/exec", response_model=None)
    async def instance_exec_command(
        instance_id: str, request: ExecRequest
    ) -> ExecResponse | JSONResponse:
        """Execute a shell command on a specific instance."""
        return await _run_exec(_get_driver(instance_id), request, safety)

    @app.post("/instances/{instance_id}/files/read")
    def instance_read_file(instance_id: str, request: FileReadRequest) -> dict:
        """Read a file on a specific instance."""
        driver = _get_driver(instance_id)
        result = driver.file_read(
            request.path, offset=request.offset, limit=request.limit
        )
        if result is None:
            raise HTTPException(status_code=404, detail="File not found")
        return {"content": result.content, "total_lines": result.total_lines}

    @app.post("/instances/{instance_id}/files/write")
    def instance_write_file(instance_id: str, request: FileWriteRequest) -> dict:
        """Write content to a file on a specific instance."""
        driver = _get_driver(instance_id)
        success = driver.file_write(request.path, request.content)
        if not success:
            raise HTTPException(status_code=403, detail="Path escapes workspace")
        return {"success": True}

    @app.post("/instances/{instance_id}/files/edit")
    def instance_edit_file(instance_id: str, request: FileEditRequest) -> dict:
        """Replace string(s) in a file on a specific instance."""
        driver = _get_driver(instance_id)
        result = driver.file_edit(
            request.path, request.old_string, request.new_string, request.replace_all
        )
        if result is None:
            raise HTTPException(status_code=404, detail="File not found")
        return {
            "success": result.success,
            "replacements_made": result.replacements_made,
        }

    @app.post("/instances/{instance_id}/files/list")
    def instance_list_files(instance_id: str, request: FileListRequest) -> dict:
        """List directory entries on a specific instance."""
        driver = _get_driver(instance_id)
        entries = driver.file_list(request.path)
        if entries is None:
            raise HTTPException(
                status_code=404, detail="Path not found or not a directory"
            )
        return {"entries": entries}

    @app.post("/instances/{instance_id}/files/glob")
    def instance_glob_files(instance_id: str, request: FileGlobRequest) -> dict:
        """Match files using a glob pattern on a specific instance."""
        driver = _get_driver(instance_id)
        result = driver.file_glob(
            request.pattern,
            request.path,
            exclude=request.exclude,
            type_filter=request.type,
            include_ignored=request.include_ignored,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Base path not found")
        return {"matches": result.matches, "total_files": result.total_files}

    @app.post("/instances/{instance_id}/files/grep")
    async def instance_grep_files(instance_id: str, request: FileGrepRequest) -> dict:
        """Search file contents with a regex pattern on a specific instance."""
        driver = _get_driver(instance_id)
        result = await driver.file_grep(  # type: ignore[misc]
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

    @app.post("/exec", response_model=None)
    async def exec_command(request: ExecRequest) -> ExecResponse | JSONResponse:
        """Execute a shell command within the workspace directory."""
        return await _run_exec(backend, request, safety)

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
