"""Service map building, loading, and saving utilities."""

from pathlib import Path

import yaml

from ampctl.hasher import generate_service_name
from ampctl.models import AgentDefinition, ServiceMap, ServiceMapEntry


def build_service_map_entry(agent: AgentDefinition) -> ServiceMapEntry:
    """Hash all services in *agent* and return the corresponding ServiceMapEntry."""
    behaviors: dict[str, str] = {}
    orchestrator_id = ""
    context_manager_id = ""
    providers_id = ""

    for role_key, entry in agent.all_service_entries():
        app_id = generate_service_name(role_key, entry.source_key)
        if role_key == "orchestrator":
            orchestrator_id = app_id
        elif role_key == "context_manager":
            context_manager_id = app_id
        elif role_key == "providers":
            providers_id = app_id
        else:
            behaviors[role_key] = app_id

    return ServiceMapEntry(
        orchestrator=orchestrator_id,
        context_manager=context_manager_id,
        providers=providers_id,
        behaviors=behaviors,
    )


def load_service_map(path: Path) -> ServiceMap:
    """Load a ServiceMap from *path*. Returns an empty ServiceMap if the file is missing."""
    if not path.exists():
        return ServiceMap()
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    return ServiceMap.model_validate(data)


def save_service_map(sm: ServiceMap, path: Path) -> None:
    """Serialise *sm* to YAML at *path*, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        yaml.safe_dump(sm.model_dump(), fh, default_flow_style=False)
