"""FastAPI app factory for svc-providers — the Anthropic Claude provider service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ChatRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_providers.anthropic_provider import AnthropicProvider


def create_providers_app() -> FastAPI:
    """Create the svc-providers FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    Anthropic-specific /providers/anthropic/complete endpoint.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(
        name="svc-providers",
        providers=[{"name": "anthropic", "description": "Anthropic Claude provider"}],
    )
    app = create_app(config)

    provider = AnthropicProvider()

    @app.post("/providers/anthropic/complete")
    async def complete(request: ChatRequest) -> dict[str, Any]:
        """Complete a chat request using the Anthropic provider."""
        response = await provider.complete(request)
        return response.model_dump()

    return app


app = create_providers_app()
