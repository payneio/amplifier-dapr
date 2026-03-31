"""FastAPI app factory for svc-web — the web tool service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_web.tools import WebFetchTool, WebSearchTool


def create_web_app() -> FastAPI:
    """Create the svc-web FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    web-specific /tools/web_search/execute and /tools/web_fetch/execute endpoints.

    Returns:
        Configured FastAPI application.
    """
    search_tool = WebSearchTool()
    fetch_tool = WebFetchTool()

    config = ServiceConfig(
        name="svc-web",
        tools=[
            ToolCapability(
                name=search_tool.name,
                description=search_tool.description,
                input_schema=search_tool.input_schema,
            ),
            ToolCapability(
                name=fetch_tool.name,
                description=fetch_tool.description,
                input_schema=fetch_tool.input_schema,
            ),
        ],
    )
    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/web_search/execute")
    async def execute_web_search(request: ToolRequest) -> dict[str, Any]:
        """Search the web using DuckDuckGo."""
        result = await search_tool.execute(request.input)
        return result.model_dump()

    @fastapi_app.post("/tools/web_fetch/execute")
    async def execute_web_fetch(request: ToolRequest) -> dict[str, Any]:
        """Fetch and parse a web page."""
        result = await fetch_tool.execute(request.input)
        return result.model_dump()

    return fastapi_app


app = create_web_app()
