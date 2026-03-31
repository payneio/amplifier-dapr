"""FastAPI app factory for svc-skills — the skills tool service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_skills.tool import SkillsTool


def create_skills_app() -> FastAPI:
    """Create the svc-skills FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    skills-specific /tools/load_skill/execute endpoint.

    Returns:
        Configured FastAPI application.
    """
    skills_tool = SkillsTool()

    config = ServiceConfig(
        name="svc-skills",
        tools=[
            ToolCapability(
                name=skills_tool.name,
                description=skills_tool.description,
                input_schema=skills_tool.input_schema,
            ),
        ],
    )
    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/load_skill/execute")
    async def execute_load_skill(request: ToolRequest) -> dict[str, Any]:
        """Load domain knowledge from a skill."""
        result = await skills_tool.execute(request.input)
        return result.model_dump()

    return fastapi_app


app = create_skills_app()
