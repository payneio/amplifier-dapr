"""FastAPI application for the approval pre-hook service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_approval.hook import ApprovalHook


def create_approval_hook_app(config: dict[str, Any] | None = None) -> FastAPI:
    """Create and configure the approval hook FastAPI application.

    Args:
        config: Optional configuration dict with ``deny_tools`` list.
                If ``None``, reads from the ``DENY_TOOLS`` environment variable
                (comma-separated list of glob patterns).
    """
    if config is None:
        raw = os.environ.get("DENY_TOOLS", "")
        deny_tools = [t.strip() for t in raw.split(",") if t.strip()] if raw else []
        config = {"deny_tools": deny_tools}

    hook = ApprovalHook(config=config)

    service_config = ServiceConfig(
        name="svc-hooks-approval",
        hooks=[
            HookRegistration(
                name=ApprovalHook.name,
                events=ApprovalHook.events,
                priority=ApprovalHook.priority,
                mode=ApprovalHook.mode,
            )
        ],
    )

    application = create_app(service_config)

    @application.post("/hooks/approval/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return application


# Module-level app instance for uvicorn
app = create_approval_hook_app()
