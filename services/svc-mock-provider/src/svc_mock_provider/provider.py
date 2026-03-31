"""MockProvider — deterministic canned responses for testing."""

from __future__ import annotations

import uuid
from typing import Any

from amplifier_service_sdk import (
    ChatRequest,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolCapability,
)

_INPUT_TOKENS = 50

_SCHEMA_TYPE_DEFAULTS: dict[str, Any] = {
    "string": "mock_{name}_value",
    "integer": 1,
    "number": 1,
    "boolean": False,
}


def _default_args_for_tool(tool: ToolCapability) -> dict[str, Any]:
    """Generate sensible default arguments from a tool's input_schema."""
    properties: dict[str, Any] = (
        tool.input_schema.get("properties", {}) if tool.input_schema else {}
    )
    args: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        prop_type = prop_schema.get("type", "string")
        if prop_type == "string":
            args[prop_name] = f"mock_{prop_name}_value"
        elif prop_type in ("integer", "number"):
            args[prop_name] = 1
        elif prop_type == "boolean":
            args[prop_name] = False
        else:
            args[prop_name] = f"mock_{prop_name}_value"
    return args


def _new_tool_call_id() -> str:
    """Generate a determinism-friendly tool call ID."""
    return f"tc_{uuid.uuid4().hex[:8]}"


def _output_tokens_for_text(text: str) -> int:
    """Rough token estimate: 1 token per 4 characters, minimum 1."""
    return max(1, len(text) // 4)


class MockProvider:
    """Mock LLM provider that returns deterministic canned responses."""

    async def complete(self, request: ChatRequest) -> ChatResponse:  # noqa: PLR0911
        """Return a deterministic response based on the last message in *request*."""
        if not request.messages:
            content = "Mock response to: (empty)"
            return ChatResponse(
                content=content,
                stop_reason="end_turn",
                usage=TokenUsage(
                    input_tokens=_INPUT_TOKENS,
                    output_tokens=_output_tokens_for_text(content),
                ),
            )

        last_message = request.messages[-1]

        # ── Case 1: last message is a tool result ──────────────────────────
        if last_message.role == "tool" or last_message.tool_call_id is not None:
            output = last_message.content or ""
            content = f"The tool returned: {output}"
            return ChatResponse(
                content=content,
                stop_reason="end_turn",
                usage=TokenUsage(
                    input_tokens=_INPUT_TOKENS,
                    output_tokens=_output_tokens_for_text(content),
                ),
            )

        # ── Case 2: user message mentions a tool name (tools must be provided) ─
        if request.tools and last_message.role == "user":
            last_content = (
                last_message.content
                if isinstance(last_message.content, str)
                else str(last_message.content or "")
            )
            for tool in request.tools:
                if tool.name in last_content:
                    arguments = _default_args_for_tool(tool)
                    tc = ToolCall(
                        id=_new_tool_call_id(),
                        name=tool.name,
                        arguments=arguments,
                    )
                    return ChatResponse(
                        tool_calls=[tc],
                        stop_reason="tool_use",
                        usage=TokenUsage(
                            input_tokens=_INPUT_TOKENS,
                            output_tokens=20,
                        ),
                    )

        # ── Case 3: default text response ──────────────────────────────────
        last_content = (
            last_message.content
            if isinstance(last_message.content, str)
            else str(last_message.content or "")
        )
        content = f"Mock response to: {last_content}"
        return ChatResponse(
            content=content,
            stop_reason="end_turn",
            usage=TokenUsage(
                input_tokens=_INPUT_TOKENS,
                output_tokens=_output_tokens_for_text(content),
            ),
        )
