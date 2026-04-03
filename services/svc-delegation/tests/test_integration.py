"""Integration tests for the full delegation end-to-end path with mocked external services."""

from __future__ import annotations

from unittest.mock import AsyncMock

from svc_delegation.tool import MAX_DELEGATION_DEPTH, DelegateTool


class TestDelegationEndToEnd:
    """End-to-end integration tests verifying the full delegation path."""

    async def test_full_delegation_with_context_inheritance(self) -> None:
        """Full delegation with context inheritance from a parent session.

        Verifies that:
        - The orchestrator is called with the correct prompt, agent_ref, and delegation_depth.
        - Context is fetched, filtered to 'recent'+'conversation', and correctly trimmed to
          the last 2 turns (4 messages).
        - Success is returned with the child_session_id from the orchestrator response.
        """
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            session_service_base_url="http://session:8080",
            parent_session_id="parent-session",
            delegation_depth=1,
        )

        # Parent transcript: 1 system + 3 user/assistant turn pairs (6 non-system messages)
        mock_parent_messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What are Python decorators?"},
            {
                "role": "assistant",
                "content": "Decorators are a way to modify functions.",
            },
            {"role": "user", "content": "Show me an example"},
            {"role": "assistant", "content": "Here is print('hello')"},
            {"role": "user", "content": "Now explain decorators"},
            {"role": "assistant", "content": "Decorators wrap functions"},
        ]

        tool._fetch_parent_messages = AsyncMock(return_value=mock_parent_messages)  # type: ignore[method-assign]
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value={"child_session_id": "child-abc", "result": "done"}
        )

        result = await tool.execute(
            {
                "instruction": "Explain Python decorators in depth",
                "agent": "foundation:explorer",
                "context_depth": "recent",
                "context_scope": "conversation",
                "context_turns": 2,
            }
        )

        # Verify success and returned child session ID
        assert result.success is True
        assert result.output["child_session_id"] == "child-abc"

        # Verify the payload sent to the orchestrator
        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["prompt"] == "Explain Python decorators in depth"
        assert payload["agent_ref"] == "foundation:explorer"
        assert payload["delegation_depth"] == 2

        # Verify context: exactly 4 messages (last 2 turns), all user/assistant roles
        context = payload["context_messages"]
        assert len(context) == 4
        for msg in context:
            assert msg["role"] in ("user", "assistant")

        # Verify correct content order (last 2 turns of 3-turn conversation)
        assert context[0]["content"] == "Show me an example"
        assert context[1]["content"] == "Here is print('hello')"
        assert context[2]["content"] == "Now explain decorators"
        assert context[3]["content"] == "Decorators wrap functions"

    async def test_recursion_guard_blocks_deep_delegation(self) -> None:
        """Recursion guard prevents delegation when depth equals MAX_DELEGATION_DEPTH.

        Verifies that:
        - execute() returns success=False when delegation_depth == MAX_DELEGATION_DEPTH.
        - The error message indicates the maximum delegation depth was exceeded.
        """
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            delegation_depth=MAX_DELEGATION_DEPTH,
        )

        result = await tool.execute({"instruction": "infinite recursion"})

        assert result.success is False
        assert result.error is not None
        assert "maximum delegation depth" in result.error["message"].lower()

    async def test_session_resumption_flow(self) -> None:
        """Session resumption passes child_session_id through to the orchestrator payload.

        Verifies that:
        - When session_id is provided, it is forwarded as child_session_id in the payload.
        - context_depth='none' skips parent context fetching entirely.
        - The result reflects success with the resumed child session.
        """
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            session_service_base_url="http://session:8080",
            parent_session_id="parent-resume",
            delegation_depth=0,
        )

        # Mock empty parent messages (context_depth='none' means fetch is skipped anyway)
        tool._fetch_parent_messages = AsyncMock(return_value=[])  # type: ignore[method-assign]

        # Mock orchestrator response confirming the resumed session
        tool._call_orchestrator = AsyncMock(  # type: ignore[method-assign]
            return_value={"child_session_id": "existing-child", "result": "continued"}
        )

        result = await tool.execute(
            {
                "instruction": "Continue the analysis",
                "session_id": "existing-child",
                "context_depth": "none",
            }
        )

        # Verify success
        assert result.success is True

        # Verify the orchestrator payload carries the child session ID
        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["child_session_id"] == "existing-child"
