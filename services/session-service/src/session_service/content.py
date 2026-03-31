"""Content module for session-service — assembles system prompts from workspace content."""

from __future__ import annotations


def assemble_system_prompt(
    workspace_content: dict[str, str],
    agent_ref: str = "default",
) -> str:
    """Assemble a system prompt from workspace content.

    Args:
        workspace_content: Mapping of file paths to their content.
        agent_ref: The agent reference identifier.

    Returns:
        A system prompt string with workspace content as context_file blocks,
        or a default prompt if no workspace content is provided.
    """
    if not workspace_content:
        return "You are a helpful AI assistant."

    blocks: list[str] = []
    for path, content in workspace_content.items():
        blocks.append(f'<context_file path="{path}">\n{content}\n</context_file>')

    return "\n\n".join(blocks)
