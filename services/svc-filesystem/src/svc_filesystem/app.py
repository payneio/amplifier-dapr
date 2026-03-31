"""FastAPI app factory for svc-filesystem — the filesystem tool service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_filesystem.tools import EditFileTool, ReadFileTool, WriteFileTool

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")


def create_filesystem_app(machine_base_url: str | None = None) -> FastAPI:
    """Create the svc-filesystem FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    filesystem-specific /tools/read_file/execute, /tools/write_file/execute,
    and /tools/edit_file/execute endpoints.

    Args:
        machine_base_url: Base URL for the machine service.  Defaults to the
            Dapr sidecar invocation URL for svc-machine.

    Returns:
        Configured FastAPI application.
    """
    if machine_base_url is None:
        machine_base_url = (
            f"http://localhost:{_DAPR_HTTP_PORT}/v1.0/invoke/svc-machine/method"
        )

    read_tool = ReadFileTool(machine_base_url=machine_base_url)
    write_tool = WriteFileTool(machine_base_url=machine_base_url)
    edit_tool = EditFileTool(machine_base_url=machine_base_url)

    config = ServiceConfig(
        name="svc-filesystem",
        tools=[
            ToolCapability(
                name=read_tool.name,
                description=read_tool.description,
                input_schema=read_tool.input_schema,
            ),
            ToolCapability(
                name=write_tool.name,
                description=write_tool.description,
                input_schema=write_tool.input_schema,
            ),
            ToolCapability(
                name=edit_tool.name,
                description=edit_tool.description,
                input_schema=edit_tool.input_schema,
            ),
        ],
    )
    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/read_file/execute")
    async def execute_read_file(request: ToolRequest) -> dict[str, Any]:
        """Read a file via the machine service."""
        result = await read_tool.execute(request.input)
        return result.model_dump()

    @fastapi_app.post("/tools/write_file/execute")
    async def execute_write_file(request: ToolRequest) -> dict[str, Any]:
        """Write a file via the machine service."""
        result = await write_tool.execute(request.input)
        return result.model_dump()

    @fastapi_app.post("/tools/edit_file/execute")
    async def execute_edit_file(request: ToolRequest) -> dict[str, Any]:
        """Edit a file via the machine service."""
        result = await edit_tool.execute(request.input)
        return result.model_dump()

    return fastapi_app


app = create_filesystem_app()
