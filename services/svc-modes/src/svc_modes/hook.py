"""ModeHooks, ModeDefinition, HookResult, and parse_mode_file for svc-modes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ModeDefinition:
    """Parsed mode definition from a mode file."""

    name: str
    description: str = ""
    source: str = ""
    shortcut: str | None = None
    context: str = ""  # Markdown body — injected when mode is active
    safe_tools: list[str] = field(default_factory=list)
    warn_tools: list[str] = field(default_factory=list)
    confirm_tools: list[str] = field(default_factory=list)
    block_tools: list[str] = field(default_factory=list)
    default_action: str = "allow"  # "block" or "allow"
    allowed_transitions: list[str] | None = None
    allow_clear: bool = True


@dataclass
class HookResult:
    """Result returned by a hook handler."""

    action: str = "CONTINUE"
    reason: str | None = None
    context_injection: str | None = None
    context_injection_role: str | None = None
    ephemeral: bool | None = None


class ModeHooks:
    """In-process mode management: tracks active mode and enforces tool policy."""

    name = "mode_hooks"

    def __init__(self) -> None:
        self._active_mode: ModeDefinition | None = None

    # ── State management ─────────────────────────────────────────────────────

    def set_active_mode(self, mode: ModeDefinition) -> None:
        """Activate a mode."""
        self._active_mode = mode

    def get_active_mode(self) -> ModeDefinition | None:
        """Return the currently active mode, or None."""
        return self._active_mode

    def clear_active_mode(self) -> None:
        """Deactivate any active mode."""
        self._active_mode = None

    # ── Hook handler ──────────────────────────────────────────────────────────

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Enforce tool policy based on active mode.

        Returns CONTINUE if no mode active, tool is safe, or tool is unlisted.
        Returns DENY if tool is in block_tools.
        """
        mode = self._active_mode
        if not mode:
            return HookResult(action="CONTINUE")

        tool_name = data.get("tool_name", "")

        if tool_name in mode.safe_tools:
            return HookResult(action="CONTINUE")

        if tool_name in mode.block_tools:
            reason = f"Mode '{mode.name}': '{tool_name}' is blocked. {mode.description}"
            return HookResult(action="DENY", reason=reason)

        # Unlisted tools: CONTINUE by default
        return HookResult(action="CONTINUE")


# ── Mode file parsing ─────────────────────────────────────────────────────────


def parse_mode_file(file_path: Path) -> ModeDefinition | None:
    """Parse a mode definition from a markdown file with YAML frontmatter.

    Expected format::

        ---
        mode:
          name: plan
          description: Think and discuss
          tools:
            safe: [read_file, grep]
            block: [bash]
          default_action: allow
        ---

        # Mode Context

        Markdown content injected when mode is active...
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read mode file %s: %s", file_path, e)
        return None

    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not frontmatter_match:
        logger.warning("Mode file %s missing YAML frontmatter", file_path)
        return None

    yaml_content = frontmatter_match.group(1)
    markdown_body = frontmatter_match.group(2).strip()

    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        logger.warning("Invalid YAML in mode file %s: %s", file_path, e)
        return None

    if not parsed or "mode" not in parsed:
        logger.warning("Mode file %s missing 'mode:' section", file_path)
        return None

    mode_config = parsed["mode"]
    tools_config = mode_config.get("tools", {})

    return ModeDefinition(
        name=mode_config.get("name", file_path.stem),
        description=mode_config.get("description", ""),
        shortcut=mode_config.get("shortcut"),
        context=markdown_body,
        safe_tools=tools_config.get("safe", []),
        warn_tools=tools_config.get("warn", []),
        confirm_tools=tools_config.get("confirm", []),
        block_tools=tools_config.get("block", []),
        default_action=mode_config.get("default_action", "allow"),
        allowed_transitions=mode_config.get("allowed_transitions"),
        allow_clear=mode_config.get("allow_clear", True),
    )


__all__ = [
    "ModeDefinition",
    "ModeHooks",
    "HookResult",
    "parse_mode_file",
]
