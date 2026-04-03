"""FastAPI application for the redaction pre-hook service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_redaction.hook import RedactionHook


def create_redaction_hook_app() -> FastAPI:
    """Create and configure the redaction hook FastAPI application."""
    hook = RedactionHook()

    service_config = ServiceConfig(
        name="svc-hooks-redaction",
        hooks=[
            HookRegistration(
                name=RedactionHook.name,
                events=RedactionHook.events,
                priority=RedactionHook.priority,
                mode=RedactionHook.mode,
            )
        ],
    )

    application = create_app(service_config)

    @application.post("/hooks/redaction/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return application


# Module-level app instance for uvicorn
app = create_redaction_hook_app()
