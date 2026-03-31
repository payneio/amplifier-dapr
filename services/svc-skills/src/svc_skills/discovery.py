"""
Skill discovery and metadata parsing.
Shared utilities for finding and parsing SKILL.md files.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Pattern for valid skill names per Agent Skills Spec
VALID_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class SkillMetadata:
    """Metadata from a SKILL.md file's YAML frontmatter.

    Follows the Agent Skills Specification:
    https://agentskills.io/specification

    Required fields: name, description
    Optional fields: version, license, compatibility, allowed-tools, metadata, hooks
    """

    name: str
    description: str
    path: Path
    source: str  # Which directory/source this came from
    version: str | None = None
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: list[str] | None = None
    metadata: dict[str, Any] | None = None
    hooks: dict[str, Any] | None = None


def parse_skill_frontmatter(skill_path: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter from a SKILL.md file."""
    try:
        content = skill_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to read {skill_path}: {e}")
        return None

    if not content.startswith("---"):
        logger.debug(f"No frontmatter in {skill_path}")
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        logger.debug(f"Incomplete frontmatter in {skill_path}")
        return None

    try:
        frontmatter = yaml.safe_load(parts[1])
        return frontmatter if isinstance(frontmatter, dict) else None
    except yaml.YAMLError as e:
        logger.warning(f"Invalid YAML in {skill_path}: {e}")
        return None


def extract_skill_body(skill_path: Path) -> str | None:
    """Extract the markdown body from a SKILL.md file (without frontmatter)."""
    try:
        content = skill_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to read {skill_path}: {e}")
        return None

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()

    return content.strip()


def discover_skills(skills_dir: Path) -> dict[str, SkillMetadata]:
    """Discover all skills in a directory."""
    skills = {}

    if not skills_dir.exists():
        logger.debug(f"Skills directory does not exist: {skills_dir}")
        return skills

    if not skills_dir.is_dir():
        logger.warning(f"Skills path is not a directory: {skills_dir}")
        return skills

    for skill_file in skills_dir.glob("**/SKILL.md"):
        try:
            frontmatter = parse_skill_frontmatter(skill_file)
            if not frontmatter:
                logger.debug(f"Skipping {skill_file} - no valid frontmatter")
                continue

            name = frontmatter.get("name")
            description = frontmatter.get("description")

            if not name or not description:
                logger.warning(
                    f"Skipping {skill_file} - missing required fields (name, description)"
                )
                continue

            if len(name) > 64:
                logger.warning(
                    f"Skill '{name}' at {skill_file} exceeds 64 character name limit"
                )
            if len(description) > 1024:
                logger.warning(
                    f"Skill '{name}' at {skill_file} exceeds 1024 character description limit"
                )

            if not VALID_NAME_PATTERN.match(name):
                logger.warning(
                    f"Skill '{name}' at {skill_file} has invalid name format"
                )

            parent_dir_name = skill_file.parent.name
            if name != parent_dir_name:
                logger.warning(
                    f"Skill '{name}' at {skill_file} has mismatched directory name '{parent_dir_name}'"
                )

            # Parse allowed-tools
            allowed_tools_raw = frontmatter.get("allowed-tools")
            allowed_tools = None
            if allowed_tools_raw:
                if isinstance(allowed_tools_raw, list):
                    allowed_tools = [str(t) for t in allowed_tools_raw]
                elif isinstance(allowed_tools_raw, str):
                    allowed_tools = [t.strip() for t in allowed_tools_raw.split()]

            compatibility = frontmatter.get("compatibility")

            hooks_config = frontmatter.get("hooks")
            if hooks_config and not isinstance(hooks_config, dict):
                logger.warning(f"Invalid hooks format in {skill_file}: expected dict")
                hooks_config = None

            metadata = SkillMetadata(
                name=name,
                description=description,
                path=skill_file,
                source=str(skills_dir),
                version=frontmatter.get("version"),
                license=frontmatter.get("license"),
                compatibility=compatibility,
                allowed_tools=allowed_tools,
                metadata=frontmatter.get("metadata"),
                hooks=hooks_config,
            )

            skills[name] = metadata
            logger.debug(f"Discovered skill: {name} at {skill_file}")

        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Error processing {skill_file}: {e}")
            continue

    logger.info(f"Discovered {len(skills)} skills in {skills_dir}")
    return skills


def discover_skills_multi_source(
    skills_dirs: list[Path] | list[str],
) -> dict[str, SkillMetadata]:
    """Discover skills from multiple directories with priority.

    First-match-wins: If same skill name appears in multiple directories,
    the one from the earlier directory (higher priority) is used.
    """
    all_skills: dict[str, SkillMetadata] = {}

    for skills_dir in skills_dirs:
        dir_path = Path(skills_dir).expanduser().resolve()

        if not dir_path.exists():
            logger.debug(f"Skills directory does not exist: {dir_path}")
            continue

        dir_skills = discover_skills(dir_path)

        for name, metadata in dir_skills.items():
            if name not in all_skills:
                all_skills[name] = metadata
                logger.debug(f"Added skill '{name}' from {dir_path}")
            else:
                logger.debug(f"Skipping duplicate skill '{name}' from {dir_path}")

    logger.info(f"Discovered {len(all_skills)} skills from {len(skills_dirs)} sources")
    return all_skills


def get_default_skills_dirs() -> list[Path]:
    """Get default skills directory search paths with priority."""
    dirs = []

    if env_dir := os.getenv("AMPLIFIER_SKILLS_DIR"):
        dirs.append(Path(env_dir))

    dirs.append(Path(".amplifier/skills"))
    dirs.append(Path("~/.amplifier/skills").expanduser())

    return dirs
