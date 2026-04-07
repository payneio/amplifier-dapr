"""HTTP client for the Amplifier IPC service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

_DEFAULT_BASE_URL = "http://localhost:8090"
_TIMEOUT = 120.0
_METADATA_TIMEOUT = 10.0  # metadata queries: tools, modes, clear


@dataclass
class SSEEvent:
    """A single Server-Sent Event."""

    event: str
    data: Any

    @classmethod
    def from_lines(cls, raw: str) -> SSEEvent | None:
        """Parse a raw SSE text block into an SSEEvent.

        Returns None for empty input. Defaults event type to 'message'
        when no event field is present. Parses data field as JSON; falls
        back to the raw string if JSON is malformed.
        """
        if not raw or not raw.strip():
            return None

        event_type = "message"
        data: Any = None

        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                raw_data = line[len("data:") :].strip()
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    data = raw_data

        return cls(event=event_type, data=data)


class SessionClient:
    """HTTP client for interacting with the Amplifier IPC session service."""

    def __init__(self, base_url: str = _DEFAULT_BASE_URL) -> None:
        self.base_url = base_url
        self._http: httpx.AsyncClient | None = None

    def _get_http(self) -> httpx.AsyncClient:
        """Return the HTTP client, creating one if needed."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=_TIMEOUT,
            )
        return self._http

    async def close(self) -> None:
        """Close the underlying HTTP client and release connection pool resources."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> SessionClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def create_session(
        self,
        agent_ref: str = "default",
        machine_config: dict[str, Any] | None = None,
        use_default_machine: bool = False,
    ) -> dict[str, Any]:
        """Create a new session via the session service.

        POST /sessions/create
        """
        if machine_config is None and use_default_machine:
            machine_config = {
                "type": "ssh",
                "host": "localhost",
                "working_dir": os.getcwd(),
            }
        http = self._get_http()
        body: dict[str, Any] = {
            "agent_ref": agent_ref,
            "machine_config": machine_config,
        }
        response = await http.post("/sessions/create", json=body, timeout=30.0)
        response.raise_for_status()
        return response.json()

    def _build_turn_body(
        self,
        prompt: str,
        workspace_content: dict[str, str] | None,
        provider_name: str | None,
        services: list[dict[str, Any]] | None,
        agent_ref: str | None = None,
    ) -> dict[str, Any]:
        """Build the request body for turn endpoints."""
        body: dict[str, Any] = {"prompt": prompt}
        if workspace_content is not None:
            body["workspace_content"] = workspace_content
        if provider_name is not None:
            body["provider_name"] = provider_name
        if services is not None:
            body["services"] = services
        if agent_ref is not None:
            body["agent_ref"] = agent_ref
        return body

    async def healthcheck(self) -> bool:
        """Check if the service is healthy.

        Returns True if the service responds with HTTP 200, False if the
        service is unreachable or returns a non-200 status.
        """
        http = self._get_http()
        try:
            response = await http.get("/healthz")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def send_turn(
        self,
        session_id: str,
        prompt: str,
        workspace_content: dict[str, str] | None = None,
        provider_name: str | None = None,
        services: list[dict[str, Any]] | None = None,
        agent_ref: str | None = None,
    ) -> dict[str, Any]:
        """Send a turn to the session service and return the response.

        POST /sessions/{session_id}/turn
        """
        http = self._get_http()
        body = self._build_turn_body(
            prompt, workspace_content, provider_name, services, agent_ref
        )
        response = await http.post(
            f"/sessions/{session_id}/turn",
            json=body,
        )
        response.raise_for_status()
        return response.json()

    async def stream_turn(
        self,
        session_id: str,
        prompt: str,
        workspace_content: dict[str, str] | None = None,
        provider_name: str | None = None,
        services: list[dict[str, Any]] | None = None,
        agent_ref: str | None = None,
    ) -> AsyncIterator[SSEEvent]:
        """Stream a turn from the session service as SSE events.

        POST /sessions/{session_id}/turn/stream
        Uses buffer-based SSE parsing, splitting on double newlines.
        """
        http = self._get_http()
        body = self._build_turn_body(
            prompt, workspace_content, provider_name, services, agent_ref
        )

        async with http.stream(
            "POST",
            f"/sessions/{session_id}/turn/stream",
            json=body,
        ) as response:
            response.raise_for_status()
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                # Normalize \r\n to \n for SSE parsing
                buffer = buffer.replace("\r\n", "\n")
                # SSE events are separated by double newlines
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    event = SSEEvent.from_lines(block)
                    if event is not None:
                        yield event

    async def get_session_info(self, session_id: str) -> dict[str, Any]:
        """Get information about a session.

        GET /sessions/{session_id}
        """
        http = self._get_http()
        response = await http.get(f"/sessions/{session_id}")
        response.raise_for_status()
        return response.json()

    async def get_tools(self, session_id: str) -> list[dict[str, Any]]:
        """Get the list of tools available to a session.

        GET /sessions/{session_id}/tools
        """
        http = self._get_http()
        response = await http.get(
            f"/sessions/{session_id}/tools", timeout=_METADATA_TIMEOUT
        )
        response.raise_for_status()
        return response.json().get("tools", [])

    async def get_modes(self, session_id: str) -> list[dict[str, Any]]:
        """Get the list of available modes for a session.

        GET /sessions/{session_id}/modes
        """
        http = self._get_http()
        response = await http.get(
            f"/sessions/{session_id}/modes", timeout=_METADATA_TIMEOUT
        )
        response.raise_for_status()
        return response.json().get("modes", [])

    async def get_agents(self, session_id: str) -> list[dict[str, Any]]:
        """Get the list of available agents for a session.

        GET /sessions/{session_id}/agents
        """
        http = self._get_http()
        response = await http.get(
            f"/sessions/{session_id}/agents", timeout=_METADATA_TIMEOUT
        )
        response.raise_for_status()
        return response.json().get("agents", [])

    async def clear_session(self, session_id: str) -> bool:
        """Reset session state to initial values.

        POST /sessions/{session_id}/clear
        """
        http = self._get_http()
        response = await http.post(
            f"/sessions/{session_id}/clear", timeout=_METADATA_TIMEOUT
        )
        response.raise_for_status()
        return response.json().get("status") == "cleared"
