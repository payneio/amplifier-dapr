"""FastAPI app factory for Amplifier-compatible microservices."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from amplifier_service_sdk.content import ContentManager
from amplifier_service_sdk.models import (
    AgentCapability,
    DescribeResponse,
    HealthResponse,
    HookRegistration,
    ModeCapability,
    ToolCapability,
)


class ServiceConfig(BaseModel):
    """Configuration for an Amplifier-compatible FastAPI service."""

    name: str
    version: str = "0.1.0"
    tools: list[ToolCapability] = Field(default_factory=list)
    hooks: list[HookRegistration] = Field(default_factory=list)
    providers: list[dict[str, Any]] = Field(default_factory=list)
    content_paths: list[str] = Field(default_factory=list)
    content_dir: str | None = None
    modes: list[ModeCapability] = Field(default_factory=list)
    agents: list[AgentCapability] = Field(default_factory=list)
    behaviors: list[str] = Field(default_factory=list)


def create_app(config: ServiceConfig) -> FastAPI:
    """Create a FastAPI application wired with standard Amplifier endpoints.

    Endpoints created:
      GET /healthz      — liveness check
      GET /describe     — service capability manifest
      GET /content/{path} — serve content files safely
    """
    app = FastAPI(title=config.name, version=config.version)

    # Build optional content manager once at startup
    content_manager: ContentManager | None = None
    if config.content_dir is not None:
        content_manager = ContentManager(Path(config.content_dir))

    # ------------------------------------------------------------------
    # GET /healthz
    # ------------------------------------------------------------------

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        response = HealthResponse(
            service_name=config.name,
            version=config.version,
        )
        return response.model_dump()

    # ------------------------------------------------------------------
    # GET /describe
    # ------------------------------------------------------------------

    @app.get("/describe")
    def describe() -> dict[str, Any]:
        content_paths: list[str] = []
        if content_manager is not None:
            content_paths = content_manager.list_paths()

        response = DescribeResponse(
            name=config.name,
            version=config.version,
            tools=config.tools,
            hooks=config.hooks,
            providers=config.providers,
            content_paths=content_paths,
            modes=config.modes,
            agents=config.agents,
            behaviors=config.behaviors,
        )
        return response.model_dump()

    # ------------------------------------------------------------------
    # GET /content/{path}
    # ------------------------------------------------------------------

    @app.get("/content/{path:path}")
    def content(path: str) -> dict[str, Any]:
        if content_manager is None:
            raise HTTPException(
                status_code=404, detail="No content directory configured"
            )

        file_content = content_manager.read(path)
        if file_content is None:
            # ContentManager returns None for both missing files and path traversal.
            # Return 404 generically; callers may treat traversal attempts as 403 or 404.
            raise HTTPException(status_code=404, detail="File not found")

        return {"path": path, "content": file_content}

    return app
