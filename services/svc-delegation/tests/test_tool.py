"""Tests for DelegateTool."""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock

from svc_delegation.tool import DelegateTool


@pytest.fixture
def tool() -> DelegateTool:
    """Create a DelegateTool for testing."""
    return DelegateTool(orchestrator_base_url="http://orchestrator:8080")


class TestDelegateToolMissingPrompt:
    """Tests for missing prompt validation."""

    async def test_execute_missing_prompt_returns_error(
        self, tool: DelegateTool
    ) -> None:
        """execute() with no prompt returns error ToolResult."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "prompt" in result.error["message"].lower()


class TestDelegateToolSuccess:
    """Tests for successful delegation scenarios."""

    async def test_execute_delegates_and_returns_result(
        self, tool: DelegateTool
    ) -> None:
        """execute() calls _call_orchestrator and returns child_session_id + result."""
        mock_response = {"session_id": "abc123", "result": "done"}
        tool._call_orchestrator = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        result = await tool.execute({"prompt": "hello"})

        assert result.success is True
        assert result.output is not None
        assert result.output["child_session_id"] == "abc123"
        assert result.output["result"] == mock_response

    async def test_execute_passes_provider_name(self, tool: DelegateTool) -> None:
        """execute() forwards provider_name to the orchestrator payload."""
        mock_response = {"session_id": "abc123", "result": "done"}
        tool._call_orchestrator = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        await tool.execute({"prompt": "hello", "provider_name": "openai"})

        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["provider_name"] == "openai"


class TestDelegateToolErrors:
    """Tests for orchestrator error handling."""

    async def test_execute_orchestrator_unreachable_returns_error(
        self, tool: DelegateTool
    ) -> None:
        """execute() returns error when orchestrator is unreachable."""
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.RequestError("Connection refused")
        )

        result = await tool.execute({"prompt": "hello"})

        assert result.success is False
        assert result.error is not None
        assert "unreachable" in result.error["message"].lower()

    async def test_execute_http_error_returns_error_with_status_code(
        self, tool: DelegateTool
    ) -> None:
        """execute() returns error containing HTTP status code on HTTPStatusError."""
        mock_request = httpx.Request(
            "POST", "http://orchestrator:8080/orchestrator/delegate"
        )
        mock_response = httpx.Response(500, request=mock_request)
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.HTTPStatusError(
                "Server error", request=mock_request, response=mock_response
            )
        )

        result = await tool.execute({"prompt": "hello"})

        assert result.success is False
        assert result.error is not None
        assert "500" in result.error["message"]
