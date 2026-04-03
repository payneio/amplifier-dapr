"""FastAPI app factory for svc-delegation — the delegation tool service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_delegation.tool import DelegateTool


def create_delegation_app(
    orchestrator_base_url: str | None = None,
    session_service_base_url: str | None = None,
) -> FastAPI:
    """Create the svc-delegation FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    delegation-specific /tools/delegate/execute endpoint.

    Args:
        orchestrator_base_url: Base URL for the orchestrator service.
            If None, uses the Dapr service invocation URL for svc-orchestrator.
        session_service_base_url: Base URL for the session service (for context fetching).
            If None, uses the Dapr service invocation URL for svc-session.

    Returns:
        Configured FastAPI application.
    """
    if orchestrator_base_url is None:
        dapr_port = os.environ.get("DAPR_HTTP_PORT", "3500")
        orchestrator_base_url = (
            f"http://localhost:{dapr_port}/v1.0/invoke/svc-orchestrator/method"
        )

    if session_service_base_url is None:
        dapr_port = os.environ.get("DAPR_HTTP_PORT", "3500")
        session_service_base_url = (
            f"http://localhost:{dapr_port}/v1.0/invoke/session-service/method"
        )

    tool = DelegateTool(
        orchestrator_base_url=orchestrator_base_url,
        session_service_base_url=session_service_base_url,
    )

    config = ServiceConfig(
        name="svc-delegation",
        tools=[
            ToolCapability(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            ),
        ],
    )

    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/delegate/execute")
    async def execute_delegate(request: ToolRequest) -> dict[str, Any]:
        """Spawn a child agent session via the orchestrator."""
        result = await tool.execute(request.input)
        return result.model_dump()

    return fastapi_app


app = create_delegation_app()
