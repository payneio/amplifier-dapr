"""SkillsVisibilityHook — injects available skills into provider:request context."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from amplifier_service_sdk.models import HookResult

if TYPE_CHECKING:
    from svc_skills.tool import SkillsTool


class SkillsVisibilityHook:
    """Pre-hook that injects available skill names into provider:request context."""

    name: str = "skills_visibility"
    events: list[str] = ["provider:request"]
    priority: int = 20
    mode: Literal["sync", "async"] = "sync"

    def __init__(self, skills_tool: SkillsTool) -> None:
        self.skills_tool = skills_tool

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle a hook event.

        For provider:request events: inject available skill names into context.
        For all other events: return CONTINUE.
        """
        if event != "provider:request":
            return HookResult(action="CONTINUE")

        skills = self.skills_tool.skills
        if not skills:
            return HookResult(action="CONTINUE")

        lines = ["Available skills (use load_skill tool):"]
        for name in sorted(skills.keys()):
            metadata = skills[name]
            description = getattr(metadata, "description", str(metadata))
            lines.append(f"\n- **{name}**: {description}")

        body = "\n".join(lines)
        content = (
            f'<system-reminder source="hooks-skills-visibility">\n'
            f"{body}\n"
            f"</system-reminder>"
        )

        return HookResult(
            action="INJECT_CONTEXT",
            data={"content": content, "ephemeral": True},
        )
