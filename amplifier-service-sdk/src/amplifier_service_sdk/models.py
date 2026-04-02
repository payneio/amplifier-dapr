"""Pydantic v2 models for the Amplifier Service SDK."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCapability(BaseModel):
    """Describes a tool exposed by a service."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ModeCapability(BaseModel):
    """Describes a runtime mode advertised by a service."""

    name: str
    description: str = ""


class AgentCapability(BaseModel):
    """Describes an agent advertised by a service."""

    name: str
    description: str = ""


class ToolRequest(BaseModel):
    """A request to invoke a tool."""

    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The result of a tool invocation."""

    success: bool = True
    output: Any = None
    error: dict[str, Any] | None = None


class HookEvent(BaseModel):
    """An event passed to a hook handler."""

    event: str
    data: dict[str, Any] = Field(default_factory=dict)


class HookResult(BaseModel):
    """The result returned by a hook handler."""

    action: str = "CONTINUE"
    data: dict[str, Any] | None = None
    reason: str | None = None


class ProviderRequest(BaseModel):
    """A request to a provider (LLM backend)."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    system: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None


class ProviderResponse(BaseModel):
    """A response from a provider (LLM backend)."""

    content: str | list[Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None


class DescribeResponse(BaseModel):
    """The response to a /describe endpoint request."""

    name: str
    version: str = "0.1.0"
    tools: list[ToolCapability] = Field(default_factory=list)
    hooks: list["HookRegistration"] = Field(default_factory=list)
    providers: list[dict[str, Any]] = Field(default_factory=list)
    content_paths: list[str] = Field(default_factory=list)
    modes: list[ModeCapability] = Field(default_factory=list)
    agents: list[AgentCapability] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """The response to a /health endpoint request."""

    status: str = "healthy"
    service_name: str
    version: str = "0.1.0"


class ContentFile(BaseModel):
    """A file served from a content path."""

    path: str
    content: str


# ── Phase 2 models ────────────────────────────────────────────────────────────


class HookAction(str, Enum):
    """Actions a hook handler can return to control execution flow."""

    CONTINUE = "CONTINUE"
    DENY = "DENY"
    MODIFY = "MODIFY"
    INJECT_CONTEXT = "INJECT_CONTEXT"


class ToolCall(BaseModel):
    """A tool call made by the LLM during a chat turn."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    """Token usage statistics for a chat exchange."""

    input_tokens: int = 0
    output_tokens: int = 0


class Message(BaseModel):
    """A single message in a conversation."""

    role: str
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None


class ChatRequest(BaseModel):
    """A request to a chat endpoint carrying structured messages."""

    messages: list[Message]
    tools: list[ToolCapability] | None = None
    system: str | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    temperature: float | None = None


class ChatResponse(BaseModel):
    """A response from a chat endpoint."""

    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    usage: TokenUsage | None = None
    stop_reason: str | None = None


class RoutingTable(BaseModel):
    """Routing configuration for an orchestrator session."""

    tools: dict[str, str] = Field(default_factory=dict)
    providers: dict[str, str] = Field(default_factory=dict)
    hooks: dict[str, list[str]] = Field(default_factory=dict)
    context: str = ""
    hook_endpoints: dict[str, str] = Field(default_factory=dict)
    hook_priorities: dict[str, int] = Field(default_factory=dict)


class StreamEvent(BaseModel):
    """A streaming event emitted during a session."""

    session_id: str
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)


# ── Phase 3b models ───────────────────────────────────────────────────────────


class HookRegistration(BaseModel):
    """Describes a hook registration advertised by a service via /describe."""

    name: str
    events: list[str] = Field(default_factory=list)
    priority: int = 50
    mode: Literal["sync", "async"] = Field(
        default="sync",
        description="'sync' = pre-hook blocking, 'async' = pub/sub subscriber",
    )


class DaprSubscription(BaseModel):
    """A Dapr pub/sub subscription descriptor."""

    pubsubname: str
    topic: str
    route: str = ""

    def model_post_init(self, __context: Any) -> None:  # noqa: ANN401
        if not self.route:
            safe_topic = self.topic.replace(":", ".")
            self.route = f"/events/{safe_topic}"
