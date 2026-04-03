"""Tests for TodoReminderHook — todo state context injection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from svc_hooks_todo_reminder.hook import TodoReminderHook


@pytest.fixture
def hook() -> TodoReminderHook:
    return TodoReminderHook()


class TestTodoReminderHook:
    """Covers TodoReminderHook behaviour for provider:request events."""

    async def test_non_provider_request_continues(self, hook: TodoReminderHook) -> None:
        """Returns CONTINUE for events that are not provider:request."""
        result = await hook.handle("tool:pre", {"session_id": "sess-1"})
        assert result.action == "CONTINUE"

    async def test_no_session_id_continues(self, hook: TodoReminderHook) -> None:
        """Returns CONTINUE if no session_id in data."""
        result = await hook.handle("provider:request", {})
        assert result.action == "CONTINUE"

    async def test_empty_state_continues(self, hook: TodoReminderHook) -> None:
        """Returns CONTINUE if todo state is empty."""
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=[]):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
        assert result.action == "CONTINUE"

    async def test_injects_reminder_with_hooks_todo_reminder_source_and_symbols(
        self, hook: TodoReminderHook
    ) -> None:
        """Injects INJECT_CONTEXT with hooks-todo-reminder source and ✓→☐ symbols."""
        todos = [
            {
                "status": "completed",
                "content": "Write tests",
                "activeForm": "Writing tests",
            },
            {
                "status": "in_progress",
                "content": "Implement hook",
                "activeForm": "Implementing hook",
            },
            {
                "status": "pending",
                "content": "Review code",
                "activeForm": "Reviewing code",
            },
        ]
        with patch.object(
            hook, "_read_state", new_callable=AsyncMock, return_value=todos
        ):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})

        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        content = result.data["content"]
        assert 'source="hooks-todo-reminder"' in content
        assert "✓" in content
        assert "→" in content
        assert "☐" in content

    async def test_completed_shows_content_not_active_form(
        self, hook: TodoReminderHook
    ) -> None:
        """Completed todos show 'content' field ('Write tests'), not 'activeForm' ('Writing tests')."""
        todos = [
            {
                "status": "completed",
                "content": "Write tests",
                "activeForm": "Writing tests",
            },
        ]
        with patch.object(
            hook, "_read_state", new_callable=AsyncMock, return_value=todos
        ):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})

        assert result.data is not None
        content = result.data["content"]
        assert "Write tests" in content
        assert "Writing tests" not in content

    async def test_in_progress_shows_active_form_field(
        self, hook: TodoReminderHook
    ) -> None:
        """In-progress todos show 'activeForm' field ('Implementing hook')."""
        todos = [
            {
                "status": "in_progress",
                "content": "Implement hook",
                "activeForm": "Implementing hook",
            },
        ]
        with patch.object(
            hook, "_read_state", new_callable=AsyncMock, return_value=todos
        ):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})

        assert result.data is not None
        content = result.data["content"]
        assert "Implementing hook" in content

    async def test_read_state_called_with_session_id(
        self, hook: TodoReminderHook
    ) -> None:
        """_read_state is called with the session_id from event data."""
        todos = [
            {
                "status": "pending",
                "content": "Do something",
                "activeForm": "Doing something",
            }
        ]
        mock_read = AsyncMock(return_value=todos)
        with patch.object(hook, "_read_state", mock_read):
            await hook.handle("provider:request", {"session_id": "my-session"})
        mock_read.assert_called_once_with("my-session")

    async def test_read_state_failure_returns_continue(
        self, hook: TodoReminderHook
    ) -> None:
        """Returns CONTINUE if _read_state raises an exception."""
        with patch.object(
            hook,
            "_read_state",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Dapr unavailable"),
        ):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})

        assert result.action == "CONTINUE"

    async def test_content_wraps_in_system_reminder_tags_and_ephemeral_is_true(
        self, hook: TodoReminderHook
    ) -> None:
        """Content wraps in <system-reminder> tags and ephemeral flag is True."""
        todos = [
            {
                "status": "pending",
                "content": "Do something",
                "activeForm": "Doing something",
            }
        ]
        with patch.object(
            hook, "_read_state", new_callable=AsyncMock, return_value=todos
        ):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})

        assert result.data is not None
        assert result.data["ephemeral"] is True
        content = result.data["content"]
        assert '<system-reminder source="hooks-todo-reminder">' in content
        assert "</system-reminder>" in content
        assert "DO NOT mention this reminder" in content
