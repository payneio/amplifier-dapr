"""Tests for DelegateTool (new schema with context inheritance and recursion guard)."""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock

from svc_delegation.tool import DelegateTool


@pytest.fixture
def tool() -> DelegateTool:
    """Create a DelegateTool for testing."""
    return DelegateTool(orchestrator_base_url="http://orchestrator:8080")


class TestDelegateToolSchema:
    """Tests for the DelegateTool input schema."""

    def test_instruction_in_required(self) -> None:
        """input_schema must require 'instruction'."""
        assert "instruction" in DelegateTool.input_schema["required"]

    def test_all_new_properties_present(self) -> None:
        """input_schema must declare all new properties."""
        props = DelegateTool.input_schema["properties"]
        expected = {
            "instruction",
            "agent",
            "session_id",
            "context_depth",
            "context_scope",
            "context_turns",
            "model_role",
            "provider_preferences",
        }
        assert expected.issubset(props.keys())

    def test_context_depth_enum(self) -> None:
        """context_depth property must have enum [none, recent, all]."""
        prop = DelegateTool.input_schema["properties"]["context_depth"]
        assert set(prop["enum"]) == {"none", "recent", "all"}

    def test_context_scope_enum(self) -> None:
        """context_scope property must have enum [conversation, agents, full]."""
        prop = DelegateTool.input_schema["properties"]["context_scope"]
        assert set(prop["enum"]) == {"conversation", "agents", "full"}


class TestDelegateToolMissingInstruction:
    """Tests for missing instruction validation."""

    async def test_execute_missing_instruction_returns_error(
        self, tool: DelegateTool
    ) -> None:
        """execute() with no instruction returns error ToolResult."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "instruction" in result.error["message"].lower()


class TestDelegateToolSuccess:
    """Tests for successful delegation scenarios."""

    async def test_execute_delegates_with_instruction(self, tool: DelegateTool) -> None:
        """execute() calls _call_orchestrator with instruction and returns result."""
        mock_response = {"child_session_id": "abc123", "result": "done"}
        tool._call_orchestrator = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        result = await tool.execute({"instruction": "do something"})

        assert result.success is True
        tool._call_orchestrator.assert_called_once()
        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["prompt"] == "do something"

    async def test_execute_forwards_agent_parameter(self, tool: DelegateTool) -> None:
        """execute() forwards the agent parameter as agent_ref in the payload."""
        mock_response = {"child_session_id": "abc123", "result": "done"}
        tool._call_orchestrator = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

        await tool.execute({"instruction": "do something", "agent": "my-agent"})

        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["agent_ref"] == "my-agent"


class TestDelegateToolErrors:
    """Tests for orchestrator error handling."""

    async def test_execute_orchestrator_unreachable_returns_error(
        self, tool: DelegateTool
    ) -> None:
        """execute() returns error when orchestrator is unreachable."""
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.RequestError("Connection refused")
        )

        result = await tool.execute({"instruction": "hello"})

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

        result = await tool.execute({"instruction": "hello"})

        assert result.success is False
        assert result.error is not None
        assert "500" in result.error["message"]


class TestContextInheritance:
    """Tests for context inheritance scope and depth filtering."""

    async def test_context_depth_none_sends_no_context(self) -> None:
        """depth=none: _fetch_parent_messages not called, context_messages absent."""
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            parent_session_id="parent-1",
        )
        tool._fetch_parent_messages = AsyncMock()  # type: ignore[method-assign]
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value={"child_session_id": "abc", "result": "done"}
        )

        await tool.execute({"instruction": "do something", "context_depth": "none"})

        tool._fetch_parent_messages.assert_not_called()
        payload = tool._call_orchestrator.call_args[0][0]
        assert "context_messages" not in payload

    async def test_context_scope_conversation_filters_to_user_assistant(
        self,
    ) -> None:
        """scope=conversation removes system and tool roles, keeps user and assistant."""
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            parent_session_id="parent-1",
        )
        parent_messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "tool", "content": "tool result"},
        ]
        tool._fetch_parent_messages = AsyncMock(  # type: ignore[method-assign]
            return_value=parent_messages
        )
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value={"child_session_id": "abc", "result": "done"}
        )

        await tool.execute(
            {
                "instruction": "do something",
                "context_depth": "all",
                "context_scope": "conversation",
            }
        )

        payload = tool._call_orchestrator.call_args[0][0]
        context = payload["context_messages"]
        roles = {m["role"] for m in context}
        assert "system" not in roles
        assert "tool" not in roles
        assert "user" in roles
        assert "assistant" in roles

    async def test_context_depth_recent_limits_turns(self) -> None:
        """depth=recent with context_turns=2 returns exactly 4 messages (2 turns × 2)."""
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            parent_session_id="parent-1",
        )
        # 10 alternating user/assistant messages = 5 turns
        parent_messages: list[dict[str, str]] = []
        for i in range(5):
            parent_messages.append({"role": "user", "content": f"user {i}"})
            parent_messages.append({"role": "assistant", "content": f"assistant {i}"})

        tool._fetch_parent_messages = AsyncMock(  # type: ignore[method-assign]
            return_value=parent_messages
        )
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value={"child_session_id": "abc", "result": "done"}
        )

        await tool.execute(
            {
                "instruction": "do something",
                "context_depth": "recent",
                "context_turns": 2,
            }
        )

        payload = tool._call_orchestrator.call_args[0][0]
        context = payload["context_messages"]
        assert len(context) == 4  # 2 turns × 2 messages per turn

    async def test_context_scope_full_keeps_everything(self) -> None:
        """scope=full keeps user, assistant, tool but always removes system."""
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            parent_session_id="parent-1",
        )
        parent_messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "tool", "content": "tool result"},
        ]
        tool._fetch_parent_messages = AsyncMock(  # type: ignore[method-assign]
            return_value=parent_messages
        )
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value={"child_session_id": "abc", "result": "done"}
        )

        await tool.execute(
            {
                "instruction": "do something",
                "context_depth": "all",
                "context_scope": "full",
            }
        )

        payload = tool._call_orchestrator.call_args[0][0]
        context = payload["context_messages"]
        # system removed; user + assistant + tool remain = 3 messages
        assert len(context) == 3
        roles = {m["role"] for m in context}
        assert "system" not in roles
        assert "user" in roles
        assert "assistant" in roles
        assert "tool" in roles
