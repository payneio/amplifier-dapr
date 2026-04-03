"""Tests for streaming delegation in DelegateTool (task-6c)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from svc_delegation.tool import DelegateTool, MAX_DELEGATION_DEPTH


@pytest.fixture
def tool() -> DelegateTool:
    """Create a DelegateTool with session_service_base_url for streaming tests."""
    return DelegateTool(
        orchestrator_base_url="http://orchestrator:8080",
        session_service_base_url="http://session-service:8080",
    )


def _make_stream_client_mock(sse_lines: list[str]) -> MagicMock:
    """Build an httpx AsyncClient mock that streams the given SSE lines.

    Mirrors the async context-manager protocol used in production code:
    ``async with httpx.AsyncClient() as client:``
        ``async with client.stream(...) as response:``
            ``async for line in response.aiter_lines():``
    """

    async def _aiter_lines():
        for line in sse_lines:
            yield line

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = lambda: _aiter_lines()

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream.return_value = mock_stream_ctx

    return mock_client


class TestStreamingDelegationExists:
    """Tests that execute_stream exists on DelegateTool."""

    def test_execute_stream_not_defined_yet(self, tool: DelegateTool) -> None:
        """DelegateTool must have an execute_stream method."""
        assert hasattr(tool, "execute_stream")


class TestStreamingDelegationLifecycle:
    """Tests for execute_stream lifecycle events."""

    async def test_execute_stream_yields_spawned_and_completed(
        self, tool: DelegateTool
    ) -> None:
        """execute_stream yields delegate:agent_spawned and delegate:agent_completed."""
        sse_lines = [
            "event: text_delta",
            'data: {"text": "hello"}',
            "",
            "event: complete",
            'data: {"result": "Agent finished"}',
            "",
        ]
        mock_client = _make_stream_client_mock(sse_lines)

        with patch("svc_delegation.tool.httpx.AsyncClient", return_value=mock_client):
            events = []
            async for event in tool.execute_stream(
                {
                    "instruction": "do something",
                    "session_id": "child-session-1",
                }
            ):
                events.append(event)

        event_types = [e["event"] for e in events]
        assert "delegate:agent_spawned" in event_types
        assert "delegate:agent_completed" in event_types

    async def test_execute_stream_spawned_has_required_fields(
        self, tool: DelegateTool
    ) -> None:
        """delegate:agent_spawned event data must contain agent, session_id, instruction, depth."""
        sse_lines = [
            "event: complete",
            'data: {"result": "done"}',
            "",
        ]
        mock_client = _make_stream_client_mock(sse_lines)

        with patch("svc_delegation.tool.httpx.AsyncClient", return_value=mock_client):
            events = []
            async for event in tool.execute_stream(
                {
                    "instruction": "do something",
                    "agent": "my-agent",
                    "session_id": "child-123",
                }
            ):
                events.append(event)

        spawned = next(e for e in events if e["event"] == "delegate:agent_spawned")
        assert spawned["data"]["agent"] == "my-agent"
        assert spawned["data"]["session_id"] == "child-123"
        assert spawned["data"]["instruction"] == "do something"
        assert "depth" in spawned["data"]

    async def test_execute_stream_completed_has_required_fields(
        self, tool: DelegateTool
    ) -> None:
        """delegate:agent_completed event data must contain agent, session_id, success, turn_count, result_preview."""
        sse_lines = [
            "event: complete",
            'data: {"result": "final result"}',
            "",
        ]
        mock_client = _make_stream_client_mock(sse_lines)

        with patch("svc_delegation.tool.httpx.AsyncClient", return_value=mock_client):
            events = []
            async for event in tool.execute_stream(
                {
                    "instruction": "do something",
                    "agent": "my-agent",
                    "session_id": "child-456",
                }
            ):
                events.append(event)

        completed = next(e for e in events if e["event"] == "delegate:agent_completed")
        data = completed["data"]
        assert data["agent"] == "my-agent"
        assert data["session_id"] == "child-456"
        assert "success" in data
        assert "turn_count" in data
        assert "result_preview" in data

    async def test_execute_stream_forwards_child_events(
        self, tool: DelegateTool
    ) -> None:
        """execute_stream forwards non-complete child events from SSE stream."""
        sse_lines = [
            "event: text_delta",
            'data: {"text": "streaming"}',
            "",
            "event: complete",
            'data: {"result": "done"}',
            "",
        ]
        mock_client = _make_stream_client_mock(sse_lines)

        with patch("svc_delegation.tool.httpx.AsyncClient", return_value=mock_client):
            events = []
            async for event in tool.execute_stream(
                {"instruction": "do something", "session_id": "child-789"}
            ):
                events.append(event)

        event_types = [e["event"] for e in events]
        assert "text_delta" in event_types

    async def test_execute_stream_does_not_forward_complete_event(
        self, tool: DelegateTool
    ) -> None:
        """execute_stream must NOT forward 'complete' events (it extracts result_text instead)."""
        sse_lines = [
            "event: complete",
            'data: {"result": "done"}',
            "",
        ]
        mock_client = _make_stream_client_mock(sse_lines)

        with patch("svc_delegation.tool.httpx.AsyncClient", return_value=mock_client):
            events = []
            async for event in tool.execute_stream(
                {"instruction": "do something", "session_id": "child-789"}
            ):
                events.append(event)

        event_types = [e["event"] for e in events]
        assert "complete" not in event_types

    async def test_execute_stream_extracts_result_text_from_complete(
        self, tool: DelegateTool
    ) -> None:
        """execute_stream extracts result_text from 'complete' and puts it in result_preview."""
        sse_lines = [
            "event: complete",
            'data: {"result": "The final answer is 42"}',
            "",
        ]
        mock_client = _make_stream_client_mock(sse_lines)

        with patch("svc_delegation.tool.httpx.AsyncClient", return_value=mock_client):
            events = []
            async for event in tool.execute_stream(
                {"instruction": "do something", "session_id": "child-result"}
            ):
                events.append(event)

        completed = next(e for e in events if e["event"] == "delegate:agent_completed")
        assert "42" in completed["data"]["result_preview"]


class TestStreamingDelegationErrorHandling:
    """Tests for execute_stream error cases."""

    async def test_execute_stream_missing_instruction_yields_error(
        self, tool: DelegateTool
    ) -> None:
        """execute_stream with no instruction yields delegate:error."""
        events = []
        async for event in tool.execute_stream({}):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "delegate:error" in event_types
        assert "delegate:agent_spawned" not in event_types

    async def test_execute_stream_depth_exceeded_yields_error(self) -> None:
        """execute_stream at MAX_DELEGATION_DEPTH yields delegate:error."""
        tool = DelegateTool(
            orchestrator_base_url="http://orchestrator:8080",
            session_service_base_url="http://session-service:8080",
            delegation_depth=MAX_DELEGATION_DEPTH,
        )
        events = []
        async for event in tool.execute_stream({"instruction": "do something"}):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "delegate:error" in event_types
        assert "delegate:agent_spawned" not in event_types

    async def test_execute_stream_exception_yields_error_and_completed(
        self, tool: DelegateTool
    ) -> None:
        """execute_stream on httpx exception yields delegate:error and still yields delegate:agent_completed."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream.side_effect = Exception("Connection refused")

        with patch("svc_delegation.tool.httpx.AsyncClient", return_value=mock_client):
            events = []
            async for event in tool.execute_stream(
                {"instruction": "do something", "session_id": "fail-session"}
            ):
                events.append(event)

        event_types = [e["event"] for e in events]
        assert "delegate:error" in event_types
        assert "delegate:agent_completed" in event_types

        completed = next(e for e in events if e["event"] == "delegate:agent_completed")
        assert completed["data"]["success"] is False
