"""Tests for AnthropicProvider — name, config, complete, usage extraction."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_service_sdk.models import ChatRequest, ChatResponse, Message, TokenUsage
from svc_providers.anthropic_provider import AnthropicProvider
from svc_providers.base import BaseProvider


class TestProviderName:
    """test_provider_name: AnthropicProvider.name == 'anthropic'."""

    def test_provider_name(self) -> None:
        """AnthropicProvider.name attribute is 'anthropic'."""
        provider = AnthropicProvider(config={"api_key": "test-key"})
        assert provider.name == "anthropic"

    def test_provider_is_base_provider(self) -> None:
        """AnthropicProvider inherits from BaseProvider."""
        provider = AnthropicProvider(config={"api_key": "test-key"})
        assert isinstance(provider, BaseProvider)


class TestProviderConfig:
    """test_provider_config: AnthropicProvider accepts config dict with api_key."""

    def test_config_api_key(self) -> None:
        """AnthropicProvider stores api_key from config dict."""
        provider = AnthropicProvider(config={"api_key": "sk-test-123"})
        assert provider._api_key == "sk-test-123"

    def test_config_model_default(self) -> None:
        """AnthropicProvider has a default model attribute."""
        provider = AnthropicProvider(config={"api_key": "test"})
        assert isinstance(provider.model, str)
        assert len(provider.model) > 0

    def test_config_max_tokens_default(self) -> None:
        """AnthropicProvider has a default max_tokens attribute."""
        provider = AnthropicProvider(config={"api_key": "test"})
        assert isinstance(provider.max_tokens, int)
        assert provider.max_tokens > 0

    def test_config_model_override(self) -> None:
        """AnthropicProvider uses model from config."""
        provider = AnthropicProvider(
            config={"api_key": "test", "model": "claude-3-haiku-20240307"}
        )
        assert provider.model == "claude-3-haiku-20240307"

    def test_config_max_tokens_override(self) -> None:
        """AnthropicProvider uses max_tokens from config."""
        provider = AnthropicProvider(config={"api_key": "test", "max_tokens": 1024})
        assert provider.max_tokens == 1024


class MockTextBlock:
    """Simulates an Anthropic text content block."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class MockUsage:
    """Simulates an Anthropic API usage object."""

    def __init__(self, input_tokens: int = 10, output_tokens: int = 20) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0


class MockAnthropicResponse:
    """Simulates an Anthropic Messages API response."""

    def __init__(
        self,
        content: list[Any],
        stop_reason: str = "end_turn",
        usage: MockUsage | None = None,
        model: str = "claude-test",
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage or MockUsage()
        self.model = model


class TestCompleteWithMockedTextResponse:
    """test_complete: complete() with mocked client returns ChatResponse with correct text."""

    @pytest.fixture
    def provider(self) -> AnthropicProvider:
        """Provider with injected AsyncMock client."""
        p = AnthropicProvider(config={"api_key": "test-key"})
        # Inject a mock client
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MockAnthropicResponse(
                content=[MockTextBlock("Hello from Claude!")],
                stop_reason="end_turn",
                usage=MockUsage(input_tokens=10, output_tokens=5),
            )
        )
        p._client = mock_client
        return p

    @pytest.mark.asyncio
    async def test_complete_returns_chat_response(
        self, provider: AnthropicProvider
    ) -> None:
        """complete() returns a ChatResponse instance."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert isinstance(response, ChatResponse)

    @pytest.mark.asyncio
    async def test_complete_returns_correct_text(
        self, provider: AnthropicProvider
    ) -> None:
        """complete() returns ChatResponse with text from mocked response."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.content == "Hello from Claude!"

    @pytest.mark.asyncio
    async def test_complete_stop_reason(self, provider: AnthropicProvider) -> None:
        """complete() sets stop_reason from mocked response."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.stop_reason == "end_turn"


class TestUsageExtraction:
    """test_usage_extraction: complete() extracts usage with input_tokens and output_tokens."""

    @pytest.fixture
    def provider(self) -> AnthropicProvider:
        """Provider with injected AsyncMock client returning specific usage."""
        p = AnthropicProvider(config={"api_key": "test-key"})
        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=MockAnthropicResponse(
                content=[MockTextBlock("Test")],
                stop_reason="end_turn",
                usage=MockUsage(input_tokens=42, output_tokens=17),
            )
        )
        p._client = mock_client
        return p

    @pytest.mark.asyncio
    async def test_usage_is_token_usage(self, provider: AnthropicProvider) -> None:
        """complete() returns ChatResponse with TokenUsage instance."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.usage is not None
        assert isinstance(response.usage, TokenUsage)

    @pytest.mark.asyncio
    async def test_usage_input_tokens(self, provider: AnthropicProvider) -> None:
        """complete() extracts input_tokens from Anthropic usage."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.usage is not None
        assert response.usage.input_tokens == 42

    @pytest.mark.asyncio
    async def test_usage_output_tokens(self, provider: AnthropicProvider) -> None:
        """complete() extracts output_tokens from Anthropic usage."""
        request = ChatRequest(messages=[Message(role="user", content="Hi")])
        response = await provider.complete(request)
        assert response.usage is not None
        assert response.usage.output_tokens == 17
