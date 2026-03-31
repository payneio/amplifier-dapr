"""FastAPI app factory for svc-mock-provider — the mock LLM provider service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ChatRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_mock_provider.provider import MockProvider


def create_mock_provider_app() -> FastAPI:
    """Create the svc-mock-provider FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    mock-provider-specific /providers/mock/complete endpoint.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(
        name="svc-mock-provider",
        providers=[{"name": "mock", "description": "Mock LLM provider for testing"}],
    )
    app = create_app(config)

    provider = MockProvider()

    @app.post("/providers/mock/complete")
    async def complete(request: ChatRequest) -> dict[str, Any]:
        """Complete a chat request using the mock provider."""
        response = await provider.complete(request)
        return response.model_dump()

    return app


app = create_mock_provider_app()
