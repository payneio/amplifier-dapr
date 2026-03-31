"""FastAPI app factory for svc-providers — Anthropic, OpenAI, and Azure OpenAI provider service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ChatRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_providers.anthropic_provider import AnthropicProvider
from svc_providers.azure_openai_provider import AzureOpenAIProvider
from svc_providers.openai_provider import OpenAIProvider


def create_providers_app() -> FastAPI:
    """Create the svc-providers FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and provider-specific
    /providers/{name}/complete endpoints for Anthropic, OpenAI, and Azure OpenAI.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(
        name="svc-providers",
        providers=[
            {"name": "anthropic", "description": "Anthropic Claude provider"},
            {"name": "openai", "description": "OpenAI provider"},
            {"name": "azure-openai", "description": "Azure OpenAI provider"},
        ],
    )
    app = create_app(config)

    anthropic_provider = AnthropicProvider()
    openai_provider = OpenAIProvider()
    azure_openai_provider = AzureOpenAIProvider()

    @app.post("/providers/anthropic/complete")
    async def complete_anthropic(request: ChatRequest) -> dict[str, Any]:
        """Complete a chat request using the Anthropic provider."""
        response = await anthropic_provider.complete(request)
        return response.model_dump()

    @app.post("/providers/openai/complete")
    async def complete_openai(request: ChatRequest) -> dict[str, Any]:
        """Complete a chat request using the OpenAI provider."""
        response = await openai_provider.complete(request)
        return response.model_dump()

    @app.post("/providers/azure-openai/complete")
    async def complete_azure_openai(request: ChatRequest) -> dict[str, Any]:
        """Complete a chat request using the Azure OpenAI provider."""
        response = await azure_openai_provider.complete(request)
        return response.model_dump()

    return app


app = create_providers_app()
