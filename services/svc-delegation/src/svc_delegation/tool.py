"""DelegateTool — spawn child agent sessions via the orchestrator."""

from __future__ import annotations

from typing import Any

import httpx

from amplifier_service_sdk.models import ToolResult

MAX_DELEGATION_DEPTH = 10


class DelegateTool:
    """Tool that delegates work to a child agent session via the orchestrator."""

    name = "delegate"
    description = (
        "Spawn a specialized agent to handle tasks autonomously. "
        "Supports context inheritance, session resumption, and recursion guards."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "Clear instruction for the agent to execute.",
            },
            "agent": {
                "type": "string",
                "description": "Agent reference to delegate to (e.g. 'namespace:agent-name').",
            },
            "session_id": {
                "type": "string",
                "description": "Optional session ID to resume an existing child session.",
            },
            "context_depth": {
                "type": "string",
                "enum": ["none", "recent", "all"],
                "description": (
                    "How much parent context to pass: "
                    "'none' = no context, 'recent' = last N turns, 'all' = full history."
                ),
            },
            "context_scope": {
                "type": "string",
                "enum": ["conversation", "agents", "full"],
                "description": (
                    "Which messages to include: "
                    "'conversation' = user/assistant only, "
                    "'agents' = adds delegate tool results, "
                    "'full' = all messages."
                ),
            },
            "context_turns": {
                "type": "integer",
                "description": "Number of turns to include when context_depth is 'recent'.",
            },
            "model_role": {
                "type": "string",
                "description": "Override the agent's default model role for this delegation.",
            },
            "provider_preferences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "model": {"type": "string"},
                    },
                },
                "description": "Ordered list of provider/model preferences.",
            },
        },
        "required": ["instruction"],
    }

    def __init__(
        self,
        orchestrator_base_url: str,
        session_service_base_url: str | None = None,
        parent_session_id: str = "",
        delegation_depth: int = 0,
    ) -> None:
        """Initialize the DelegateTool.

        Args:
            orchestrator_base_url: Base URL for the orchestrator service.
            session_service_base_url: Base URL for the session service (for context fetching).
            parent_session_id: Session ID of the parent session (for context inheritance).
            delegation_depth: Current nesting depth for recursion guard.
        """
        self._orchestrator_base_url = orchestrator_base_url
        self._session_service_base_url = session_service_base_url
        self._parent_session_id = parent_session_id
        self._delegation_depth = delegation_depth

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a delegation request.

        Validates that 'instruction' is present, checks recursion depth,
        fetches parent context if requested, and calls the orchestrator.

        Args:
            input: Tool input dict with at minimum {'instruction': str}.

        Returns:
            ToolResult with success=True on success, or success=False with
            an error dict on failure.
        """
        instruction = input.get("instruction")
        if not instruction:
            return ToolResult(
                success=False,
                error={"message": "Missing required field: instruction"},
            )

        if self._delegation_depth >= MAX_DELEGATION_DEPTH:
            return ToolResult(
                success=False,
                error={
                    "message": (
                        f"Maximum delegation depth ({MAX_DELEGATION_DEPTH}) exceeded"
                    )
                },
            )

        # Fetch and filter parent context if requested
        context_depth = input.get("context_depth", "none")
        context_messages: list[dict[str, Any]] | None = None

        if context_depth != "none" and self._parent_session_id:
            try:
                raw_messages = await self._fetch_parent_messages(
                    self._parent_session_id
                )
                context_scope = input.get("context_scope", "conversation")
                context_turns = input.get("context_turns")
                context_messages = self._filter_context(
                    raw_messages, context_scope, context_depth, context_turns
                )
            except (httpx.RequestError, httpx.HTTPStatusError):
                # If we can't fetch context, proceed without it
                context_messages = None

        payload: dict[str, Any] = {
            "prompt": instruction,
            "delegation_depth": self._delegation_depth + 1,
        }

        if "agent" in input:
            payload["agent_ref"] = input["agent"]

        if "session_id" in input:
            payload["child_session_id"] = input["session_id"]

        if context_messages is not None:
            payload["context_messages"] = context_messages

        if "model_role" in input:
            payload["model_role"] = input["model_role"]

        if "provider_preferences" in input:
            payload["provider_preferences"] = input["provider_preferences"]

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

        return ToolResult(
            success=True,
            output=result,
        )

    def _filter_context(
        self,
        messages: list[dict[str, Any]],
        scope: str,
        depth: str,
        turns: int | None,
    ) -> list[dict[str, Any]]:
        """Filter parent context messages by scope and depth.

        Args:
            messages: Raw messages from the parent session.
            scope: 'conversation' (user/assistant only), 'agents' (adds delegate
                   tool results), or 'full' (all messages).
            depth: 'all' keeps all filtered messages, 'recent' keeps last N*2.
            turns: Number of turns for 'recent' depth (N).

        Returns:
            Filtered list of messages (system messages always removed).
        """
        # Remove system messages always
        filtered = [m for m in messages if m.get("role") != "system"]

        if scope == "conversation":
            filtered = [m for m in filtered if m.get("role") in ("user", "assistant")]
        elif scope == "agents":
            # Keeps user, assistant, and tool results from delegate calls
            filtered = [
                m for m in filtered if m.get("role") in ("user", "assistant", "tool")
            ]
        # scope == "full": keep everything (already removed system messages)

        if depth == "recent" and turns is not None and turns > 0:
            # "recent" takes last N*2 messages (N turns = N user + N assistant)
            filtered = filtered[-(turns * 2) :]

        return filtered

    async def _fetch_parent_messages(
        self, parent_session_id: str
    ) -> list[dict[str, Any]]:
        """Fetch messages from the parent session via the session service.

        Args:
            parent_session_id: The session ID to fetch messages for.

        Returns:
            List of message dicts from the session service.

        Raises:
            httpx.HTTPStatusError: If the session service returns 4xx/5xx.
            httpx.RequestError: If the session service is unreachable.
        """
        if not self._session_service_base_url:
            return []

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._session_service_base_url}/sessions/{parent_session_id}/messages",
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return data  # type: ignore[no-any-return]
            return data.get("messages", [])

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
