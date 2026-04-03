"""FastAPI app factory for svc-todo — the todo tool service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import (
    HookEvent,
    HookRegistration,
    ToolCapability,
    ToolRequest,
)
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_todo.hooks import TodoDisplayHook, TodoReminderHook
from svc_todo.tool import TodoTool


def create_todo_app() -> FastAPI:
    """Create the svc-todo FastAPI application."""
    todo_tool = TodoTool()
    todo_reminder_hook = TodoReminderHook()
    todo_display_hook = TodoDisplayHook()

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
        hooks=[
            HookRegistration(
                name=TodoReminderHook.name,
                events=TodoReminderHook.events,
                priority=TodoReminderHook.priority,
                mode=TodoReminderHook.mode,
            ),
            HookRegistration(
                name=TodoDisplayHook.name,
                events=TodoDisplayHook.events,
                priority=TodoDisplayHook.priority,
                mode=TodoDisplayHook.mode,
            ),
        ],
    )
    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/todo/execute")
    async def execute_todo(request: ToolRequest) -> dict[str, Any]:
        """Execute a todo operation."""
        result = await todo_tool.execute(request.input)
        return result.model_dump()

    @fastapi_app.post("/hooks/todo_reminder/invoke")
    async def invoke_todo_reminder(event: HookEvent) -> dict[str, Any]:
        """Invoke the todo reminder hook."""
        result = await todo_reminder_hook.handle(event.event, event.data)
        return result.model_dump()

    @fastapi_app.post("/hooks/todo_display/invoke")
    async def invoke_todo_display(event: HookEvent) -> dict[str, Any]:
        """Invoke the todo display hook."""
        result = await todo_display_hook.handle(event.event, event.data)
        return result.model_dump()

    @fastapi_app.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return fastapi_app


app = create_todo_app()
