"""Tests for SkillsVisibilityHook."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from svc_skills.visibility_hook import SkillsVisibilityHook


def _make_metadata(description: str) -> Any:
    """Create a mock metadata object with a description attribute."""
    m = MagicMock()
    m.description = description
    return m


@pytest.fixture
def skills_tool_with_skills():
    """Mock SkillsTool with two skills loaded."""
    tool = MagicMock()
    tool.skills = {
        "python-standards": _make_metadata(
            "Python coding standards and best practices"
        ),
        "design-patterns": _make_metadata("Software design patterns and architecture"),
    }
    return tool


@pytest.fixture
def skills_tool_empty():
    """Mock SkillsTool with no skills."""
    tool = MagicMock()
    tool.skills = {}
    return tool


class TestSkillsVisibilityHook:
    """Tests for SkillsVisibilityHook."""

    async def test_non_provider_request_continues(
        self, skills_tool_with_skills
    ) -> None:
        """Non-provider:request events return CONTINUE."""
        hook = SkillsVisibilityHook(skills_tool=skills_tool_with_skills)
        result = await hook.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    async def test_injects_context_with_skill_names(
        self, skills_tool_with_skills
    ) -> None:
        """provider:request event injects context with hooks-skills-visibility source
        containing skill names 'python-standards' and 'design-patterns'."""
        hook = SkillsVisibilityHook(skills_tool=skills_tool_with_skills)
        result = await hook.handle("provider:request", {})
        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        content = result.data["content"]
        assert "python-standards" in content
        assert "design-patterns" in content
        assert result.data.get("ephemeral") is True

    async def test_empty_skills_continues(self, skills_tool_empty) -> None:
        """provider:request with empty skills dict returns CONTINUE."""
        hook = SkillsVisibilityHook(skills_tool=skills_tool_empty)
        result = await hook.handle("provider:request", {})
        assert result.action == "CONTINUE"

    async def test_content_starts_and_ends_with_system_reminder_tag(
        self, skills_tool_with_skills
    ) -> None:
        """Content starts with <system-reminder source="hooks-skills-visibility"> and ends with closing tag."""
        hook = SkillsVisibilityHook(skills_tool=skills_tool_with_skills)
        result = await hook.handle("provider:request", {})
        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        content = result.data["content"]
        assert content.startswith('<system-reminder source="hooks-skills-visibility">')
        assert content.endswith("</system-reminder>")
