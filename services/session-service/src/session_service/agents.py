"""Agent registry for session-service — maps agent names to service lists and behaviour config."""

from __future__ import annotations

#: Registry of all known agents.
#: Each entry maps an agent name to a config dict with:
#:   services       — ordered list of Dapr app-ids to discover for this agent
#:   default_provider — provider to use when the caller hasn't chosen one
#:   system_prompt  — optional preamble prepended before workspace/tool content
AGENTS: dict[str, dict] = {
    "default": {
        "services": [
            "svc-bash",
            "svc-filesystem",
            "svc-search",
            "svc-web",
            "svc-skills",
            "svc-todo",
            "svc-modes",
            "svc-providers",
            "svc-mock-provider",
            "svc-context",
            "svc-orchestrator",
            "svc-delegation",
            "svc-hooks-approval",
            "svc-hooks-routing",
            "svc-hooks-async",
            "svc-hooks-shell",
            "svc-content-core",
            "svc-content-amplifier",
            "svc-content-browser-tester",
            "svc-content-design-intelligence",
            "svc-content-filesystem",
            "svc-content-recipes",
            "svc-content-superpowers",
            "svc-content-system-design-intelligence",
        ],
        "default_provider": "mock",
    },
    "foundation": {
        "services": [
            "svc-bash",
            "svc-filesystem",
            "svc-search",
            "svc-web",
            "svc-skills",
            "svc-todo",
            "svc-modes",
            "svc-providers",
            "svc-context",
            "svc-orchestrator",
            "svc-delegation",
            "svc-hooks-approval",
            "svc-hooks-routing",
            "svc-hooks-async",
            "svc-hooks-shell",
            "svc-content-core",
            "svc-content-amplifier",
            "svc-content-browser-tester",
            "svc-content-design-intelligence",
            "svc-content-filesystem",
            "svc-content-recipes",
            "svc-content-superpowers",
            "svc-content-system-design-intelligence",
        ],
        "default_provider": "anthropic",
        "system_prompt": (
            "You are Amplifier, an AI-powered CLI tool that helps users accomplish tasks. "
            "You have access to tools for file operations, web search, code execution, and more. "
            "Focus on being helpful, accurate, and efficient."
        ),
    },
}


def resolve_agent(agent_ref: str) -> dict:
    """Resolve an agent reference to its configuration dict.

    Args:
        agent_ref: The agent name (e.g. ``"foundation"``).

    Returns:
        The matching agent config dict.  Falls back to the ``"default"`` agent
        when *agent_ref* is not found in the registry.

    Examples:
        >>> cfg = resolve_agent("foundation")
        >>> cfg["default_provider"]
        'anthropic'

        >>> cfg = resolve_agent("nonexistent")
        >>> cfg == AGENTS["default"]
        True
    """
    return AGENTS.get(agent_ref, AGENTS["default"])
