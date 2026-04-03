"""Tests for DelegateTool (new schema with context inheritance and recursion guard)."""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock

from svc_delegation.tool import MAX_DELEGATION_DEPTH, DelegateTool

_MOCK_ORCH_RESPONSE = {"child_session_id": "abc", "result": "done"}


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
            "delegation_depth",
        }
        assert expected.issubset(props.keys())

    def test_delegation_depth_schema_type_is_integer(self) -> None:
        """delegation_depth property must have type 'integer' in input_schema."""
        prop = DelegateTool.input_schema["properties"]["delegation_depth"]
        assert prop["type"] == "integer"

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

    @pytest.fixture
    def tool_with_parent(self) -> DelegateTool:
        """Create a DelegateTool with a parent session for context inheritance tests."""
        return DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            parent_session_id="parent-1",
        )

    async def test_context_depth_none_sends_no_context(
        self, tool_with_parent: DelegateTool
    ) -> None:
        """depth=none: _fetch_parent_messages not called, context_messages absent."""
        tool_with_parent._fetch_parent_messages = AsyncMock()  # type: ignore[method-assign]
        tool_with_parent._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value=_MOCK_ORCH_RESPONSE
        )

        await tool_with_parent.execute(
            {"instruction": "do something", "context_depth": "none"}
        )

        tool_with_parent._fetch_parent_messages.assert_not_called()
        payload = tool_with_parent._call_orchestrator.call_args[0][0]
        assert "context_messages" not in payload

    async def test_context_scope_conversation_filters_to_user_assistant(
        self, tool_with_parent: DelegateTool
    ) -> None:
        """scope=conversation removes system and tool roles, keeps user and assistant."""
        parent_messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "tool", "content": "tool result"},
        ]
        tool_with_parent._fetch_parent_messages = AsyncMock(  # type: ignore[method-assign]
            return_value=parent_messages
        )
        tool_with_parent._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value=_MOCK_ORCH_RESPONSE
        )

        await tool_with_parent.execute(
            {
                "instruction": "do something",
                "context_depth": "all",
                "context_scope": "conversation",
            }
        )

        payload = tool_with_parent._call_orchestrator.call_args[0][0]
        context = payload["context_messages"]
        assert len(context) == 2
        roles = {m["role"] for m in context}
        assert "system" not in roles
        assert "tool" not in roles
        assert "user" in roles
        assert "assistant" in roles

    async def test_context_depth_recent_limits_turns(
        self, tool_with_parent: DelegateTool
    ) -> None:
        """depth=recent with context_turns=2 returns exactly 4 messages (2 turns × 2)."""
        # 10 alternating user/assistant messages = 5 turns
        parent_messages: list[dict[str, str]] = []
        for i in range(5):
            parent_messages.append({"role": "user", "content": f"user {i}"})
            parent_messages.append({"role": "assistant", "content": f"assistant {i}"})

        tool_with_parent._fetch_parent_messages = AsyncMock(  # type: ignore[method-assign]
            return_value=parent_messages
        )
        tool_with_parent._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value=_MOCK_ORCH_RESPONSE
        )

        await tool_with_parent.execute(
            {
                "instruction": "do something",
                "context_depth": "recent",
                "context_turns": 2,
            }
        )

        payload = tool_with_parent._call_orchestrator.call_args[0][0]
        context = payload["context_messages"]
        assert len(context) == 4  # 2 turns × 2 messages per turn

    async def test_context_scope_full_keeps_everything(
        self, tool_with_parent: DelegateTool
    ) -> None:
        """scope=full keeps user, assistant, tool but always removes system."""
        parent_messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "tool", "content": "tool result"},
        ]
        tool_with_parent._fetch_parent_messages = AsyncMock(  # type: ignore[method-assign]
            return_value=parent_messages
        )
        tool_with_parent._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value=_MOCK_ORCH_RESPONSE
        )

        await tool_with_parent.execute(
            {
                "instruction": "do something",
                "context_depth": "all",
                "context_scope": "full",
            }
        )

        payload = tool_with_parent._call_orchestrator.call_args[0][0]
        context = payload["context_messages"]
        # system removed; user + assistant + tool remain = 3 messages
        assert len(context) == 3
        roles = {m["role"] for m in context}
        assert "system" not in roles
        assert "user" in roles
        assert "assistant" in roles
        assert "tool" in roles


class TestRecursionGuard:
    """Tests for the recursion depth guard."""

    async def test_depth_at_max_returns_error(self) -> None:
        """Tool at MAX_DELEGATION_DEPTH returns error without calling orchestrator."""
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            delegation_depth=MAX_DELEGATION_DEPTH,
        )
        result = await tool.execute({"instruction": "do something"})
        assert result.success is False
        assert result.error is not None
        assert "maximum delegation depth" in result.error["message"].lower()

    async def test_depth_below_max_succeeds(self) -> None:
        """Tool with delegation_depth=5 (below max) executes successfully."""
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            delegation_depth=5,
        )
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value=_MOCK_ORCH_RESPONSE
        )
        result = await tool.execute({"instruction": "do something"})
        assert result.success is True

    async def test_depth_incremented_in_payload(self) -> None:
        """Payload delegation_depth is one greater than the tool's current depth."""
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            delegation_depth=3,
        )
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value=_MOCK_ORCH_RESPONSE
        )
        await tool.execute({"instruction": "do something"})
        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["delegation_depth"] == 4

    async def test_depth_from_input_triggers_guard_for_singleton_tool(self) -> None:
        """delegation_depth in input dict must trigger the recursion guard even if the
        singleton tool instance was created with depth=0 (production scenario)."""
        # Simulate a singleton tool as created by create_delegation_app()
        singleton_tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            delegation_depth=0,  # default — always 0 for singletons
        )
        # Orchestrator passes delegation_depth through the tool call input at runtime
        result = await singleton_tool.execute(
            {"instruction": "do something", "delegation_depth": MAX_DELEGATION_DEPTH}
        )
        assert result.success is False
        assert result.error is not None
        assert "maximum delegation depth" in result.error["message"].lower()

    async def test_depth_from_input_incremented_in_payload(self) -> None:
        """delegation_depth in the payload is incremented from the input dict value,
        not the singleton's constructor value."""
        singleton_tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            delegation_depth=0,  # singleton default
        )
        singleton_tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value=_MOCK_ORCH_RESPONSE
        )
        await singleton_tool.execute(
            {"instruction": "do something", "delegation_depth": 7}
        )
        payload = singleton_tool._call_orchestrator.call_args[0][0]
        assert payload["delegation_depth"] == 8


class TestSessionResumption:
    """Tests for session resumption via session_id forwarding."""

    async def test_session_id_forwarded_as_child_session_id(
        self, tool: DelegateTool
    ) -> None:
        """session_id input is forwarded to orchestrator as child_session_id."""
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value=_MOCK_ORCH_RESPONSE
        )
        await tool.execute(
            {"instruction": "do something", "session_id": "existing-child"}
        )
        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["child_session_id"] == "existing-child"

    async def test_no_session_id_means_new_session(self, tool: DelegateTool) -> None:
        """Without session_id, child_session_id is absent from the payload."""
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value=_MOCK_ORCH_RESPONSE
        )
        await tool.execute({"instruction": "do something"})
        payload = tool._call_orchestrator.call_args[0][0]
        assert "child_session_id" not in payload
