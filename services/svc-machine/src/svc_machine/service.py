"""FastAPI service for svc-machine — exposes /exec, /healthz, /describe endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_machine.local_backend import LocalBackend


class ExecRequest(BaseModel):
    """Request body for POST /exec."""

    command: str
    timeout: int = 30
    working_dir: str | None = None


class ExecResponse(BaseModel):
    """Response body for POST /exec."""

    stdout: str
    stderr: str
    exit_code: int


def create_machine_app(workspace_dir: Path) -> FastAPI:
    """Create the svc-machine FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    machine-specific /exec endpoint.

    Args:
        workspace_dir: Root directory for all subprocess execution.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(name="svc-machine")
    app = create_app(config)

    backend = LocalBackend(workspace_dir=workspace_dir)

    @app.post("/exec")
    async def exec_command(request: ExecRequest) -> ExecResponse:
        """Execute a shell command within the workspace directory."""
        result = await backend.exec(
            command=request.command,
            timeout=request.timeout,
            working_dir=request.working_dir,
        )
        return ExecResponse(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
        )

    return app
