"""FastAPI app factory for session-service — manages conversation sessions via Dapr."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from amplifier_service_sdk.models import Message
from amplifier_service_sdk.service import ServiceConfig, create_app

from session_service.agents import get_agent_config
from session_service.content import assemble_system_prompt
from session_service.discovery import discover_services
from session_service.state import load_transcript, save_transcript
from session_service.streaming import StreamEventType


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TurnRequest(BaseModel):
    """Request model for POST /sessions/{id}/turn."""

    prompt: str
    workspace_content: dict[str, str] = {}
    agent_ref: str = "default"
    services: list[str] = []
    provider_name: str = "mock"


class TurnResponse(BaseModel):
    """Response model for POST /sessions/{id}/turn."""

    session_id: str
    result: str
    messages: list[Message]


class SessionInfo(BaseModel):
    """Response model for GET /sessions/{id}."""

    session_id: str
    status: str
    turn_count: int


# ---------------------------------------------------------------------------
# Default services list
# ---------------------------------------------------------------------------

#: Phase 3a + 3b service app-ids discovered when TurnRequest.services is empty.
DEFAULT_SERVICES: list[str] = [
    "svc-bash",
    "svc-filesystem",
    "svc-search",
    "svc-web",
    "svc-skills",
    "svc-todo",
    "svc-modes",
    "svc-mock-provider",
    "svc-providers",
    # Phase 3b: delegation and hook services
    "svc-delegation",
    "svc-hooks-approval",
    "svc-hooks-routing",
    "svc-hooks-async",
    "svc-hooks-shell",
]


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_session_app(dapr_url: str | None = None) -> FastAPI:
    """Create the session-service FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and session
    management endpoints (/sessions/{id}/turn, /sessions/{id}/turn/stream,
    /sessions/{id}).

    Args:
        dapr_url: Base URL of the Dapr HTTP sidecar. Defaults to
                  http://localhost:{DAPR_HTTP_PORT} using the environment variable,
                  falling back to http://localhost:3500.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(name="session-service")
    app = create_app(config)

    if dapr_url is None:
        port = os.environ.get("DAPR_HTTP_PORT", "3500")
        dapr_url = f"http://localhost:{port}"

    _dapr_url = dapr_url

    @app.post("/sessions/{session_id}/turn")
    async def turn(session_id: str, request: TurnRequest) -> dict[str, Any]:
        """Execute a conversation turn within a session."""
        # Create session if it doesn't exist
        if session_id not in _sessions:
            _sessions[session_id] = {"turn_count": 0, "status": "active"}

        # Resolve agent configuration
        agent_config = get_agent_config(request.agent_ref)

        # Discover services — caller-supplied list takes priority over agent default
        service_ids = request.services if request.services else agent_config["services"]
        routing_table_dict: dict[str, Any] = await discover_services(
            service_ids,
            _dapr_url,
            context_app_id=agent_config.get("context_app_id", "svc-context"),
        )

        # Resolve provider — agent default overrides the bare "mock" sentinel
        provider_name = request.provider_name
        if provider_name == "mock" and agent_config.get("default_provider"):
            provider_name = agent_config["default_provider"]

        # Convert workspace content dict to formatted string for prompt assembly
        workspace_content_str: str | None = None
        if request.workspace_content:
            ws_parts = [
                f'<context_file path="{path}">\n{content}\n</context_file>'
                for path, content in request.workspace_content.items()
            ]
            workspace_content_str = "\n\n".join(ws_parts)

        # Assemble the system prompt: agent prompt + service content + workspace
        system_prompt: str = await assemble_system_prompt(
            routing_table_dict,
            workspace_content=workspace_content_str,
            agent_system_prompt=agent_config.get("system_prompt"),
            dapr_url=_dapr_url,
        )

        # Load existing transcript
        transcript: list[Message] = await load_transcript(session_id, _dapr_url)

        # Add user message to transcript
        transcript.append(Message(role="user", content=request.prompt))

        # Invoke orchestrator via Dapr service invocation
        orchestrator_app_id = agent_config.get(
            "orchestrator_app_id", "svc-orchestrator"
        )
        invoke_url = (
            f"{_dapr_url}/v1.0/invoke/{orchestrator_app_id}/method/orchestrator/execute"
        )
        payload = {
            "system_prompt": system_prompt,
            "messages": [m.model_dump() for m in transcript],
            "config": {
                "provider": provider_name,
                "tools": routing_table_dict.get("_tool_specs", []),
            },
            "routing_table": routing_table_dict,
            "session_id": session_id,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(invoke_url, json=payload, timeout=120.0)
            response.raise_for_status()
            orch_result: dict[str, Any] = response.json()

        result_text: str = orch_result.get("result", "")
        result_messages: list[dict[str, Any]] = orch_result.get("messages", [])
        messages = [Message(**m) for m in result_messages]

        # Save transcript
        await save_transcript(session_id, messages, _dapr_url)

        # Store routing table for later metadata queries
        _sessions[session_id]["routing_table"] = routing_table_dict

        # Increment turn count
        _sessions[session_id]["turn_count"] += 1

        return TurnResponse(
            session_id=session_id,
            result=result_text,
            messages=messages,
        ).model_dump()

    @app.post("/sessions/{session_id}/turn/stream")
    async def turn_stream(session_id: str, request: TurnRequest) -> EventSourceResponse:
        """Execute a conversation turn and stream results as SSE events.

        Relays SSE events from the orchestrator's streaming endpoint directly to
        the CLI as they arrive.  The session-service acts as a transparent SSE
        relay — it opens a streaming HTTP connection to
        ``/orchestrator/execute/stream``, parses each event, and forwards it
        immediately.  No buffering occurs until the final ``complete`` event,
        at which point the transcript is saved before the event is forwarded.
        """

        async def event_generator() -> AsyncGenerator[dict[str, Any], None]:
            try:
                # Create session if it doesn't exist
                if session_id not in _sessions:
                    _sessions[session_id] = {"turn_count": 0, "status": "active"}

                # Resolve agent configuration
                agent_config = get_agent_config(request.agent_ref)

                # Discover services — caller-supplied list takes priority over agent default
                service_ids = (
                    request.services if request.services else agent_config["services"]
                )
                routing_table_dict: dict[str, Any] = await discover_services(
                    service_ids,
                    _dapr_url,
                    context_app_id=agent_config.get("context_app_id", "svc-context"),
                )

                # Resolve provider — agent default overrides the bare "mock" sentinel
                provider_name = request.provider_name
                if provider_name == "mock" and agent_config.get("default_provider"):
                    provider_name = agent_config["default_provider"]

                # Convert workspace content dict to formatted string for prompt assembly
                workspace_content_str: str | None = None
                if request.workspace_content:
                    ws_parts = [
                        f'<context_file path="{path}">\n{content}\n</context_file>'
                        for path, content in request.workspace_content.items()
                    ]
                    workspace_content_str = "\n\n".join(ws_parts)

                # Assemble the system prompt: agent prompt + service content + workspace
                system_prompt: str = await assemble_system_prompt(
                    routing_table_dict,
                    workspace_content=workspace_content_str,
                    agent_system_prompt=agent_config.get("system_prompt"),
                    dapr_url=_dapr_url,
                )

                # Load existing transcript and append the new user message
                transcript: list[Message] = await load_transcript(session_id, _dapr_url)
                transcript.append(Message(role="user", content=request.prompt))

                # Build the payload for the orchestrator streaming endpoint.
                # NOTE: We call the orchestrator DIRECTLY (not through Dapr)
                # because Dapr service invocation buffers the entire response
                # before returning it, which defeats SSE streaming.
                # In Docker Compose, services reach each other by container name.
                orchestrator_app_id = agent_config.get(
                    "orchestrator_app_id", "svc-orchestrator"
                )
                orch_direct_url = os.environ.get(
                    "ORCHESTRATOR_DIRECT_URL", f"http://{orchestrator_app_id}:8000"
                )
                stream_url = f"{orch_direct_url}/orchestrator/execute/stream"
                payload: dict[str, Any] = {
                    "system_prompt": system_prompt,
                    "messages": [m.model_dump() for m in transcript],
                    "config": {
                        "provider": provider_name,
                        "tools": routing_table_dict.get("_tool_specs", []),
                    },
                    "routing_table": routing_table_dict,
                    "session_id": session_id,
                }

                # ---------------------------------------------------------------
                # Open a streaming HTTP connection to the orchestrator and relay
                # SSE events to the CLI as they arrive.
                # ---------------------------------------------------------------
                async with httpx.AsyncClient() as http_client:
                    async with http_client.stream(
                        "POST", stream_url, json=payload, timeout=300.0
                    ) as response:
                        response.raise_for_status()

                        # SSE state machine: accumulate event / data per SSE block
                        current_event: str | None = None
                        current_data: str | None = None

                        async for line in response.aiter_lines():
                            if line.startswith("event:"):
                                current_event = line[6:].strip()
                            elif line.startswith("data:"):
                                current_data = line[5:].strip()
                            elif line == "":
                                # Blank line marks the end of an SSE event block
                                if (
                                    current_event is not None
                                    and current_data is not None
                                ):
                                    if current_event == "complete":
                                        # On complete: persist transcript, enrich
                                        # the event with session_id, then forward.
                                        try:
                                            orch_complete = json.loads(current_data)
                                        except json.JSONDecodeError:
                                            orch_complete = {}

                                        result_text: str = orch_complete.get(
                                            "result", ""
                                        )
                                        raw_msgs: list[dict[str, Any]] = (
                                            orch_complete.get("messages", [])
                                        )
                                        final_messages = [
                                            Message(**m) for m in raw_msgs
                                        ]

                                        # Save transcript
                                        await save_transcript(
                                            session_id, final_messages, _dapr_url
                                        )

                                        # Update session state
                                        _sessions[session_id]["routing_table"] = (
                                            routing_table_dict
                                        )
                                        _sessions[session_id]["turn_count"] += 1

                                        yield {
                                            "event": StreamEventType.complete.value,
                                            "data": json.dumps(
                                                {
                                                    "session_id": session_id,
                                                    "result": result_text,
                                                    "messages": [
                                                        m.model_dump()
                                                        for m in final_messages
                                                    ],
                                                }
                                            ),
                                        }
                                    else:
                                        # All other events (token, thinking,
                                        # tool_call_start, tool_call, tool_result,
                                        # error) are forwarded verbatim.
                                        yield {
                                            "event": current_event,
                                            "data": current_data,
                                        }

                                # Reset for next event block
                                current_event = None
                                current_data = None

            except Exception as exc:  # noqa: BLE001
                yield {
                    "event": StreamEventType.error.value,
                    "data": json.dumps({"message": str(exc)}),
                }

        return EventSourceResponse(event_generator())

    @app.get("/sessions/{session_id}")
    async def session_info(session_id: str) -> dict[str, Any]:
        """Return session metadata."""
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail="Session not found")

        session = _sessions[session_id]
        return SessionInfo(
            session_id=session_id,
            status=session["status"],
            turn_count=session["turn_count"],
        ).model_dump()

    @app.get("/sessions/{session_id}/tools")
    async def session_tools(session_id: str) -> dict[str, Any]:
        """Return tools available to a session from its routing table.

        If the session has no cached routing table yet (e.g. before the first
        turn has been sent), runs service discovery against the default service
        list on demand and caches the result so subsequent calls are fast.
        """
        session = _sessions.get(session_id)
        routing_table: dict[str, Any] | None = (
            session.get("routing_table") if session else None
        )
        if routing_table is None:
            routing_table = await discover_services(DEFAULT_SERVICES, _dapr_url)
            # Cache for later: create the session entry if it doesn't exist yet.
            if session_id not in _sessions:
                _sessions[session_id] = {"turn_count": 0, "status": "active"}
            _sessions[session_id]["routing_table"] = routing_table
        return {"tools": routing_table.get("_tool_specs", [])}

    @app.get("/sessions/{session_id}/modes")
    async def session_modes(session_id: str) -> dict[str, Any]:
        """Return modes available to a session from its routing table.

        If the session has no cached routing table yet (e.g. before the first
        turn has been sent), runs service discovery against the default service
        list on demand and caches the result so subsequent calls are fast.
        Modes are collected from each service's /describe response during
        discovery, flowing through the same pipeline as tools.
        """
        session = _sessions.get(session_id)
        routing_table: dict[str, Any] | None = (
            session.get("routing_table") if session else None
        )
        if routing_table is None:
            routing_table = await discover_services(DEFAULT_SERVICES, _dapr_url)
            # Cache for later: create the session entry if it doesn't exist yet.
            if session_id not in _sessions:
                _sessions[session_id] = {"turn_count": 0, "status": "active"}
            _sessions[session_id]["routing_table"] = routing_table
        return {"modes": routing_table.get("_modes", [])}

    @app.get("/sessions/{session_id}/agents")
    async def session_agents(session_id: str) -> dict[str, Any]:
        """Return agents available to a session from its routing table.

        If the session has no cached routing table yet (e.g. before the first
        turn has been sent), runs service discovery against the default service
        list on demand and caches the result so subsequent calls are fast.
        Agents are collected from each service's /describe response during
        discovery, flowing through the same pipeline as tools and modes.
        """
        session = _sessions.get(session_id)
        routing_table: dict[str, Any] | None = (
            session.get("routing_table") if session else None
        )
        if routing_table is None:
            routing_table = await discover_services(DEFAULT_SERVICES, _dapr_url)
            # Cache for later: create the session entry if it doesn't exist yet.
            if session_id not in _sessions:
                _sessions[session_id] = {"turn_count": 0, "status": "active"}
            _sessions[session_id]["routing_table"] = routing_table
        return {"agents": routing_table.get("_agents", [])}

    @app.post("/sessions/{session_id}/clear")
    async def session_clear(session_id: str) -> dict[str, Any]:
        """Reset session state to initial values."""
        # Upsert: create a fresh session entry whether or not one already existed.
        _sessions[session_id] = {"turn_count": 0, "status": "active"}
        return {"status": "cleared"}

    return app


app = create_session_app()
