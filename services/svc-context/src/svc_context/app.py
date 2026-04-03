"""FastAPI app factory for svc-context — the context management service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from amplifier_service_sdk.models import Message
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_context.context_manager import SimpleContextManager


class BulkMessagesRequest(BaseModel):
    """Request body for PUT /context/{session_id}/messages/bulk."""

    messages: list[Message]


class SystemPromptRequest(BaseModel):
    """Request body for POST /context/{session_id}/system-prompt."""

    content: str


def create_context_app() -> FastAPI:
    """Create the svc-context FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    context-specific endpoints for managing conversation messages,
    keyed by session_id in the URL path.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(name="svc-context")
    app = create_app(config)

    manager = SimpleContextManager()

    @app.post("/context/{session_id}/messages")
    async def add_message(session_id: str, message: Message) -> dict[str, Any]:
        """Add a message to the session context."""
        await manager.add_message(session_id, message)
        return {"success": True}

    @app.get("/context/{session_id}/messages")
    async def get_messages(
        session_id: str,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Get all messages from the session context, with optional compaction parameters."""
        messages = await manager.get_messages(
            session_id,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
        )
        return {"messages": [m.model_dump() for m in messages]}

    @app.put("/context/{session_id}/messages/bulk")
    async def bulk_set_messages(
        session_id: str, request: BulkMessagesRequest
    ) -> dict[str, Any]:
        """Replace all messages in the session context with the provided list."""
        await manager.set_messages(session_id, request.messages)
        return {"success": True}

    @app.post("/context/{session_id}/clear")
    async def clear_messages(session_id: str) -> dict[str, Any]:
        """Clear all messages from the session context."""
        await manager.clear(session_id)
        return {"success": True}

    @app.post("/context/{session_id}/system-prompt")
    async def set_system_prompt(
        session_id: str, request: SystemPromptRequest
    ) -> dict[str, Any]:
        """Set or replace the system prompt for the session.

        If a system message already exists at position 0, it is replaced.
        Otherwise, a new system message is prepended to the session.
        """
        # NOTE: _get_session returns a mutable reference; mutation is intentional.
        session = manager._get_session(session_id)
        system_message = Message(role="system", content=request.content)
        if session and session[0].role == "system":
            session[0] = system_message
        else:
            session.insert(0, system_message)
        return {"success": True}

    return app


app = create_context_app()
