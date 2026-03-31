"""Content module for session-service — assembles system prompts from workspace content."""

from __future__ import annotations

_DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


def assemble_system_prompt(
    routing_table: dict,
    workspace_content: dict[str, str],
    dapr_url: str,
) -> str:
    """Assemble a system prompt from workspace content.

    Iterates workspace_content dict, formats each entry as a context_file XML block.
    Returns all blocks joined together, or _DEFAULT_SYSTEM_PROMPT if workspace is empty.

    Args:
        routing_table: The service routing table (reserved for Phase 3 service content).
        workspace_content: Mapping of file paths to their content.
        dapr_url: Dapr sidecar URL (reserved for Phase 3 service content fetching).

    Returns:
        A system prompt string with workspace content as context_file blocks,
        or _DEFAULT_SYSTEM_PROMPT if no workspace content is provided.

    TODO (Phase 3): Fetch additional service content via GET /content/{path}
        for each service in routing_table.
    """
    if not workspace_content:
        return _DEFAULT_SYSTEM_PROMPT

    parts: list[str] = []
    for path, content in workspace_content.items():
        parts.append(f'<context_file path="{path}">\n{content}\n</context_file>')

    return "\n\n".join(parts)
