"""FastAPI app factory for svc-orchestrator — the Amplifier orchestrator service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import Message, RoutingTable
from amplifier_service_sdk.service import ServiceConfig, create_app
from pydantic import BaseModel

from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator


class ExecuteRequest(BaseModel):
    """Request model for POST /orchestrator/execute."""

    system_prompt: str
    messages: list[Message]
    config: dict[str, Any] = {}
    routing_table: RoutingTable
    session_id: str = ""


class ExecuteResponse(BaseModel):
    """Response model for POST /orchestrator/execute."""

    result: str
    messages: list[Message]


def create_orchestrator_app(dapr_url: str | None = None) -> FastAPI:
    """Create the svc-orchestrator FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    orchestrator-specific /orchestrator/execute endpoint.

    Args:
        dapr_url: Base URL of the Dapr HTTP sidecar. Defaults to
                  http://localhost:{DAPR_HTTP_PORT} using the environment variable,
                  falling back to http://localhost:3500.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(name="svc-orchestrator")
    app = create_app(config)

    if dapr_url is None:
        port = os.environ.get("DAPR_HTTP_PORT", "3500")
        dapr_url = f"http://localhost:{port}"

    dapr = DaprClient(dapr_url=dapr_url)

    @app.post("/orchestrator/execute")
    async def execute(request: ExecuteRequest) -> dict[str, Any]:
        """Execute an orchestration session."""
        orch = Orchestrator(dapr=dapr)
        result, messages = await orch.execute(
            system_prompt=request.system_prompt,
            messages=request.messages,
            config=request.config,
            routing_table=request.routing_table,
            session_id=request.session_id,
        )
        return ExecuteResponse(result=result, messages=messages).model_dump()

    return app


app = create_orchestrator_app()
