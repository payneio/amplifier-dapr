"""ChildSessionSpawner — spawns child sessions via the session-service."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from svc_orchestrator.dapr_client import DaprClient


class ChildSessionRequest(BaseModel):
    """Request model for spawning a child session."""

    prompt: str
    child_session_id: str = ""
    provider_name: str = "mock"
    services: list[str] = Field(default_factory=list)
    workspace_content: dict[str, str] = Field(default_factory=dict)
    agent_ref: str = "default"


class ChildSessionSpawner:
    """Spawns child sessions by invoking the session-service via Dapr."""

    def __init__(
        self,
        dapr: DaprClient,
        session_service_app_id: str = "session-service",
    ) -> None:
        """Initialise the ChildSessionSpawner.

        Args:
            dapr: Async Dapr HTTP client used for service invocation.
            session_service_app_id: Dapr app ID for the session service.
        """
        self._dapr = dapr
        self._session_service_app_id = session_service_app_id

    async def spawn(self, request: ChildSessionRequest) -> dict[str, Any]:
        """Spawn a child session by invoking the session-service.

        Generates a session_id if ``request.child_session_id`` is empty.

        Args:
            request: The child session request parameters.

        Returns:
            Result dict returned by the session-service.
        """
        session_id = request.child_session_id or str(uuid4())[:8]

        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "provider_name": request.provider_name,
            "services": request.services,
            "workspace_content": request.workspace_content,
            "agent_ref": request.agent_ref,
        }

        result: dict[str, Any] = await self._dapr.invoke(
            self._session_service_app_id,
            f"sessions/{session_id}/turn",
            payload,
            timeout=300.0,
        )
        return {"session_id": session_id, **result}
