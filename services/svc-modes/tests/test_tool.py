"""Tests for ModeTool — list, current, set, clear, error cases."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from svc_modes.hook import ModeDefinition, ModeHooks
from svc_modes.tool import ModeTool


@pytest.fixture
def hooks() -> ModeHooks:
    return ModeHooks()


@pytest.fixture
def tool(hooks: ModeHooks) -> ModeTool:
    t = ModeTool()
    t._mode_hooks = hooks
    return t


@pytest.fixture
def tool_no_hooks() -> ModeTool:
    """ModeTool with no _mode_hooks wired (not_ready state)."""
    return ModeTool()


SAMPLE_MODE = ModeDefinition(
    name="plan",
    description="Think and discuss",
    safe_tools=["read_file", "grep"],
    block_tools=["bash"],
)


class TestList:
    async def test_list_returns_modes(self, tool: ModeTool) -> None:
        with patch.object(tool, "_discover_modes", return_value=[SAMPLE_MODE]):
            result = await tool.execute({"operation": "list"})
        assert result.success is True
        assert "modes" in result.output
        assert any(m["name"] == "plan" for m in result.output["modes"])

    async def test_list_empty_when_no_modes(self, tool: ModeTool) -> None:
        with patch.object(tool, "_discover_modes", return_value=[]):
            result = await tool.execute({"operation": "list"})
        assert result.success is True
        assert result.output["modes"] == []


class TestCurrent:
    async def test_current_returns_none_when_no_active_mode(
        self, tool: ModeTool
    ) -> None:
        result = await tool.execute({"operation": "current"})
        assert result.success is True
        assert result.output["active_mode"] is None


class TestSet:
    async def test_set_then_current_shows_mode(self, tool: ModeTool) -> None:
        with patch.object(tool, "_discover_modes", return_value=[SAMPLE_MODE]):
            set_result = await tool.execute({"operation": "set", "name": "plan"})
        assert set_result.success is True

        current_result = await tool.execute({"operation": "current"})
        assert current_result.success is True
        assert current_result.output["active_mode"] == "plan"

    async def test_set_missing_name_returns_error(self, tool: ModeTool) -> None:
        result = await tool.execute({"operation": "set"})
        assert result.success is False
        assert result.error is not None
        assert (
            "name" in result.error["code"]
            or "missing" in result.error["message"].lower()
        )

    async def test_set_unknown_mode_returns_error(self, tool: ModeTool) -> None:
        with patch.object(tool, "_discover_modes", return_value=[]):
            result = await tool.execute({"operation": "set", "name": "nonexistent"})
        assert result.success is False
        assert result.error is not None


class TestClear:
    async def test_clear_deactivates_mode(
        self, tool: ModeTool, hooks: ModeHooks
    ) -> None:
        hooks.set_active_mode(SAMPLE_MODE)
        assert hooks.get_active_mode() is not None

        result = await tool.execute({"operation": "clear"})
        assert result.success is True
        assert hooks.get_active_mode() is None


class TestInvalidOperation:
    async def test_invalid_operation_returns_error(self, tool: ModeTool) -> None:
        result = await tool.execute({"operation": "bogus"})
        assert result.success is False
        assert result.error is not None
        assert "invalid_operation" in result.error["code"]


class TestNotReady:
    async def test_list_not_ready_when_no_hooks(self, tool_no_hooks: ModeTool) -> None:
        result = await tool_no_hooks.execute({"operation": "list"})
        assert result.success is False
        assert result.error["code"] == "not_ready"

    async def test_current_not_ready_when_no_hooks(
        self, tool_no_hooks: ModeTool
    ) -> None:
        result = await tool_no_hooks.execute({"operation": "current"})
        assert result.success is False
        assert result.error["code"] == "not_ready"

    async def test_set_not_ready_when_no_hooks(self, tool_no_hooks: ModeTool) -> None:
        result = await tool_no_hooks.execute({"operation": "set", "name": "plan"})
        assert result.success is False
        assert result.error["code"] == "not_ready"

    async def test_clear_not_ready_when_no_hooks(self, tool_no_hooks: ModeTool) -> None:
        result = await tool_no_hooks.execute({"operation": "clear"})
        assert result.success is False
        assert result.error["code"] == "not_ready"
