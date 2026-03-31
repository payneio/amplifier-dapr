"""Tests for TodoTool."""
from __future__ import annotations

import pytest
from svc_todo.tool import TodoTool


@pytest.fixture
def tool() -> TodoTool:
    """Create a fresh TodoTool instance."""
    return TodoTool()


VALID_TODO = {"content": "Write tests", "activeForm": "Writing tests", "status": "pending"}
VALID_TODO_2 = {"content": "Run tests", "activeForm": "Running tests", "status": "in_progress"}
VALID_TODO_3 = {"content": "Deploy", "activeForm": "Deploying", "status": "completed"}


class TestCreate:
    async def test_create_stores_todos(self, tool: TodoTool) -> None:
        """create action stores todos and returns count."""
        result = await tool.execute({"action": "create", "todos": [VALID_TODO, VALID_TODO_2]})
        assert result.success is True
        assert result.output["status"] == "created"
        assert result.output["count"] == 2
        assert result.output["todos"] == [VALID_TODO, VALID_TODO_2]

    async def test_create_replaces_existing_todos(self, tool: TodoTool) -> None:
        """create replaces any existing todo state."""
        await tool.execute({"action": "create", "todos": [VALID_TODO]})
        result = await tool.execute({"action": "create", "todos": [VALID_TODO_2, VALID_TODO_3]})
        assert result.success is True
        assert result.output["count"] == 2

    async def test_create_empty_list(self, tool: TodoTool) -> None:
        """create with empty todos list is valid."""
        result = await tool.execute({"action": "create", "todos": []})
        assert result.success is True
        assert result.output["count"] == 0


class TestUpdate:
    async def test_update_replaces_todos(self, tool: TodoTool) -> None:
        """update replaces todo state with new todos and returns counts."""
        await tool.execute({"action": "create", "todos": [VALID_TODO]})
        result = await tool.execute(
            {"action": "update", "todos": [VALID_TODO, VALID_TODO_2, VALID_TODO_3]}
        )
        assert result.success is True
        assert result.output["status"] == "updated"
        assert result.output["count"] == 3
        assert result.output["pending"] == 1
        assert result.output["in_progress"] == 1
        assert result.output["completed"] == 1

    async def test_update_counts_statuses(self, tool: TodoTool) -> None:
        """update returns correct pending/in_progress/completed counts."""
        todos = [
            {"content": "A", "activeForm": "Doing A", "status": "pending"},
            {"content": "B", "activeForm": "Doing B", "status": "pending"},
            {"content": "C", "activeForm": "Doing C", "status": "completed"},
        ]
        result = await tool.execute({"action": "update", "todos": todos})
        assert result.success is True
        assert result.output["pending"] == 2
        assert result.output["in_progress"] == 0
        assert result.output["completed"] == 1


class TestList:
    async def test_list_returns_empty_initially(self, tool: TodoTool) -> None:
        """list returns empty todos when nothing has been created."""
        result = await tool.execute({"action": "list"})
        assert result.success is True
        assert result.output["status"] == "listed"
        assert result.output["todos"] == []
        assert result.output["count"] == 0

    async def test_list_returns_current_state(self, tool: TodoTool) -> None:
        """list returns the current todo state after create."""
        await tool.execute({"action": "create", "todos": [VALID_TODO, VALID_TODO_2]})
        result = await tool.execute({"action": "list"})
        assert result.success is True
        assert result.output["count"] == 2
        assert VALID_TODO in result.output["todos"]


class TestInvalidAction:
    async def test_invalid_action_returns_error(self, tool: TodoTool) -> None:
        """Unknown actions like 'delete' return an error."""
        result = await tool.execute({"action": "delete"})
        assert result.success is False
        assert result.error is not None
        assert "delete" in result.error["message"] or "Unknown action" in result.error["message"]

    async def test_none_action_returns_error(self, tool: TodoTool) -> None:
        """Missing action returns an error."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None


class TestInvalidStatus:
    async def test_invalid_status_returns_error(self, tool: TodoTool) -> None:
        """Todo with invalid status returns an error."""
        bad_todo = {"content": "Test", "activeForm": "Testing", "status": "done"}
        result = await tool.execute({"action": "create", "todos": [bad_todo]})
        assert result.success is False
        assert result.error is not None
        assert "status" in result.error["message"].lower() or "done" in result.error["message"]


class TestMissingFields:
    async def test_missing_content_returns_error(self, tool: TodoTool) -> None:
        """Todo missing 'content' field returns an error."""
        bad_todo = {"activeForm": "Testing", "status": "pending"}
        result = await tool.execute({"action": "create", "todos": [bad_todo]})
        assert result.success is False
        assert result.error is not None

    async def test_missing_activeform_returns_error(self, tool: TodoTool) -> None:
        """Todo missing 'activeForm' field returns an error."""
        bad_todo = {"content": "Test", "status": "pending"}
        result = await tool.execute({"action": "create", "todos": [bad_todo]})
        assert result.success is False
        assert result.error is not None

    async def test_missing_status_returns_error(self, tool: TodoTool) -> None:
        """Todo missing 'status' field returns an error."""
        bad_todo = {"content": "Test", "activeForm": "Testing"}
        result = await tool.execute({"action": "create", "todos": [bad_todo]})
        assert result.success is False
        assert result.error is not None
