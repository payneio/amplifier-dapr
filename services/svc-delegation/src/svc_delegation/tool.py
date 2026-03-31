"""DelegateTool — spawn child agent sessions via the orchestrator."""

from __future__ import annotations

from typing import Any

import httpx

from amplifier_service_sdk.models import ToolResult


class DelegateTool:
    """Tool that delegates work to a child agent session via the orchestrator."""

    name = "delegate"
    description = (
        "Spawn a child agent session by delegating a prompt to the orchestrator. "
        "Returns the child session ID and the result of the delegated work."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The prompt to send to the child agent session.",
            },
            "provider_name": {
                "type": "string",
                "description": "The LLM provider name to use for the child session.",
                "default": "mock",
            },
            "services": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of service names to make available in the child session.",
            },
            "workspace_content": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Workspace files (filename → content) to pass to the child session.",
            },
            "child_session_id": {
                "type": "string",
                "description": "Optional child session ID to resume an existing session.",
            },
        },
        "required": ["prompt"],
    }

    def __init__(self, orchestrator_base_url: str) -> None:
        """Initialize the DelegateTool with the orchestrator base URL.

        Args:
            orchestrator_base_url: Base URL for the orchestrator service
                (e.g. 'http://localhost:8080').
        """
        self._orchestrator_base_url = orchestrator_base_url

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a delegation request.

        Validates that 'prompt' is present, builds the orchestrator payload,
        and calls the orchestrator's delegate endpoint.

        Args:
            input: Tool input dict with at minimum {'prompt': str}.

        Returns:
            ToolResult with success=True and output={'child_session_id', 'result'}
            on success, or success=False with an error dict on failure.
        """
        prompt = input.get("prompt")
        if not prompt:
            return ToolResult(
                success=False,
                error={"message": "Missing required field: prompt"},
            )

        payload: dict[str, Any] = {
            "prompt": prompt,
            "provider_name": input.get("provider_name", "mock"),
            "services": input.get("services", []),
            "workspace_content": input.get("workspace_content", {}),
        }
        if "child_session_id" in input:
            payload["child_session_id"] = input["child_session_id"]

        try:
            result = await self._call_orchestrator(payload)
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error={
                    "message": f"Orchestrator returned HTTP {exc.response.status_code}"
                },
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Orchestrator unreachable"},
            )

        # Orchestrator may return 'child_session_id' (delegated result) or 'session_id'
        child_session_id = result.get("child_session_id", result.get("session_id", ""))
        return ToolResult(
            success=True,
            output={
                "child_session_id": child_session_id,
                "result": result,
            },
        )

    async def _call_orchestrator(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST the delegation payload to the orchestrator.

        Args:
            payload: The request body to send.

        Returns:
            The parsed JSON response from the orchestrator.

        Raises:
            httpx.HTTPStatusError: If the orchestrator returns a 4xx/5xx status.
            httpx.RequestError: If the orchestrator is unreachable.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._orchestrator_base_url}/orchestrator/delegate",
                json=payload,
                timeout=300.0,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
