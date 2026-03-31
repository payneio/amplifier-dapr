"""Tests for MockProvider deterministic canned responses."""

from __future__ import annotations

import pytest

from amplifier_service_sdk import (
    ChatRequest,
    ChatResponse,
    Message,
    TokenUsage,
    ToolCall,
    ToolCapability,
)
from svc_mock_provider.provider import MockProvider


class TestMockProviderTextResponse:
    """test_text_response: Plain message with no matching tools returns text."""

    @pytest.fixture
    def provider(self) -> MockProvider:
        return MockProvider()

    @pytest.mark.asyncio
    async def test_text_response(self, provider: MockProvider) -> None:
        """Returns 'Mock response to: {content}' with end_turn when no tools match."""
        request = ChatRequest(
            messages=[Message(role="user", content="Hello, world")],
        )
        response = await provider.complete(request)

        assert isinstance(response, ChatResponse)
        assert response.content == "Mock response to: Hello, world"
        assert response.stop_reason == "end_turn"
        assert response.tool_calls is None or response.tool_calls == []

    @pytest.mark.asyncio
    async def test_text_response_usage_populated(self, provider: MockProvider) -> None:
        """Usage is always populated with positive values."""
        request = ChatRequest(
            messages=[Message(role="user", content="Hello")],
        )
        response = await provider.complete(request)

        assert response.usage is not None
        assert isinstance(response.usage, TokenUsage)
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0


class TestMockProviderToolCallResponse:
    """test_tool_call_response: User message mentioning a tool name triggers a tool call."""

    @pytest.fixture
    def provider(self) -> MockProvider:
        return MockProvider()

    @pytest.mark.asyncio
    async def test_tool_call_response(self, provider: MockProvider) -> None:
        """Returns tool_call with tool_use stop_reason when user mentions a tool name."""
        tools = [
            ToolCapability(
                name="search",
                description="Search for things",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer"},
                    },
                },
            )
        ]
        request = ChatRequest(
            messages=[Message(role="user", content="Please use search to find cats")],
            tools=tools,
        )
        response = await provider.complete(request)

        assert isinstance(response, ChatResponse)
        assert response.stop_reason == "tool_use"
        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1

        tc = response.tool_calls[0]
        assert isinstance(tc, ToolCall)
        assert tc.name == "search"
        assert tc.id.startswith("tc_")
        assert len(tc.id) == len("tc_") + 8  # tc_{8 hex chars}

        # Arguments derived from input_schema
        assert tc.arguments["query"] == "mock_query_value"
        assert tc.arguments["max_results"] == 1

    @pytest.mark.asyncio
    async def test_tool_call_response_usage_populated(
        self, provider: MockProvider
    ) -> None:
        """Usage is populated with positive values on tool call response."""
        tools = [ToolCapability(name="my_tool", description="A tool")]
        request = ChatRequest(
            messages=[Message(role="user", content="Use my_tool now")],
            tools=tools,
        )
        response = await provider.complete(request)

        assert response.usage is not None
        assert response.usage.input_tokens == 50
        assert response.usage.output_tokens > 0


class TestMockProviderNoToolCallWhenNoTools:
    """test_no_tool_call_when_no_tools: tools=None means no tool calls even if mentioned."""

    @pytest.fixture
    def provider(self) -> MockProvider:
        return MockProvider()

    @pytest.mark.asyncio
    async def test_no_tool_call_when_no_tools(self, provider: MockProvider) -> None:
        """Returns text even if message mentions tool names when tools=None."""
        request = ChatRequest(
            messages=[Message(role="user", content="Use search to find something")],
            tools=None,
        )
        response = await provider.complete(request)

        assert isinstance(response, ChatResponse)
        assert response.stop_reason == "end_turn"
        assert response.content == "Mock response to: Use search to find something"
        assert response.tool_calls is None or response.tool_calls == []


class TestMockProviderTextAfterToolResult:
    """test_text_after_tool_result: Returns text 'The tool returned: {output}' after tool result."""

    @pytest.fixture
    def provider(self) -> MockProvider:
        return MockProvider()

    @pytest.mark.asyncio
    async def test_text_after_tool_result(self, provider: MockProvider) -> None:
        """Returns 'The tool returned: {output}' with end_turn when last message is tool result."""
        request = ChatRequest(
            messages=[
                Message(role="user", content="Use search"),
                Message(
                    role="tool",
                    content="42 results found",
                    tool_call_id="tc_abcd1234",
                ),
            ],
        )
        response = await provider.complete(request)

        assert isinstance(response, ChatResponse)
        assert response.content == "The tool returned: 42 results found"
        assert response.stop_reason == "end_turn"
        assert response.tool_calls is None or response.tool_calls == []

    @pytest.mark.asyncio
    async def test_text_after_tool_result_usage_populated(
        self, provider: MockProvider
    ) -> None:
        """Usage is populated with positive values after tool result."""
        request = ChatRequest(
            messages=[
                Message(
                    role="tool",
                    content="result data",
                    tool_call_id="tc_00000001",
                ),
            ],
        )
        response = await provider.complete(request)

        assert response.usage is not None
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0
