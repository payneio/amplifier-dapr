"""Tests for SkillsTool."""

from __future__ import annotations

import pytest

from svc_skills.tool import SkillsTool


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory with test skills."""
    # Create a test skill: python-standards
    skill_dir = tmp_path / "python-standards"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: python-standards\n"
        "description: Python coding standards and best practices\n"
        "version: 1.0.0\n"
        "license: MIT\n"
        "---\n\n"
        "# Python Standards\n\n"
        "Follow PEP 8 and use type hints.\n"
    )

    # Create a second skill: design-patterns
    skill_dir2 = tmp_path / "design-patterns"
    skill_dir2.mkdir()
    skill_file2 = skill_dir2 / "SKILL.md"
    skill_file2.write_text(
        "---\n"
        "name: design-patterns\n"
        "description: Software design patterns and architecture\n"
        "---\n\n"
        "# Design Patterns\n\n"
        "Use SOLID principles.\n"
    )

    return tmp_path


@pytest.fixture
def tool(skills_dir):
    """Create a SkillsTool pre-initialized with the temp skills dir."""
    t = SkillsTool(skills_dirs=[skills_dir])
    return t


class TestSkillsList:
    async def test_list_returns_all_skills(self, tool):
        """list=True returns all available skills."""
        result = await tool.execute({"list": True})
        assert result.success is True
        assert "skills" in result.output
        names = [s["name"] for s in result.output["skills"]]
        assert "python-standards" in names
        assert "design-patterns" in names

    async def test_list_empty_when_no_skills(self, tmp_path):
        """list=True with no skills returns a no-skills message."""
        t = SkillsTool(skills_dirs=[tmp_path])
        result = await t.execute({"list": True})
        assert result.success is True


class TestSkillsSearch:
    async def test_search_filters_by_name(self, tool):
        """search='python' returns matching skill."""
        result = await tool.execute({"search": "python"})
        assert result.success is True
        assert "matches" in result.output
        names = [s["name"] for s in result.output["matches"]]
        assert "python-standards" in names
        assert "design-patterns" not in names

    async def test_search_filters_by_description(self, tool):
        """search='architecture' finds skill with matching description."""
        result = await tool.execute({"search": "architecture"})
        assert result.success is True
        assert "matches" in result.output
        names = [s["name"] for s in result.output["matches"]]
        assert "design-patterns" in names


class TestSkillsLoad:
    async def test_load_skill_returns_content(self, tool):
        """skill_name='python-standards' loads full skill content."""
        result = await tool.execute({"skill_name": "python-standards"})
        assert result.success is True
        assert "content" in result.output
        assert "python-standards" in result.output["content"]
        assert "PEP 8" in result.output["content"]
        assert "skill_directory" in result.output

    async def test_load_nonexistent_skill_returns_error(self, tool):
        """skill_name='nonexistent' returns error with success=False."""
        result = await tool.execute({"skill_name": "nonexistent"})
        assert result.success is False
        assert result.error is not None
        assert "nonexistent" in result.error["message"]


class TestSkillsInfo:
    async def test_skill_info_returns_metadata(self, tool):
        """info='python-standards' returns metadata without full content."""
        result = await tool.execute({"info": "python-standards"})
        assert result.success is True
        assert result.output["name"] == "python-standards"
        assert result.output["version"] == "1.0.0"
        assert result.output["license"] == "MIT"
        # Should not contain full body content
        assert "content" not in result.output


class TestSkillsNoParams:
    async def test_no_params_returns_error(self, tool):
        """Empty params returns error message."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "Must provide" in result.error["message"]
