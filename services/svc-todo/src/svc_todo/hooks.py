"""Todo hooks — TodoReminderHook and TodoDisplayHook."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import httpx

from amplifier_service_sdk.models import HookEvent, HookResult

logger = logging.getLogger(__name__)

_DAPR_PORT_DEFAULT = "3500"
_DAPR_STATE_STORE = "statestore"

# Status symbols
_SYMBOL_COMPLETED = "✓"
_SYMBOL_IN_PROGRESS = "→"
_SYMBOL_PENDING = "☐"


class TodoReminderHook:
    """Pre-hook on provider:request — injects current todo state as a system reminder."""

    name = "todo_reminder"
    priority: int = 10
    mode: Literal["sync", "async"] = "sync"

    async def _read_state(self, session_id: str) -> list[dict[str, Any]]:
        """Read todo state from Dapr state store for the given session_id."""
        port = os.environ.get("DAPR_HTTP_PORT", _DAPR_PORT_DEFAULT)
        url = (
            f"http://localhost:{port}/v1.0/state/{_DAPR_STATE_STORE}/todo-{session_id}"
        )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                if response.status_code == 204:
                    return []
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, list) else []
        except Exception:
            logger.exception("Failed to read todo state from Dapr state store")
            return []

    def _format_todos(self, todos: list[dict[str, Any]]) -> str:
        """Format todos with status symbols for injection."""
        lines: list[str] = []
        for todo in todos:
            status = todo.get("status", "")
            if status == "completed":
                lines.append(f"{_SYMBOL_COMPLETED} {todo.get('content', '')}")
            elif status == "in_progress":
                lines.append(f"{_SYMBOL_IN_PROGRESS} {todo.get('activeForm', '')}")
            else:  # unknown status treated as pending
                lines.append(f"{_SYMBOL_PENDING} {todo.get('content', '')}")
        return "\n".join(lines)

    async def handle(self, event: HookEvent) -> HookResult:
        """Inject todo reminder on provider:request; CONTINUE otherwise."""
        if event.event != "provider:request":
            return HookResult(action="CONTINUE")

        session_id = event.data.get("session_id")
        if not session_id:
            return HookResult(action="CONTINUE")

        todos = await self._read_state(
            str(session_id)
        )  # data values are Any; coerce to str
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
            action="INJECT_CONTEXT", data={"content": content, "ephemeral": True}
        )


class TodoDisplayHook:
    """Post-hook on tool:post — formats todo progress for display after todo tool calls."""

    name = "todo_display"
    priority: int = 50
    mode: Literal["sync", "async"] = "sync"

    async def handle(self, event: HookEvent) -> HookResult:
        """Format todo progress on tool:post for the todo tool; CONTINUE otherwise."""
        if event.event != "tool:post":
            return HookResult(action="CONTINUE")

        tool_name = event.data.get("tool_name")
        if tool_name != "todo":
            return HookResult(action="CONTINUE")

        result: dict[str, Any] = event.data.get("result") or {}
        output: dict[str, Any] = result.get("output") or {}
        status = output.get("status")

        if status not in ("created", "updated"):
            return HookResult(action="CONTINUE")

        count: int = output.get("count", 0)
        completed: int = output.get("completed", 0)
        in_progress: int = output.get("in_progress", 0)
        pending: int = output.get("pending", 0)

        display = f"{completed}/{count} done, {in_progress} active, {pending} pending"
        return HookResult(action="CONTINUE", data={"display": display})
