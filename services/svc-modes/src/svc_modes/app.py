"""FastAPI app factory for svc-modes — the mode tool service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_modes.hook import ModeHooks
from svc_modes.tool import ModeTool


def create_mode_app() -> FastAPI:
    """Create the svc-modes FastAPI application."""
    mode_hooks = ModeHooks()
    mode_tool = ModeTool()
    mode_tool._mode_hooks = mode_hooks  # wire hook into tool

    config = ServiceConfig(
        name="svc-modes",
        version="0.1.0",
        tools=[
            ToolCapability(
                name=mode_tool.name,
                description=mode_tool.description,
                input_schema=mode_tool.input_schema,
            ),
        ],
    )
    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/mode/execute")
    async def execute_mode(request: ToolRequest) -> dict[str, Any]:
        result = await mode_tool.execute(request.input)
        return result.model_dump()

    return fastapi_app


app = create_mode_app()
