"""Tests for ModeHooks — hook lifecycle and tool enforcement."""

from __future__ import annotations

import pytest

from svc_modes.hook import HookResult, ModeDefinition, ModeHooks


@pytest.fixture
def hooks() -> ModeHooks:
    return ModeHooks()


PLAN_MODE = ModeDefinition(
    name="plan",
    description="Think and discuss — no writing",
    safe_tools=["read_file", "grep"],
    block_tools=["bash", "write_file"],
)


class TestModeHooksLifecycle:
    def test_initial_mode_is_none(self, hooks: ModeHooks) -> None:
        assert hooks.get_active_mode() is None

    def test_set_active_mode(self, hooks: ModeHooks) -> None:
        hooks.set_active_mode(PLAN_MODE)
        assert hooks.get_active_mode() is PLAN_MODE

    def test_clear_active_mode(self, hooks: ModeHooks) -> None:
        hooks.set_active_mode(PLAN_MODE)
        hooks.clear_active_mode()
        assert hooks.get_active_mode() is None


class TestModeHooksHandle:
    async def test_no_active_mode_continues(self, hooks: ModeHooks) -> None:
        result = await hooks.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    async def test_safe_tool_continues(self, hooks: ModeHooks) -> None:
        hooks.set_active_mode(PLAN_MODE)
        result = await hooks.handle("tool:pre", {"tool_name": "read_file"})
        assert result.action == "CONTINUE"

    async def test_blocked_tool_denies(self, hooks: ModeHooks) -> None:
        hooks.set_active_mode(PLAN_MODE)
        result = await hooks.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "DENY"
        assert result.reason is not None

    async def test_unknown_tool_continues_by_default(self, hooks: ModeHooks) -> None:
        """Tools not in safe or block lists continue (unlisted = allow)."""
        hooks.set_active_mode(PLAN_MODE)
        result = await hooks.handle("tool:pre", {"tool_name": "some_unknown_tool"})
        assert result.action == "CONTINUE"


class TestHookResultDataclass:
    def test_default_action_is_continue(self) -> None:
        result = HookResult()
        assert result.action == "CONTINUE"

    def test_can_set_reason(self) -> None:
        result = HookResult(action="DENY", reason="blocked by mode")
        assert result.reason == "blocked by mode"

    def test_optional_fields_default_none(self) -> None:
        result = HookResult()
        assert result.reason is None
        assert result.context_injection is None
        assert result.context_injection_role is None
        assert result.ephemeral is None


class TestModeDefinitionDataclass:
    def test_minimal_mode_definition(self) -> None:
        mode = ModeDefinition(name="focus")
        assert mode.name == "focus"
        assert mode.safe_tools == []
        assert mode.block_tools == []

    def test_full_mode_definition(self) -> None:
        mode = ModeDefinition(
            name="readonly",
            description="Read only mode",
            safe_tools=["read_file"],
            block_tools=["write_file"],
        )
        assert mode.safe_tools == ["read_file"]
        assert mode.block_tools == ["write_file"]
