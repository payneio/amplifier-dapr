"""FastAPI app factory for svc-todo — the todo tool service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_todo.tool import TodoTool


def create_todo_app() -> FastAPI:
    """Create the svc-todo FastAPI application."""
    todo_tool = TodoTool()

    config = ServiceConfig(
        name="svc-todo",
        version="0.1.0",
        tools=[
            ToolCapability(
                name=todo_tool.name,
                description=todo_tool.description,
                input_schema=todo_tool.input_schema,
            ),
        ],
    )
    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/todo/execute")
    async def execute_todo(request: ToolRequest) -> dict[str, Any]:
        """Execute a todo operation."""
        result = await todo_tool.execute(request.input)
        return result.model_dump()

    return fastapi_app


app = create_todo_app()
