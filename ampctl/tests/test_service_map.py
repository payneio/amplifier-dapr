"""Tests for service map building, loading, and saving."""

from pathlib import Path

from ampctl.hasher import generate_service_name
from ampctl.models import AgentDefinition, ServiceEntry, ServiceMap, ServiceMapEntry
from ampctl.service_map import (
    build_service_map_entry,
    load_service_map,
    save_service_map,
)


def _minimal_agent() -> AgentDefinition:
    return AgentDefinition(
        ref="example/my-agent",
        orchestrator=ServiceEntry(image="ghcr.io/example/orchestrator:latest"),
        context_manager=ServiceEntry(image="ghcr.io/example/context-manager:latest"),
        providers=ServiceEntry(image="ghcr.io/example/providers:latest"),
    )


def test_build_service_map_entry() -> None:
    """build_service_map_entry produces correct prefixed app-ids for all roles."""
    agent = _minimal_agent()
    entry = build_service_map_entry(agent)

    assert isinstance(entry, ServiceMapEntry)
    assert entry.orchestrator == generate_service_name(
        "orchestrator", agent.orchestrator.source_key
    )
    assert entry.context_manager == generate_service_name(
        "context_manager", agent.context_manager.source_key
    )
    assert entry.providers == generate_service_name(
        "providers", agent.providers.source_key
    )
    assert entry.behaviors == {}


def test_build_service_map_entry_with_behaviors() -> None:
    """Behaviors are included in the map entry with correct app-ids."""
    agent = AgentDefinition(
        ref="example/agent-with-behaviors",
        orchestrator=ServiceEntry(image="ghcr.io/example/orchestrator:latest"),
        context_manager=ServiceEntry(image="ghcr.io/example/ctx:latest"),
        providers=ServiceEntry(image="ghcr.io/example/prov:latest"),
        behaviors={
            "web-search": ServiceEntry(image="ghcr.io/example/web-search:latest"),
        },
    )
    entry = build_service_map_entry(agent)

    assert "web-search" in entry.behaviors
    assert entry.behaviors["web-search"] == generate_service_name(
        "web-search", agent.behaviors["web-search"].source_key
    )


def test_load_empty_service_map(tmp_path: Path) -> None:
    """Loading from a nonexistent path returns an empty ServiceMap."""
    missing = tmp_path / "nonexistent" / "service_map.yaml"
    result = load_service_map(missing)
    assert isinstance(result, ServiceMap)
    assert result.agents == {}


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """Saving and then loading a ServiceMap preserves all data."""
    sm = ServiceMap(
        agents={
            "my-agent": ServiceMapEntry(
                orchestrator="svc-orchestrator-abc12345",
                context_manager="svc-context_manager-def67890",
                providers="svc-providers-fed09876",
                behaviors={"machine": "svc-machine-11223344"},
            )
        }
    )
    path = tmp_path / "service_map.yaml"
    save_service_map(sm, path)

    loaded = load_service_map(path)
    assert loaded.agents["my-agent"].orchestrator == "svc-orchestrator-abc12345"
    assert loaded.agents["my-agent"].context_manager == "svc-context_manager-def67890"
    assert loaded.agents["my-agent"].providers == "svc-providers-fed09876"
    assert loaded.agents["my-agent"].behaviors["machine"] == "svc-machine-11223344"


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    """save_service_map creates intermediate directories if they don't exist."""
    sm = ServiceMap()
    path = tmp_path / "deep" / "nested" / "service_map.yaml"
    save_service_map(sm, path)
    assert path.exists()
