"""FastAPI application for the routing pre-hook service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_routing.hook import RoutingHook, load_matrix_from_file

_DEFAULT_MATRIX_PATH = Path.home() / ".amplifier" / "routing" / "balanced.yaml"


def create_routing_hook_app(matrix: dict | None = None) -> FastAPI:
    """Create and configure the routing hook FastAPI application.

    Args:
        matrix: Optional routing matrix dict with ``roles`` mapping.
                If ``None``, loads from the ``ROUTING_MATRIX_PATH`` environment
                variable, or falls back to ``~/.amplifier/routing/balanced.yaml``.
    """
    if matrix is None:
        path_str = os.environ.get("ROUTING_MATRIX_PATH", str(_DEFAULT_MATRIX_PATH))
        matrix = load_matrix_from_file(Path(path_str))

    hook = RoutingHook(matrix=matrix)

    service_config = ServiceConfig(
        name="svc-hooks-routing",
        hooks=[
            HookRegistration(
                name=RoutingHook.name,
                events=RoutingHook.events,
                priority=RoutingHook.priority,
                mode=RoutingHook.mode,
            )
        ],
    )

    application = create_app(service_config)

    @application.post("/hooks/routing/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return application


# Module-level app instance for uvicorn
app = create_routing_hook_app()
