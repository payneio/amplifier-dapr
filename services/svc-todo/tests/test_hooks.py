"""Tests for todo hooks."""
from __future__ import annotations

import pytest
from amplifier_service_sdk.models import HookEvent
from svc_todo.hooks import TodoReminderHook, TodoDisplayHook


class TestTodoReminderHook:
    @pytest.fixture
    def hook(self) -> TodoReminderHook:
        return TodoReminderHook()

    async def test_handle_returns_continue(self, hook: TodoReminderHook) -> None:
        """TodoReminderHook.handle always returns CONTINUE action."""
        event = HookEvent(event="tool_call", data={"tool": "todo"})
        result = await hook.handle(event)
        assert result.action == "CONTINUE"


class TestTodoDisplayHook:
    @pytest.fixture
    def hook(self) -> TodoDisplayHook:
        return TodoDisplayHook()

    async def test_handle_returns_continue(self, hook: TodoDisplayHook) -> None:
        """TodoDisplayHook.handle always returns CONTINUE action."""
        event = HookEvent(event="tool_result", data={"tool": "todo"})
        result = await hook.handle(event)
        assert result.action == "CONTINUE"
