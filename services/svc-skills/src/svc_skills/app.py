"""FastAPI app factory for svc-skills — the skills tool service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import (
    HookEvent,
    HookRegistration,
    ToolCapability,
    ToolRequest,
)
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_skills.tool import SkillsTool
from svc_skills.visibility_hook import SkillsVisibilityHook


def create_skills_app() -> FastAPI:
    """Create the svc-skills FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    skills-specific /tools/load_skill/execute endpoint plus the
    /hooks/skills_visibility/invoke endpoint.

    Returns:
        Configured FastAPI application.
    """
    skills_tool = SkillsTool()
    visibility_hook = SkillsVisibilityHook(skills_tool=skills_tool)

    config = ServiceConfig(
        name="svc-skills",
        tools=[
            ToolCapability(
                name=skills_tool.name,
                description=skills_tool.description,
                input_schema=skills_tool.input_schema,
            ),
        ],
        hooks=[
            HookRegistration(
                name=SkillsVisibilityHook.name,
                events=SkillsVisibilityHook.events,
                priority=SkillsVisibilityHook.priority,
                mode=SkillsVisibilityHook.mode,
            ),
        ],
    )
    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/load_skill/execute")
    async def execute_load_skill(request: ToolRequest) -> dict[str, Any]:
        """Load domain knowledge from a skill."""
        result = await skills_tool.execute(request.input)
        return result.model_dump()

    @fastapi_app.post("/hooks/skills_visibility/invoke")
    async def invoke_skills_visibility(event: HookEvent) -> dict[str, Any]:
        """Invoke the skills visibility hook."""
        result = await visibility_hook.handle(event.event, event.data)
        return result.model_dump()

    @fastapi_app.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return fastapi_app


app = create_skills_app()
