"""Todo reminder pre-hook: injects todo state before each provider request."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import httpx

from amplifier_service_sdk.models import HookResult

logger = logging.getLogger(__name__)

_DAPR_PORT_DEFAULT = "3500"
_DAPR_STATE_STORE = "statestore"

_SYMBOL_COMPLETED = "✓"
_SYMBOL_IN_PROGRESS = "→"
_SYMBOL_PENDING = "☐"


class TodoReminderHook:
    """Pre-hook on provider:request — injects current todo state as a system reminder.

    Reads todo state from Dapr state store keyed by session_id.
    Formats todos with status symbols and wraps in a system-reminder tag.
    Returns INJECT_CONTEXT with ephemeral=True so the context is injected once
    and does not persist in history.

    Returns CONTINUE if:
    - Event is not provider:request
    - No session_id in data
    - Todo state is empty
    - _read_state raises an exception
    """

    name: str = "todo_reminder"
    events: list[str] = ["provider:request"]
    priority: int = 10
    mode: Literal["sync", "async"] = "sync"

    async def _read_state(self, session_id: str) -> list[dict[str, Any]]:
        """Read todo state from Dapr state store for the given session_id.

        Args:
            session_id: The session identifier used to key todo state.

        Returns:
            List of todo dicts, or empty list for 204/empty responses.

        Raises:
            httpx.HTTPError: On HTTP errors (non-204, non-200 responses).
            Exception: On network failures or unexpected errors.
        """
        port = os.environ.get("DAPR_HTTP_PORT", _DAPR_PORT_DEFAULT)
        url = (
            f"http://localhost:{port}/v1.0/state/{_DAPR_STATE_STORE}/todo-{session_id}"
        )

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            if response.status_code == 204 or not response.content:
                return []
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []

    def _format_todos(self, todos: list[dict[str, Any]]) -> str:
        """Format todo items with status symbols.

        Args:
            todos: List of todo dicts with 'status', 'content', 'activeForm' fields.

        Returns:
            Formatted string with one todo per line, prefixed by status symbol.
        """
        lines: list[str] = []
        for todo in todos:
            status = todo.get("status", "")
            if status == "completed":
                lines.append(f"{_SYMBOL_COMPLETED} {todo.get('content', '')}")
            elif status == "in_progress":
                lines.append(f"{_SYMBOL_IN_PROGRESS} {todo.get('activeForm', '')}")
            elif status == "pending":
                lines.append(f"{_SYMBOL_PENDING} {todo.get('content', '')}")
            else:
                logger.warning(
                    "TodoReminderHook: unknown todo status %r, rendering as pending",
                    status,
                )
                lines.append(f"{_SYMBOL_PENDING} {todo.get('content', '')}")
        return "\n".join(lines)

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Inject todo reminder on provider:request; CONTINUE otherwise.

        Args:
            event: The hook event name.
            data: Event data dict, expected to contain 'session_id'.

        Returns:
            HookResult with INJECT_CONTEXT action and ephemeral content,
            or CONTINUE if conditions are not met.
        """
        if event != "provider:request":
            return HookResult(action="CONTINUE")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="CONTINUE")

        try:
            todos = await self._read_state(str(session_id))
        except Exception:
            logger.exception("TodoReminderHook: failed to read state, skipping")
            return HookResult(action="CONTINUE")

        if not todos:
            return HookResult(action="CONTINUE")

        formatted = self._format_todos(todos)
        content = (
            f'<system-reminder source="hooks-todo-reminder">\n'
            f"{formatted}\n\n"
            f"DO NOT mention this reminder.\n"
            f"</system-reminder>"
        )
        return HookResult(
            action="INJECT_CONTEXT",
            data={"content": content, "ephemeral": True},
        )
