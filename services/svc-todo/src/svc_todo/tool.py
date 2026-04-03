"""TodoTool — AI-managed todo list for self-accountability through complex turns."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from amplifier_service_sdk.models import ToolResult


logger = logging.getLogger(__name__)


class TodoTool:
    """AI-managed todo list for self-accountability through complex turns."""

    name = "todo"

    description = """Manage your todo list for tracking complex multi-step tasks.

Use this tool to:
- Create a todo list when starting complex multi-step work
- Update the list as you complete each step
- Stay accountable and focused through long turns

Todo items have:
- content: Imperative description (e.g., "Run tests", "Build project")
- activeForm: Present continuous (e.g., "Running tests", "Building project")
- status: "pending" | "in_progress" | "completed"

Recommended pattern:
1. Create list when you start complex multi-step work
2. Update after completing each step
3. Keep exactly ONE item as "in_progress" at a time
4. Mark items "completed" immediately after finishing"""

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "update", "list"],
                "description": "Action to perform: create (replace all), update (replace all), list (read current)",
            },
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Imperative description: 'Run tests', 'Build project'",
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "Present continuous: 'Running tests', 'Building project'",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Current status of this todo item",
                        },
                    },
                    "required": ["content", "status", "activeForm"],
                },
                "description": "List of todos (required for create/update, ignored for list)",
            },
        },
        "required": ["action"],
    }

    def __init__(self, session_id: str | None = None) -> None:
        self._todo_state: list[dict[str, Any]] = []
        self._session_id = session_id

    async def _save_state(self) -> None:
        """Persist current todo state to Dapr state store (fire-and-forget)."""
        port = os.environ.get("DAPR_HTTP_PORT", "3500")
        url = f"http://localhost:{port}/v1.0/state/statestore"
        key = f"todo-{self._session_id}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=[{"key": key, "value": self._todo_state}]
                )
                response.raise_for_status()
        except Exception:
            logger.exception("Failed to save todo state to Dapr state store")

    def _validate_todos(self, todos: list[dict[str, Any]]) -> ToolResult | None:
        """Validate todos list; return error ToolResult on failure, None on success."""
        valid_statuses = {"pending", "in_progress", "completed"}
        for i, todo in enumerate(todos):
            if not all(k in todo for k in ["content", "status", "activeForm"]):
                return ToolResult(
                    success=False,
                    error={
                        "message": f"Todo {i} missing required fields (content, status, activeForm)"
                    },
                )
            if todo["status"] not in valid_statuses:
                return ToolResult(
                    success=False,
                    error={"message": f"Todo {i} has invalid status: {todo['status']}"},
                )
        return None

    async def _handle_create(self, todos: list[dict[str, Any]]) -> ToolResult:
        """Replace entire list with new todos."""
        error = self._validate_todos(todos)
        if error is not None:
            return error
        self._todo_state = todos
        return ToolResult(
            success=True,
            output={"status": "created", "count": len(todos), "todos": todos},
        )

    async def _handle_update(self, todos: list[dict[str, Any]]) -> ToolResult:
        """Replace entire list (AI manages state transitions)."""
        error = self._validate_todos(todos)
        if error is not None:
            return error
        self._todo_state = todos
        pending = sum(1 for t in todos if t["status"] == "pending")
        in_progress = sum(1 for t in todos if t["status"] == "in_progress")
        completed = sum(1 for t in todos if t["status"] == "completed")
        return ToolResult(
            success=True,
            output={
                "status": "updated",
                "count": len(todos),
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
            },
        )

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute todo operation.

        Actions:
        - create: Replace entire list with new todos
        - update: Replace entire list (AI manages state transitions)
        - list: Return current todos
        """
        action = input.get("action")

        if action == "create":
            result = await self._handle_create(input.get("todos", []))
            if self._session_id and result.success:
                await self._save_state()
            return result

        if action == "update":
            result = await self._handle_update(input.get("todos", []))
            if self._session_id and result.success:
                await self._save_state()
            return result

        if action == "list":
            return ToolResult(
                success=True,
                output={
                    "status": "listed",
                    "count": len(self._todo_state),
                    "todos": self._todo_state,
                },
            )

        return ToolResult(
            success=False,
            error={
                "message": f"Unknown action: {action}. Valid actions: create, update, list"
            },
        )
