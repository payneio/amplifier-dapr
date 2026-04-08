"""FastAPI service for svc-machine — exposes /exec, /healthz, /describe endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from amplifier_service_sdk.models import ToolCapability
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_machine.driver import MachineDriver
from svc_machine.instance_manager import InstanceManager, InstanceNotFoundError
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


class ToolDispatchRequest(BaseModel):
    """Request body for POST /tools/{name}/execute endpoints.

    Matches the payload the orchestrator sends when dispatching tool calls:
    ``{"name": "...", "input": {...}, "machine_instance_id": "optional"}``.
    """

    name: str
    input: dict[str, Any] = {}
    machine_instance_id: str | None = None


async def _run_exec(
    driver: MachineDriver, request: ExecRequest, safety: SafetyValidator
) -> ExecResponse | JSONResponse:
    """Execute a command on a driver with safety validation, background support, and truncation.

    Shared implementation for both the flat /exec endpoint and the
    instance-scoped /instances/{id}/exec endpoint. The only difference between
    the two callers is the driver they supply (per-instance vs per-route).
    """
    allowed, reason = safety.validate(request.command)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={"denied": True, "reason": reason},
        )

    if request.run_in_background:
        try:
            result_bg = await driver.exec_background(
                command=request.command,
                working_dir=request.working_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(content=result_bg)

    try:
        result = await driver.exec(
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


def create_machine_app() -> FastAPI:
    """Create the svc-machine FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    machine-specific tool execution endpoints.  All tool calls must be
    associated with a provisioned machine instance — there is no global
    fallback.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(
        name="svc-machine",
        behaviors=["machine"],
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
    async def instance_read_file(instance_id: str, request: FileReadRequest) -> dict:
        """Read a file on a specific instance."""
        driver = _get_driver(instance_id)
        result = await driver.file_read(
            request.path, offset=request.offset, limit=request.limit
        )
        if result is None:
            raise HTTPException(status_code=404, detail="File not found")
        return {"content": result.content, "total_lines": result.total_lines}

    @app.post("/instances/{instance_id}/files/write")
    async def instance_write_file(instance_id: str, request: FileWriteRequest) -> dict:
        """Write content to a file on a specific instance."""
        driver = _get_driver(instance_id)
        success = await driver.file_write(request.path, request.content)
        if not success:
            raise HTTPException(status_code=403, detail="Path escapes workspace")
        return {"success": True}

    @app.post("/instances/{instance_id}/files/edit")
    async def instance_edit_file(instance_id: str, request: FileEditRequest) -> dict:
        """Replace string(s) in a file on a specific instance."""
        driver = _get_driver(instance_id)
        result = await driver.file_edit(
            request.path, request.old_string, request.new_string, request.replace_all
        )
        if result is None:
            raise HTTPException(status_code=404, detail="File not found")
        return {
            "success": result.success,
            "replacements_made": result.replacements_made,
        }

    @app.post("/instances/{instance_id}/files/list")
    async def instance_list_files(instance_id: str, request: FileListRequest) -> dict:
        """List directory entries on a specific instance."""
        driver = _get_driver(instance_id)
        entries = await driver.file_list(request.path)
        if entries is None:
            raise HTTPException(
                status_code=404, detail="Path not found or not a directory"
            )
        return {"entries": entries}

    @app.post("/instances/{instance_id}/files/glob")
    async def instance_glob_files(instance_id: str, request: FileGlobRequest) -> dict:
        """Match files using a glob pattern on a specific instance."""
        driver = _get_driver(instance_id)
        result = await driver.file_glob(
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
        result = await driver.file_grep(
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

    # ------------------------------------------------------------------
    # Standard orchestrator dispatch routes: POST /tools/{name}/execute
    # These match the pattern used by all other tool services so the
    # orchestrator can reach them uniformly via Dapr service invocation.
    # ------------------------------------------------------------------

    def _resolve_driver(machine_instance_id: str | None) -> MachineDriver:
        """Return the driver for the given machine instance.

        Raises HTTP 400 if no instance ID is provided, or HTTP 404 if the
        instance is not found.  There is no global fallback — every tool
        call must be associated with a provisioned machine instance.
        """
        if machine_instance_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "machine_instance_id is required. "
                    "Provision an instance via POST /instances first."
                ),
            )
        try:
            return instance_manager.get_driver(machine_instance_id)
        except InstanceNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"Machine instance {machine_instance_id!r} not found.",
            )

    @app.post("/tools/bash/execute", response_model=None)
    async def tool_bash_execute(
        request: ToolDispatchRequest,
    ) -> ExecResponse | JSONResponse:
        """Execute a shell command — standard orchestrator dispatch endpoint."""
        try:
            exec_req = ExecRequest(**request.input)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        driver = _resolve_driver(request.machine_instance_id)
        return await _run_exec(driver, exec_req, safety)

    @app.post("/tools/read_file/execute")
    async def tool_read_file_execute(request: ToolDispatchRequest) -> dict:
        """Read a file — standard orchestrator dispatch endpoint.

        Falls back to directory listing when the path resolves to a directory.
        """
        file_path = request.input.get("file_path")
        if file_path is None:
            raise HTTPException(status_code=422, detail="input.file_path is required")
        offset: int = request.input.get("offset", 1)
        limit: int | None = request.input.get("limit")
        driver = _resolve_driver(request.machine_instance_id)
        # Try reading as a file first; directories raise IsADirectoryError.
        try:
            result = await driver.file_read(file_path, offset=offset, limit=limit)
        except IsADirectoryError:
            result = None
            entries = await driver.file_list(file_path)
            if entries is None:
                raise HTTPException(status_code=404, detail="Path not found")
            return {"entries": entries}
        if result is None:
            # Path doesn't exist or escapes workspace — check if it's a directory.
            entries = await driver.file_list(file_path)
            if entries is not None:
                return {"entries": entries}
            raise HTTPException(status_code=404, detail="File not found")
        return {"content": result.content, "total_lines": result.total_lines}

    @app.post("/tools/write_file/execute")
    async def tool_write_file_execute(request: ToolDispatchRequest) -> dict:
        """Write a file — standard orchestrator dispatch endpoint."""
        try:
            write_req = FileWriteRequest(
                path=request.input.get("file_path", request.input.get("path", "")),
                content=request.input["content"],
            )
        except (KeyError, ValidationError) as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        driver = _resolve_driver(request.machine_instance_id)
        success = await driver.file_write(write_req.path, write_req.content)
        if not success:
            raise HTTPException(status_code=403, detail="Path escapes workspace")
        return {"success": True}

    @app.post("/tools/edit_file/execute")
    async def tool_edit_file_execute(request: ToolDispatchRequest) -> dict:
        """Replace string(s) in a file — standard orchestrator dispatch endpoint."""
        try:
            edit_req = FileEditRequest(
                path=request.input.get("file_path", request.input.get("path", "")),
                old_string=request.input["old_string"],
                new_string=request.input["new_string"],
                replace_all=request.input.get("replace_all", False),
            )
        except (KeyError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        driver = _resolve_driver(request.machine_instance_id)
        result = await driver.file_edit(
            edit_req.path,
            edit_req.old_string,
            edit_req.new_string,
            edit_req.replace_all,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="File not found")
        return {
            "success": result.success,
            "replacements_made": result.replacements_made,
        }

    @app.post("/tools/glob/execute")
    async def tool_glob_execute(request: ToolDispatchRequest) -> dict:
        """Match files using a glob pattern — standard orchestrator dispatch endpoint."""
        try:
            glob_req = FileGlobRequest(**request.input)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        driver = _resolve_driver(request.machine_instance_id)
        result = await driver.file_glob(
            glob_req.pattern,
            glob_req.path,
            exclude=glob_req.exclude,
            type_filter=glob_req.type,
            include_ignored=glob_req.include_ignored,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Base path not found")
        return {"matches": result.matches, "total_files": result.total_files}

    @app.post("/tools/grep/execute")
    async def tool_grep_execute(request: ToolDispatchRequest) -> dict:
        """Search file contents with regex — standard orchestrator dispatch endpoint."""
        try:
            grep_req = FileGrepRequest(**request.input)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        driver = _resolve_driver(request.machine_instance_id)
        result = await driver.file_grep(
            pattern=grep_req.pattern,
            path=grep_req.path,
            output_mode=grep_req.output_mode,
            glob_pattern=grep_req.glob,
            file_type=grep_req.type,
            after_context=grep_req.after_context,
            before_context=grep_req.before_context,
            context=grep_req.context,
            case_insensitive=grep_req.case_insensitive,
            line_numbers=grep_req.line_numbers,
            head_limit=grep_req.head_limit,
            offset=grep_req.offset,
            include_ignored=grep_req.include_ignored,
            multiline=grep_req.multiline,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Path not found")
        return result

    return app


app = create_machine_app()
