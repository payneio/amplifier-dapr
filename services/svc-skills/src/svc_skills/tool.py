"""SkillsTool — loads domain knowledge from skills.

Ported from amplifier-skills, adapted for amplifier-service-sdk pattern.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from amplifier_service_sdk.models import ToolResult

from .discovery import (
    discover_skills,
    discover_skills_multi_source,
    extract_skill_body,
    get_default_skills_dirs,
)
from .sources import is_remote_source, resolve_skill_source

logger = logging.getLogger(__name__)


class SkillsTool:
    """Tool for loading domain knowledge from skills."""

    name = "load_skill"
    description = """\
Load domain knowledge from an available skill. Skills provide specialized knowledge, workflows,
best practices, and standards. Use when you need domain expertise, coding guidelines, or
architectural patterns.

Operations:

**List all skills:**
  load_skill(list=True)
  Returns a formatted list of all available skills with descriptions.

**Search for skills:**
  load_skill(search="pattern")
  Filters skills by name or description matching the search term.

**Get skill metadata:**
  load_skill(info="skill-name")
  Returns metadata (name, description, version, license, path) without loading full content.

**Load full skill content:**
  load_skill(skill_name="skill-name")
  Loads the complete skill content into context. Returns skill_directory path for accessing
  companion files referenced in the skill.

Usage Guidelines:
- Start tasks by listing or searching skills to discover relevant domain knowledge
- Use info operation to check skills before loading to conserve context
- Skills may reference companion files - use the returned skill_directory path with read_file tool
- Skills complement but don't replace documentation or web search

Skill Discovery:
- Skills are discovered from configured directories (workspace, user, or custom paths)
- First-match-wins priority if same skill exists in multiple directories
- Workspace skills (.amplifier/skills/) override user skills (~/.amplifier/skills/)
"""

    input_schema: dict = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of skill to load",
            },
            "list": {
                "type": "boolean",
                "description": "If true, return list of all available skills",
            },
            "search": {
                "type": "string",
                "description": "Search term to filter skills by name or description",
            },
            "info": {
                "type": "string",
                "description": "Get metadata for a specific skill without loading full content",
            },
            "source": {
                "type": "string",
                "description": "Register a new skill source. Accepts git+https:// URLs or local paths.",
            },
        },
    }

    def __init__(self, skills_dirs: list[Path] | None = None) -> None:
        self.loaded_skills: set[str] = set()
        self._initialized = False
        self._override_skills_dirs = skills_dirs
        self.skills_dirs: list[Path] = []
        self.skills: dict[str, Any] = {}

    async def _ensure_initialized(self) -> None:
        """Lazy initialization — resolve skill sources on first use."""
        if self._initialized:
            return
        self._initialized = True
        if self._override_skills_dirs is not None:
            self.skills_dirs = self._override_skills_dirs
        else:
            self.skills_dirs = get_default_skills_dirs()
        self.skills = discover_skills_multi_source(self.skills_dirs)
        logger.info(
            f"Discovered {len(self.skills)} skills from {len(self.skills_dirs)} sources"
        )

    async def _resolve_source(self, source: str) -> Path | None:
        """Resolve a source string to a local directory path."""
        if source.startswith("@"):
            return None  # @mention resolution not available in service mode

        if is_remote_source(source):
            return await resolve_skill_source(source)

        path = Path(source).expanduser().resolve()
        return path if path.exists() else None

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute skill tool operation."""
        await self._ensure_initialized()

        # Source registration
        source_str = input.get("source")
        source_summary = None
        if source_str:
            resolved_path = await self._resolve_source(source_str)
            if resolved_path is None:
                return ToolResult(
                    success=False,
                    output=f"Could not resolve source: {source_str}",
                )

            new_skills = discover_skills(resolved_path)

            added = []
            for name, metadata in new_skills.items():
                if name not in self.skills:
                    self.skills[name] = metadata
                    added.append(name)

            source_summary = (
                f"Source '{source_str}' resolved to {resolved_path}. "
                f"Found {len(new_skills)} skill(s), {len(added)} new: "
                f"{', '.join(sorted(added)) if added else 'none (all duplicates)'}."
            )

            has_other_params = any(
                input.get(k) for k in ("skill_name", "list", "search", "info")
            )
            if not has_other_params:
                return ToolResult(success=True, output=source_summary)

        if input.get("list"):
            return self._list_skills()

        if search_term := input.get("search"):
            return self._search_skills(search_term)

        if skill_name := input.get("info"):
            return self._get_skill_info(skill_name)

        skill_name = input.get("skill_name")
        if not skill_name:
            return ToolResult(
                success=False,
                error={
                    "message": "Must provide skill_name, list=true, search='term', or info='name'"
                },
            )

        return await self._load_skill(skill_name)

    def _list_skills(self) -> ToolResult:
        """List all available skills."""
        if not self.skills:
            sources = ", ".join(str(d) for d in self.skills_dirs)
            return ToolResult(
                success=True, output={"message": f"No skills found in {sources}"}
            )

        skills_list = []
        for name, metadata in sorted(self.skills.items()):
            skills_list.append({"name": name, "description": metadata.description})

        lines = ["Available Skills:", ""]
        for skill in skills_list:
            lines.append(f"**{skill['name']}**: {skill['description']}")

        return ToolResult(
            success=True, output={"message": "\n".join(lines), "skills": skills_list}
        )

    def _search_skills(self, search_term: str) -> ToolResult:
        """Search skills by name or description."""
        matches = {}
        for name, metadata in self.skills.items():
            if (
                search_term.lower() in name.lower()
                or search_term.lower() in metadata.description.lower()
            ):
                matches[name] = metadata

        if not matches:
            return ToolResult(
                success=True, output={"message": f"No skills matching '{search_term}'"}
            )

        lines = [f"Skills matching '{search_term}':", ""]
        results = []
        for name, metadata in sorted(matches.items()):
            lines.append(f"**{name}**: {metadata.description}")
            results.append({"name": name, "description": metadata.description})

        return ToolResult(
            success=True, output={"message": "\n".join(lines), "matches": results}
        )

    def _get_skill_info(self, skill_name: str) -> ToolResult:
        """Get metadata for a skill without loading full content."""
        if skill_name not in self.skills:
            available = ", ".join(sorted(self.skills.keys()))
            return ToolResult(
                success=False,
                error={
                    "message": f"Skill '{skill_name}' not found. Available: {available}"
                },
            )

        metadata = self.skills[skill_name]
        info = {
            "name": metadata.name,
            "description": metadata.description,
            "version": metadata.version,
            "license": metadata.license,
            "compatibility": metadata.compatibility,
            "allowed_tools": metadata.allowed_tools,
            "path": str(metadata.path),
        }

        if metadata.metadata:
            info["metadata"] = metadata.metadata

        return ToolResult(success=True, output=info)

    async def _load_skill(self, skill_name: str) -> ToolResult:
        """Load full skill content."""
        if skill_name not in self.skills:
            available = ", ".join(sorted(self.skills.keys()))
            return ToolResult(
                success=False,
                error={
                    "message": f"Skill '{skill_name}' not found. Available: {available}"
                },
            )

        metadata = self.skills[skill_name]
        body = extract_skill_body(metadata.path)

        if not body:
            return ToolResult(
                success=False,
                error={"message": f"Failed to load content from {metadata.path}"},
            )

        logger.info(f"Loaded skill: {skill_name}")
        self.loaded_skills.add(skill_name)

        return ToolResult(
            success=True,
            output={
                "content": f"# {skill_name}\n\n{body}",
                "skill_name": skill_name,
                "skill_directory": str(metadata.path.parent),
                "loaded_from": metadata.source,
            },
        )
