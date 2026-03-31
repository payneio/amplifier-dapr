"""Tests for OpenAIProvider — name, mocked complete with text response and usage."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_service_sdk.models import ChatRequest, ChatResponse, Message, TokenUsage
from svc_providers.base import BaseProvider


class TestOpenAIProviderName:
    """test_provider_name: OpenAIProvider.name == 'openai'."""

    def test_provider_name(self) -> None:
        """OpenAIProvider.name attribute is 'openai'."""
        from svc_providers.openai_provider import OpenAIProvider  # noqa: PLC0415

        provider = OpenAIProvider(config={"api_key": "test-key"})
        assert provider.name == "openai"

    def test_provider_is_base_provider(self) -> None:
        """OpenAIProvider inherits from BaseProvider."""
        from svc_providers.openai_provider import OpenAIProvider  # noqa: PLC0415

        provider = OpenAIProvider(config={"api_key": "test-key"})
        assert isinstance(provider, BaseProvider)


class MockOpenAIChoice:
    """Simulates an OpenAI Chat Completions choice."""

    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = MagicMock()
        self.message.content = content
        self.message.tool_calls = None
        self.finish_reason = finish_reason


class MockOpenAIUsage:
    """Simulates an OpenAI API usage object."""

    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 20) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class MockOpenAIResponse:
    """Simulates an OpenAI Chat Completions response."""

    def __init__(
        self,
        content: str,
        finish_reason: str = "stop",
        prompt_tokens: int = 10,
        completion_tokens: int = 20,
        model: str = "gpt-4o",
    ) -> None:
        self.choices = [MockOpenAIChoice(content=content, finish_reason=finish_reason)]
        self.usage = MockOpenAIUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
        self.model = model


class TestCompleteWithMockedTextResponse:
    """test_complete: complete() with mocked client returns ChatResponse with correct text."""

    @pytest.fixture
    def provider(self) -> Any:
        """Provider with injected AsyncMock client."""
        from svc_providers.openai_provider import OpenAIProvider  # noqa: PLC0415

        p = OpenAIProvider(config={"api_key": "test-key"})
        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MockOpenAIResponse(
                content="Hello from OpenAI!",
                finish_reason="stop",
                prompt_tokens=10,
                completion_tokens=5,
            )
        )
        p._client = mock_client
        return p

    @pytest.mark.asyncio
    async def test_complete_returns_chat_response(self, provider: Any) -> None:
        """complete() returns a ChatResponse instance."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert isinstance(response, ChatResponse)

    @pytest.mark.asyncio
    async def test_complete_returns_correct_text(self, provider: Any) -> None:
        """complete() returns ChatResponse with text from mocked response."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.content == "Hello from OpenAI!"

    @pytest.mark.asyncio
    async def test_complete_usage_is_token_usage(self, provider: Any) -> None:
        """complete() returns ChatResponse with TokenUsage instance."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.usage is not None
        assert isinstance(response.usage, TokenUsage)

    @pytest.mark.asyncio
    async def test_complete_usage_input_tokens(self, provider: Any) -> None:
        """complete() maps prompt_tokens to input_tokens."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.usage is not None
        assert response.usage.input_tokens == 10

    @pytest.mark.asyncio
    async def test_complete_usage_output_tokens(self, provider: Any) -> None:
        """complete() maps completion_tokens to output_tokens."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.usage is not None
        assert response.usage.output_tokens == 5

    @pytest.mark.asyncio
    async def test_complete_stop_reason(self, provider: Any) -> None:
        """complete() sets stop_reason from finish_reason."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.stop_reason == "stop"


class TestAzureOpenAIProviderName:
    """test_azure_provider_name: AzureOpenAIProvider.name == 'azure-openai'."""

    def test_provider_name(self) -> None:
        """AzureOpenAIProvider.name attribute is 'azure-openai'."""
        from svc_providers.azure_openai_provider import AzureOpenAIProvider  # noqa: PLC0415

        provider = AzureOpenAIProvider(
            config={
                "api_key": "test-key",
                "azure_endpoint": "https://test.openai.azure.com",
                "api_version": "2024-02-01",
            }
        )
        assert provider.name == "azure-openai"

    def test_azure_provider_inherits_openai_provider(self) -> None:
        """AzureOpenAIProvider inherits from OpenAIProvider."""
        from svc_providers.azure_openai_provider import AzureOpenAIProvider  # noqa: PLC0415
        from svc_providers.openai_provider import OpenAIProvider  # noqa: PLC0415

        provider = AzureOpenAIProvider(
            config={
                "api_key": "test-key",
                "azure_endpoint": "https://test.openai.azure.com",
                "api_version": "2024-02-01",
            }
        )
        assert isinstance(provider, OpenAIProvider)


class TestAppDescribeIncludesOpenAIProviders:
    """test_app_describe: GET /describe includes openai and azure-openai in providers list."""

    def test_describe_includes_openai(self) -> None:
        """GET /describe lists openai in providers."""
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from svc_providers.app import create_providers_app  # noqa: PLC0415

        app = create_providers_app()
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        provider_names = [p["name"] for p in data["providers"]]
        assert "openai" in provider_names

    def test_describe_includes_azure_openai(self) -> None:
        """GET /describe lists azure-openai in providers."""
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from svc_providers.app import create_providers_app  # noqa: PLC0415

        app = create_providers_app()
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        provider_names = [p["name"] for p in data["providers"]]
        assert "azure-openai" in provider_names
