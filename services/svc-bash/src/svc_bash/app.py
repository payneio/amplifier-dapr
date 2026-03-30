"""FastAPI app factory for svc-bash — the bash tool service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_bash.tool import BashTool

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")


def create_bash_app(machine_base_url: str | None = None) -> FastAPI:
    """Create the svc-bash FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    bash-specific /tools/bash/execute endpoint.

    Args:
        machine_base_url: Base URL for the machine service.  Defaults to the
            Dapr sidecar invocation URL for svc-machine.

    Returns:
        Configured FastAPI application.
    """
    if machine_base_url is None:
        machine_base_url = (
            f"http://localhost:{_DAPR_HTTP_PORT}/v1.0/invoke/svc-machine/method"
        )

    tool = BashTool(machine_base_url=machine_base_url)

    config = ServiceConfig(
        name="svc-bash",
        tools=[
            ToolCapability(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
        ],
    )
    app = create_app(config)

    @app.post("/tools/bash/execute")
    async def execute_bash(request: ToolRequest) -> dict[str, Any]:
        """Execute a bash command via the machine service."""
        result = await tool.execute(request.input)
        return result.model_dump()

    return app


app = create_bash_app()
