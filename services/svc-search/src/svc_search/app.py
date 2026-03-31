"""FastAPI app factory for svc-search — the search tool service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_search.tools import GlobTool, GrepTool

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")


def create_search_app(machine_base_url: str | None = None) -> FastAPI:
    """Create the svc-search FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    search-specific /tools/grep/execute and /tools/glob/execute endpoints.

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

    grep_tool = GrepTool(machine_base_url=machine_base_url)
    glob_tool = GlobTool(machine_base_url=machine_base_url)

    config = ServiceConfig(
        name="svc-search",
        tools=[
            ToolCapability(
                name=grep_tool.name,
                description=grep_tool.description,
                input_schema=grep_tool.input_schema,
            ),
            ToolCapability(
                name=glob_tool.name,
                description=glob_tool.description,
                input_schema=glob_tool.input_schema,
            ),
        ],
    )
    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/grep/execute")
    async def execute_grep(request: ToolRequest) -> dict[str, Any]:
        """Search file contents via the machine service."""
        result = await grep_tool.execute(request.input)
        return result.model_dump()

    @fastapi_app.post("/tools/glob/execute")
    async def execute_glob(request: ToolRequest) -> dict[str, Any]:
        """Match files via the machine service."""
        result = await glob_tool.execute(request.input)
        return result.model_dump()

    return fastapi_app


app = create_search_app()
