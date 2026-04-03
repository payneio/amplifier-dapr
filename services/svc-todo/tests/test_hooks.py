"""Tests for todo hooks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from amplifier_service_sdk.models import HookEvent
from svc_todo.hooks import TodoDisplayHook, TodoReminderHook


class TestTodoReminderHook:
    @pytest.fixture
    def hook(self) -> TodoReminderHook:
        return TodoReminderHook()

    async def test_non_provider_request_continues(self, hook: TodoReminderHook) -> None:
        """Returns CONTINUE for non-provider:request events (e.g. tool:pre)."""
        event = HookEvent(event="tool:pre", data={"session_id": "abc"})
        result = await hook.handle(event)
        assert result.action == "CONTINUE"

    async def test_no_session_id_continues(self, hook: TodoReminderHook) -> None:
        """Returns CONTINUE when session_id is absent from event data."""
        event = HookEvent(event="provider:request", data={})
        result = await hook.handle(event)
        assert result.action == "CONTINUE"

    async def test_empty_state_continues(self, hook: TodoReminderHook) -> None:
        """Returns CONTINUE when _read_state returns an empty list."""
        event = HookEvent(event="provider:request", data={"session_id": "abc"})
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=[]):
            result = await hook.handle(event)
        assert result.action == "CONTINUE"

    async def test_injects_context_with_todo_reminder_source(
        self, hook: TodoReminderHook
    ) -> None:
        """Returns INJECT_CONTEXT with system-reminder source and ephemeral=True."""
        todos = [
            {
                "content": "Write docs",
                "activeForm": "Writing docs",
                "status": "pending",
            },
        ]
        event = HookEvent(event="provider:request", data={"session_id": "abc"})
        with patch.object(
            hook, "_read_state", new_callable=AsyncMock, return_value=todos
        ):
            result = await hook.handle(event)
        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        assert result.data["ephemeral"] is True
        content = result.data["content"]
        assert 'source="hooks-todo-reminder"' in content
        assert "DO NOT mention this reminder" in content

    async def test_formats_status_symbols(self, hook: TodoReminderHook) -> None:
        """Formats todos with ✓ (completed/content), → (in_progress/activeForm), ☐ (pending/content)."""
        todos = [
            {
                "content": "Done task",
                "activeForm": "Finishing done task",
                "status": "completed",
            },
            {
                "content": "Active task",
                "activeForm": "Working on active",
                "status": "in_progress",
            },
            {
                "content": "Pending task",
                "activeForm": "About to start",
                "status": "pending",
            },
        ]
        event = HookEvent(event="provider:request", data={"session_id": "abc"})
        with patch.object(
            hook, "_read_state", new_callable=AsyncMock, return_value=todos
        ):
            result = await hook.handle(event)
        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        content = result.data["content"]
        assert "✓ Done task" in content
        assert "→ Working on active" in content
        assert "☐ Pending task" in content


class TestTodoDisplayHook:
    @pytest.fixture
    def hook(self) -> TodoDisplayHook:
        return TodoDisplayHook()

    async def test_non_tool_post_continues(self, hook: TodoDisplayHook) -> None:
        """Returns CONTINUE for non-tool:post events."""
        event = HookEvent(event="provider:request", data={"tool_name": "todo"})
        result = await hook.handle(event)
        assert result.action == "CONTINUE"

    async def test_non_todo_tool_continues(self, hook: TodoDisplayHook) -> None:
        """Returns CONTINUE for tool:post events where tool_name is not 'todo'."""
        event = HookEvent(event="tool:post", data={"tool_name": "bash", "result": {}})
        result = await hook.handle(event)
        assert result.action == "CONTINUE"

    async def test_todo_tool_post_formats_progress(self, hook: TodoDisplayHook) -> None:
        """Formats progress string with pending count and fraction for todo tool:post."""
        event = HookEvent(
            event="tool:post",
            data={
                "tool_name": "todo",
                "result": {
                    "output": {
                        "status": "updated",
                        "count": 3,
                        "completed": 1,
                        "in_progress": 1,
                        "pending": 1,
                    }
                },
            },
        )
        result = await hook.handle(event)
        assert result.action == "CONTINUE"
        assert result.data is not None
        display = result.data["display"]
        # Spec: "completed/count done, in_progress active, pending pending"
        assert display == "1/3 done, 1 active, 1 pending"
