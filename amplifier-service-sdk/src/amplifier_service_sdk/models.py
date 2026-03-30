"""Pydantic v2 models for the Amplifier Service SDK."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCapability(BaseModel):
    """Describes a tool exposed by a service."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


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
    hooks: list[dict[str, Any]] = Field(default_factory=list)
    providers: list[dict[str, Any]] = Field(default_factory=list)
    content_paths: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """The response to a /health endpoint request."""

    status: str = "healthy"
    service_name: str
    version: str = "0.1.0"


class ContentFile(BaseModel):
    """A file served from a content path."""

    path: str
    content: str
