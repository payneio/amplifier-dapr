"""FastAPI application for the todo reminder pre-hook service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_todo_reminder.hook import TodoReminderHook


def create_todo_reminder_hook_app() -> FastAPI:
    """Create and configure the todo reminder hook FastAPI application."""
    hook = TodoReminderHook()

    service_config = ServiceConfig(
        name="svc-hooks-todo-reminder",
        hooks=[
            HookRegistration(
                name=TodoReminderHook.name,
                events=TodoReminderHook.events,
                priority=TodoReminderHook.priority,
                mode=TodoReminderHook.mode,
            )
        ],
    )

    application = create_app(service_config)

    @application.post("/hooks/todo_reminder/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return application


# Module-level app instance for uvicorn
app = create_todo_reminder_hook_app()
