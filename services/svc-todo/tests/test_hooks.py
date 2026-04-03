"""Tests for todo hooks."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from svc_todo.hooks import TodoDisplayHook, TodoReminderHook


class TestTodoReminderHook:
    @pytest.fixture
    def hook(self) -> TodoReminderHook:
        return TodoReminderHook()

    async def test_non_provider_request_continues(self, hook: TodoReminderHook) -> None:
        """Returns CONTINUE for non-provider:request events (e.g. tool:pre)."""
        result = await hook.handle("tool:pre", {"session_id": "abc"})
        assert result.action == "CONTINUE"

    async def test_no_session_id_continues(self, hook: TodoReminderHook) -> None:
        """Returns CONTINUE when session_id is absent from event data."""
        result = await hook.handle("provider:request", {})
        assert result.action == "CONTINUE"

    async def test_empty_state_continues(self, hook: TodoReminderHook) -> None:
        """Returns CONTINUE when _read_state returns an empty list."""
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=[]):
            result = await hook.handle("provider:request", {"session_id": "abc"})
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
        with patch.object(
            hook, "_read_state", new_callable=AsyncMock, return_value=todos
        ):
            result = await hook.handle("provider:request", {"session_id": "abc"})
        assert result.action == "INJECT_CONTEXT"
        assert result.context_injection is not None
        assert result.ephemeral is True
        content = result.context_injection
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
        with patch.object(
            hook, "_read_state", new_callable=AsyncMock, return_value=todos
        ):
            result = await hook.handle("provider:request", {"session_id": "abc"})
        assert result.action == "INJECT_CONTEXT"
        assert result.context_injection is not None
        content = result.context_injection
        assert "✓ Done task" in content
        assert "→ Working on active" in content
        assert "☐ Pending task" in content

    async def test_events_class_attr(self, hook: TodoReminderHook) -> None:
        """TodoReminderHook.events must be ['provider:request']."""
        assert hook.events == ["provider:request"]


class TestTodoDisplayHook:
    @pytest.fixture
    def hook(self) -> TodoDisplayHook:
        return TodoDisplayHook()

    async def test_non_tool_post_continues(self, hook: TodoDisplayHook) -> None:
        """Returns CONTINUE for non-tool:post events."""
        result = await hook.handle("provider:request", {"tool_name": "todo"})
        assert result.action == "CONTINUE"

    async def test_non_todo_tool_continues(self, hook: TodoDisplayHook) -> None:
        """Returns CONTINUE for tool:post events where tool_name is not 'todo'."""
        result = await hook.handle("tool:post", {"tool_name": "bash", "result": {}})
        assert result.action == "CONTINUE"

    async def test_todo_tool_post_formats_progress(self, hook: TodoDisplayHook) -> None:
        """Formats progress string with pending count and fraction for todo tool:post."""
        result = await hook.handle(
            "tool:post",
            {
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
        assert result.action == "CONTINUE"
        assert result.data is not None
        display = result.data["display"]
        # Spec: "completed/count done, in_progress active, pending pending"
        assert display == "1/3 done, 1 active, 1 pending"

    async def test_events_class_attr(self, hook: TodoDisplayHook) -> None:
        """TodoDisplayHook.events must be ['tool:post']."""
        assert hook.events == ["tool:post"]
