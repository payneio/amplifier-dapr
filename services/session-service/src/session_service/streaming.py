"""SSE streaming support for session-service.

Provides StreamEventType enum and format_sse_event() helper for producing
valid Server-Sent Events (SSE) strings.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any


class StreamEventType(str, Enum):
    """Event types for SSE streaming from session-service."""

    token = "token"
    tool_call_start = "tool_call_start"
    tool_call = "tool_call"
    tool_result = "tool_result"
    todo_update = "todo_update"
    delegate_agent_spawned = "delegate:agent_spawned"
    delegate_agent_completed = "delegate:agent_completed"
    delegate_agent_resumed = "delegate:agent_resumed"
    delegate_error = "delegate:error"
    content_block_start = "content_block:start"
    content_block_end = "content_block:end"
    content_block_delta = "content_block:delta"
    thinking_delta = "thinking:delta"
    thinking_final = "thinking:final"
    error = "error"
    complete = "complete"


def format_sse_event(event_type: StreamEventType, data: dict[str, Any]) -> str:
    """Format a Server-Sent Event string.

    Produces a valid SSE message with ``event:`` and ``data:`` lines,
    terminated by a blank line as required by the SSE specification.

    Args:
        event_type: The type of SSE event.
        data: Payload dictionary to serialize as JSON.

    Returns:
        SSE-formatted string ending with double newline.
    """
    return f"event: {event_type.value}\ndata: {json.dumps(data)}\n\n"
