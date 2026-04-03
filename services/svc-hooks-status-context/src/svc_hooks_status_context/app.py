"""FastAPI application for the status context pre-hook service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_status_context.hook import StatusContextHook


def create_status_context_hook_app() -> FastAPI:
    """Create and configure the status context hook FastAPI application."""
    hook = StatusContextHook()

    service_config = ServiceConfig(
        name="svc-hooks-status-context",
        hooks=[
            HookRegistration(
                name=StatusContextHook.name,
                events=StatusContextHook.events,
                priority=StatusContextHook.priority,
                mode=StatusContextHook.mode,
            )
        ],
    )

    application = create_app(service_config)

    @application.post("/hooks/status_context/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return application


# Module-level app instance for uvicorn
app = create_status_context_hook_app()
