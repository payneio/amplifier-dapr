"""Content module for session-service — assembles system prompts from workspace content."""

from __future__ import annotations

import logging

import httpx


logger = logging.getLogger(__name__)


async def assemble_system_prompt(
    routing_table: dict,
    workspace_content: str | None = None,
    agent_system_prompt: str | None = None,
    dapr_url: str = "http://localhost:3500",
) -> str:
    """Assemble a system prompt from service content and workspace content.

    Fetches content from registered content services via the Dapr sidecar,
    wraps each response in a ``<context_file>`` XML block, and combines with
    the agent system prompt and workspace content.

    Args:
        routing_table: The service routing table; reads ``_content_services``
            (dict of app_id -> list of content paths) populated by discovery.
        workspace_content: Pre-formatted workspace content string (optional).
        agent_system_prompt: Agent-specific system prompt to prepend (optional).
        dapr_url: Base URL of the Dapr HTTP sidecar.

    Returns:
        Combined system prompt string, or ``"You are a helpful assistant."`` as
        a fallback when no content is available.
    """
    parts: list[str] = []

    # Agent-specific system prompt
    if agent_system_prompt:
        parts.append(agent_system_prompt)

    # Fetch content from content services via Dapr sidecar
    content_services: dict[str, list[str]] = routing_table.get("_content_services", {})
    if content_services:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for app_id, paths in content_services.items():
                for path in paths:
                    try:
                        url = f"{dapr_url}/v1.0/invoke/{app_id}/method/content/{path}"
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            data = resp.json()
                            content = (
                                data.get("content", "")
                                if isinstance(data, dict)
                                else str(data)
                            )
                            if content:
                                parts.append(
                                    f'<context_file path="{app_id}:{path}">\n{content}\n</context_file>'
                                )
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "Failed to fetch content %r from service %r", path, app_id
                        )

    # Workspace content from CLI (already formatted as context_file blocks)
    if workspace_content:
        parts.append(workspace_content)

    # Fallback
    if not parts:
        return "You are a helpful assistant."

    return "\n\n".join(parts)
