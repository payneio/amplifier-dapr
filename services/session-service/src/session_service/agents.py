"""Agent registry for session-service — maps agent names to service lists and behaviour config."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

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


def _load_from_yaml(agent_ref: str) -> dict | None:
    """Try to load agent config from YAML files.

    Reads ``{AMPLIFIER_AGENTS_DIR}/{agent_ref}.yaml`` and
    ``AMPLIFIER_SERVICE_MAP`` (or their ``~/.amplifier/`` defaults).

    Returns a config dict if both files exist and contain the expected data,
    otherwise returns ``None`` to signal the caller should fall back to the
    hardcoded :data:`AGENTS` registry.
    """
    agents_dir = Path(
        os.environ.get(
            "AMPLIFIER_AGENTS_DIR", str(Path.home() / ".amplifier" / "agents")
        )
    )
    agent_yaml_path = agents_dir / f"{agent_ref}.yaml"

    if not agent_yaml_path.exists():
        return None

    service_map_path = Path(
        os.environ.get(
            "AMPLIFIER_SERVICE_MAP",
            str(Path.home() / ".amplifier" / "service-map.yaml"),
        )
    )

    if not service_map_path.exists():
        return None

    with open(agent_yaml_path) as fh:
        agent_data = yaml.safe_load(fh)
    with open(service_map_path) as fh:
        service_map_data = yaml.safe_load(fh)

    agent = agent_data.get("agent", {})
    instruction: str = agent.get("instruction", "") or ""

    agents_map = service_map_data.get("agents", {}) or {}
    entry: dict = agents_map.get(agent_ref, {}) or {}

    if not entry:
        return None

    # Collect all app-ids from the service-map entry.
    services: list[str] = []
    for key in ("orchestrator", "context_manager", "providers"):
        app_id = entry.get(key)
        if app_id:
            services.append(app_id)
    for app_id in (entry.get("behaviors") or {}).values():
        services.append(app_id)

    # Normalise: ensure system_prompt ends with a newline.
    system_prompt = instruction if instruction.endswith("\n") else instruction + "\n"

    return {
        "services": services,
        "default_provider": "anthropic",
        "system_prompt": system_prompt,
        "orchestrator_app_id": entry.get("orchestrator", ""),
        "context_app_id": entry.get("context_manager", ""),
    }


def get_agent_config(agent_ref: str) -> dict:
    """Return agent configuration, preferring YAML-based definitions.

    Resolution order:

    1. If ``{AMPLIFIER_AGENTS_DIR}/{agent_ref}.yaml`` and
       ``AMPLIFIER_SERVICE_MAP`` (or their ``~/.amplifier/`` defaults) both
       exist and contain the expected structure, build the config from them.
    2. Otherwise fall back to the hardcoded :data:`AGENTS` registry (same
       behaviour as :func:`resolve_agent`).

    Args:
        agent_ref: The agent name (e.g. ``"foundation"``).

    Returns:
        A config dict guaranteed to contain at minimum ``services`` and
        ``default_provider``.  YAML-resolved configs also include
        ``orchestrator_app_id`` and ``context_app_id``.
    """
    result = _load_from_yaml(agent_ref)
    if result is not None:
        return result
    return AGENTS.get(agent_ref, AGENTS["default"])
