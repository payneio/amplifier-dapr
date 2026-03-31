"""FastAPI app factory for svc-orchestrator — the Amplifier orchestrator service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import Message, RoutingTable, ToolCapability
from amplifier_service_sdk.service import ServiceConfig, create_app
from pydantic import BaseModel, Field

from svc_orchestrator.child_session import ChildSessionRequest, ChildSessionSpawner
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


class DelegateRequest(BaseModel):
    """Request model for POST /orchestrator/delegate."""

    prompt: str
    child_session_id: str = ""
    provider_name: str = "mock"
    services: list[str] = Field(default_factory=list)
    workspace_content: dict[str, str] = Field(default_factory=dict)
    agent_ref: str = "default"


class DelegateResponse(BaseModel):
    """Response model for POST /orchestrator/delegate."""

    child_session_id: str
    result: Any
    messages: list[Any] = Field(default_factory=list)


def create_orchestrator_app(dapr_url: str | None = None) -> FastAPI:
    """Create the svc-orchestrator FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    orchestrator-specific /orchestrator/execute and /orchestrator/delegate endpoints.

    Args:
        dapr_url: Base URL of the Dapr HTTP sidecar. Defaults to
                  http://localhost:{DAPR_HTTP_PORT} using the environment variable,
                  falling back to http://localhost:3500.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(
        name="svc-orchestrator",
        tools=[
            ToolCapability(
                name="delegation",
                description="Spawn child sessions via the session-service.",
            )
        ],
    )
    app = create_app(config)

    if dapr_url is None:
        port = os.environ.get("DAPR_HTTP_PORT", "3500")
        dapr_url = f"http://localhost:{port}"

    dapr = DaprClient(dapr_url=dapr_url)
    spawner = ChildSessionSpawner(dapr=dapr)

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

    @app.post("/orchestrator/delegate")
    async def delegate(request: DelegateRequest) -> dict[str, Any]:
        """Spawn a child session via the session-service."""
        child_request = ChildSessionRequest(
            prompt=request.prompt,
            child_session_id=request.child_session_id,
            provider_name=request.provider_name,
            services=request.services,
            workspace_content=request.workspace_content,
            agent_ref=request.agent_ref,
        )
        result = await spawner.spawn(child_request)
        session_id = result.get("session_id", child_request.child_session_id)
        return DelegateResponse(
            child_session_id=session_id,
            result=result,
            messages=result.get("messages", []),
        ).model_dump()

    return app


app = create_orchestrator_app()
