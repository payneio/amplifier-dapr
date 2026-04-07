"""Tests for the session-service streaming module (SSE support)."""

from __future__ import annotations

import json


class TestStreamEventType:
    """Tests for the StreamEventType enum."""

    def test_all_event_types_defined(self) -> None:
        """StreamEventType must have all required event types."""
        from session_service.streaming import StreamEventType  # noqa: PLC0415

        required_types = [
            "token",
            "tool_call_start",
            "tool_call",
            "tool_result",
            "todo_update",
            "delegate:agent_spawned",
            "delegate:agent_completed",
            "delegate:agent_resumed",
            "delegate:error",
            "content_block:start",
            "content_block:end",
            "content_block:delta",
            "thinking:delta",
            "thinking:final",
            "error",
            "complete",
        ]
        defined_values = {e.value for e in StreamEventType}
        for event_type in required_types:
            assert event_type in defined_values, (
                f"StreamEventType missing required value: {event_type}"
            )

    def test_child_session_events_removed_from_enum(self) -> None:
        """child_session_start and child_session_end must not be in StreamEventType."""
        from session_service.streaming import StreamEventType  # noqa: PLC0415

        defined_values = {e.value for e in StreamEventType}
        assert "child_session_start" not in defined_values, (
            "StreamEventType should not contain the removed 'child_session_start' value"
        )
        assert "child_session_end" not in defined_values, (
            "StreamEventType should not contain the removed 'child_session_end' value"
        )

    def test_delegate_event_types_have_correct_values(self) -> None:
        """Delegate event types have the correct string values."""
        from session_service.streaming import StreamEventType  # noqa: PLC0415

        assert StreamEventType.delegate_agent_spawned.value == "delegate:agent_spawned"
        assert (
            StreamEventType.delegate_agent_completed.value == "delegate:agent_completed"
        )
        assert StreamEventType.delegate_agent_resumed.value == "delegate:agent_resumed"
        assert StreamEventType.delegate_error.value == "delegate:error"

    def test_thinking_removed_from_enum(self) -> None:
        """The legacy 'thinking' value must no longer be in StreamEventType."""
        from session_service.streaming import StreamEventType  # noqa: PLC0415

        defined_values = {e.value for e in StreamEventType}
        assert "thinking" not in defined_values, (
            "StreamEventType should not contain the legacy 'thinking' value"
        )


class TestFormatSseEvent:
    """Tests for the format_sse_event() helper function."""

    def test_format_token_event(self) -> None:
        """format_sse_event produces valid SSE string for a token event."""
        from session_service.streaming import StreamEventType, format_sse_event  # noqa: PLC0415

        result = format_sse_event(StreamEventType.token, {"text": "Hello"})

        assert "event: token\n" in result
        assert "data: " in result
        # data line must contain valid JSON
        data_line = next(
            line for line in result.splitlines() if line.startswith("data: ")
        )
        payload = json.loads(data_line[len("data: ") :])
        assert payload["text"] == "Hello"

    def test_format_tool_call_event(self) -> None:
        """format_sse_event produces valid SSE string for a tool_call event."""
        from session_service.streaming import StreamEventType, format_sse_event  # noqa: PLC0415

        result = format_sse_event(
            StreamEventType.tool_call, {"name": "bash", "input": {}}
        )

        assert "event: tool_call\n" in result
        data_line = next(
            line for line in result.splitlines() if line.startswith("data: ")
        )
        payload = json.loads(data_line[len("data: ") :])
        assert payload["name"] == "bash"

    def test_format_complete_event(self) -> None:
        """format_sse_event produces valid SSE string for a complete event."""
        from session_service.streaming import StreamEventType, format_sse_event  # noqa: PLC0415

        result = format_sse_event(StreamEventType.complete, {"result": "done"})

        assert "event: complete\n" in result
        data_line = next(
            line for line in result.splitlines() if line.startswith("data: ")
        )
        payload = json.loads(data_line[len("data: ") :])
        assert payload["result"] == "done"

    def test_format_error_event(self) -> None:
        """format_sse_event produces valid SSE string for an error event."""
        from session_service.streaming import StreamEventType, format_sse_event  # noqa: PLC0415

        result = format_sse_event(
            StreamEventType.error, {"message": "Something failed"}
        )

        assert "event: error\n" in result
        data_line = next(
            line for line in result.splitlines() if line.startswith("data: ")
        )
        payload = json.loads(data_line[len("data: ") :])
        assert payload["message"] == "Something failed"

    def test_sse_format_has_double_newline_terminator(self) -> None:
        """SSE events must end with a blank line (double newline) per the SSE spec."""
        from session_service.streaming import StreamEventType, format_sse_event  # noqa: PLC0415

        result = format_sse_event(StreamEventType.token, {"text": "x"})

        assert result.endswith("\n\n"), (
            "SSE event string must end with double newline per SSE spec"
        )
