"""FastAPI app factory for svc-providers — all LLM provider implementations."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ChatRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_providers.anthropic_provider import AnthropicProvider
from svc_providers.azure_openai_provider import AzureOpenAIProvider
from svc_providers.gemini_provider import GeminiProvider
from svc_providers.github_copilot_provider import GitHubCopilotProvider
from svc_providers.ollama_provider import OllamaProvider
from svc_providers.openai_provider import OpenAIProvider
from svc_providers.vllm_provider import VllmProvider


def create_providers_app() -> FastAPI:
    """Create the svc-providers FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and provider-specific
    /providers/{name}/complete endpoints for all providers.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(
        name="svc-providers",
        providers=[
            {"name": "anthropic", "description": "Anthropic Claude provider"},
            {"name": "openai", "description": "OpenAI provider"},
            {"name": "azure-openai", "description": "Azure OpenAI provider"},
            {"name": "gemini", "description": "Google Gemini provider"},
            {"name": "ollama", "description": "Ollama local model provider"},
            {"name": "vllm", "description": "vLLM OpenAI-compatible provider"},
            {"name": "github-copilot", "description": "GitHub Copilot provider"},
        ],
    )
    app = create_app(config)

    anthropic_provider = AnthropicProvider()
    openai_provider = OpenAIProvider()
    azure_openai_provider = AzureOpenAIProvider()
    gemini_provider = GeminiProvider()
    ollama_provider = OllamaProvider()
    vllm_provider = VllmProvider()
    github_copilot_provider = GitHubCopilotProvider()

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

    @app.post("/providers/gemini/complete")
    async def complete_gemini(request: ChatRequest) -> dict[str, Any]:
        """Complete a chat request using the Gemini provider."""
        response = await gemini_provider.complete(request)
        return response.model_dump()

    @app.post("/providers/ollama/complete")
    async def complete_ollama(request: ChatRequest) -> dict[str, Any]:
        """Complete a chat request using the Ollama provider."""
        response = await ollama_provider.complete(request)
        return response.model_dump()

    @app.post("/providers/vllm/complete")
    async def complete_vllm(request: ChatRequest) -> dict[str, Any]:
        """Complete a chat request using the vLLM provider."""
        response = await vllm_provider.complete(request)
        return response.model_dump()

    @app.post("/providers/github-copilot/complete")
    async def complete_github_copilot(request: ChatRequest) -> dict[str, Any]:
        """Complete a chat request using the GitHub Copilot provider."""
        response = await github_copilot_provider.complete(request)
        return response.model_dump()

    return app


app = create_providers_app()
