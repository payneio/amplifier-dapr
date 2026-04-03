"""FastAPI app factory for svc-context — the context management service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from amplifier_service_sdk.models import Message
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_context.context_manager import SimpleContextManager

# Session ID used by the legacy single-session HTTP endpoints.
# Phase 3 endpoints (e.g. /context/{session_id}/messages) should pass the
# real session_id from the request path instead.
_DEFAULT_SESSION = "default"


class BulkMessagesRequest(BaseModel):
    """Request body for PUT /context/messages/bulk."""

    messages: list[Message]


def create_context_app() -> FastAPI:
    """Create the svc-context FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    context-specific endpoints for managing conversation messages.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(name="svc-context")
    app = create_app(config)

    manager = SimpleContextManager()

    @app.post("/context/messages")
    async def add_message(message: Message) -> dict[str, Any]:
        """Add a message to the context."""
        await manager.add_message(_DEFAULT_SESSION, message)
        return {"success": True}

    @app.get("/context/messages")
    async def get_messages(
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Get all messages from the context, with optional compaction parameters."""
        messages = await manager.get_messages(
            _DEFAULT_SESSION,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
        )
        return {"messages": [m.model_dump() for m in messages]}

    @app.put("/context/messages/bulk")
    async def bulk_set_messages(request: BulkMessagesRequest) -> dict[str, Any]:
        """Replace all messages in the context with the provided list."""
        await manager.set_messages(_DEFAULT_SESSION, request.messages)
        return {"success": True}

    @app.post("/context/clear")
    async def clear_messages() -> dict[str, Any]:
        """Clear all messages from the context."""
        await manager.clear(_DEFAULT_SESSION)
        return {"success": True}

    return app


app = create_context_app()
