"""Tests for ampctl Pydantic models."""

import pytest
from pydantic import ValidationError

from ampctl.models import (
    AgentDefinition,
    AgentDefinitionFile,
    ServiceEntry,
    ServiceMap,
    ServiceMapEntry,
)


# ---------------------------------------------------------------------------
# ServiceEntry
# ---------------------------------------------------------------------------


def test_service_entry_with_image() -> None:
    entry = ServiceEntry(image="ghcr.io/example/orchestrator:latest")
    assert entry.image == "ghcr.io/example/orchestrator:latest"
    assert entry.build is None
    assert entry.source_key == "ghcr.io/example/orchestrator:latest"


def test_service_entry_with_build() -> None:
    entry = ServiceEntry(build="./services/my-service")
    assert entry.build == "./services/my-service"
    assert entry.image is None
    assert entry.source_key == "./services/my-service"


def test_service_entry_with_build_dict() -> None:
    entry = ServiceEntry(
        build={"context": "./services/my-service", "dockerfile": "Dockerfile"}
    )
    assert isinstance(entry.build, dict)
    assert entry.build["context"] == "./services/my-service"
    # source_key returns the context path for dict builds
    assert entry.source_key == "./services/my-service"


def test_service_entry_requires_image_or_build() -> None:
    with pytest.raises(ValidationError):
        ServiceEntry()


def test_service_entry_with_config() -> None:
    entry = ServiceEntry(image="example:latest", config={"model": "gpt-4"})
    assert entry.config == {"model": "gpt-4"}


def test_service_entry_with_environment() -> None:
    entry = ServiceEntry(image="example:latest", environment={"API_KEY": "secret"})
    assert entry.environment == {"API_KEY": "secret"}


def test_service_entry_with_volumes() -> None:
    entry = ServiceEntry(image="example:latest", volumes=["./data:/data"])
    assert entry.volumes == ["./data:/data"]


# ---------------------------------------------------------------------------
# AgentDefinition
# ---------------------------------------------------------------------------


def test_minimal_agent_definition() -> None:
    agent = AgentDefinition(
        ref="example/my-agent",
        orchestrator=ServiceEntry(image="example/orchestrator:latest"),
        context_manager=ServiceEntry(image="example/context-manager:latest"),
        providers=ServiceEntry(image="example/providers:latest"),
    )
    assert agent.ref == "example/my-agent"
    assert agent.description is None
    assert agent.instruction is None
    assert agent.behaviors == {}


def test_full_agent_definition() -> None:
    agent = AgentDefinition(
        ref="example/full-agent",
        description="A full-featured agent",
        instruction="You are a helpful assistant.",
        orchestrator=ServiceEntry(image="example/orchestrator:latest"),
        context_manager=ServiceEntry(image="example/context-manager:latest"),
        providers=ServiceEntry(image="example/providers:latest"),
        behaviors={
            "web-search": ServiceEntry(
                image="example/web-search:latest",
                config={"max_results": 10},
            )
        },
    )
    assert agent.description == "A full-featured agent"
    assert agent.instruction == "You are a helpful assistant."
    assert "web-search" in agent.behaviors
    assert agent.behaviors["web-search"].config == {"max_results": 10}


def test_all_service_entries_from_definition() -> None:
    agent = AgentDefinition(
        ref="example/agent",
        orchestrator=ServiceEntry(image="example/orchestrator:latest"),
        context_manager=ServiceEntry(image="example/context-manager:latest"),
        providers=ServiceEntry(image="example/providers:latest"),
        behaviors={
            "search": ServiceEntry(image="example/search:latest"),
            "tools": ServiceEntry(image="example/tools:latest"),
        },
    )
    entries = list(agent.all_service_entries())
    roles = [role for role, _ in entries]
    assert len(entries) == 5
    assert "orchestrator" in roles
    assert "context_manager" in roles
    assert "providers" in roles
    assert "search" in roles
    assert "tools" in roles


def test_all_service_entries_no_behaviors() -> None:
    agent = AgentDefinition(
        ref="example/agent",
        orchestrator=ServiceEntry(image="example/orchestrator:latest"),
        context_manager=ServiceEntry(image="example/context-manager:latest"),
        providers=ServiceEntry(image="example/providers:latest"),
    )
    entries = list(agent.all_service_entries())
    assert len(entries) == 3


# ---------------------------------------------------------------------------
# AgentDefinitionFile
# ---------------------------------------------------------------------------


def test_agent_definition_file_wrapper() -> None:
    adf = AgentDefinitionFile(
        agent=AgentDefinition(
            ref="example/agent",
            orchestrator=ServiceEntry(image="example/orchestrator:latest"),
            context_manager=ServiceEntry(image="example/context-manager:latest"),
            providers=ServiceEntry(image="example/providers:latest"),
        )
    )
    assert adf.agent.ref == "example/agent"


# ---------------------------------------------------------------------------
# ServiceMapEntry
# ---------------------------------------------------------------------------


def test_service_map_entry_all_app_ids() -> None:
    entry = ServiceMapEntry(
        orchestrator="example-orchestrator",
        context_manager="example-context-manager",
        providers="example-providers",
        behaviors={
            "search": "example-search",
            "tools": "example-tools",
        },
    )
    ids = entry.all_app_ids()
    assert len(ids) == 5
    assert "example-orchestrator" in ids
    assert "example-context-manager" in ids
    assert "example-providers" in ids
    assert "example-search" in ids
    assert "example-tools" in ids


def test_service_map_entry_no_behaviors() -> None:
    entry = ServiceMapEntry(
        orchestrator="orch",
        context_manager="ctx",
        providers="prov",
    )
    ids = entry.all_app_ids()
    assert ids == ["orch", "ctx", "prov"]


# ---------------------------------------------------------------------------
# ServiceMap
# ---------------------------------------------------------------------------


def test_service_map_round_trip() -> None:
    original = ServiceMap(
        agents={
            "my-agent": ServiceMapEntry(
                orchestrator="my-orchestrator",
                context_manager="my-context-manager",
                providers="my-providers",
            )
        }
    )
    data = original.model_dump()
    restored = ServiceMap.model_validate(data)
    assert restored.agents["my-agent"].orchestrator == "my-orchestrator"


def test_service_map_empty() -> None:
    sm = ServiceMap()
    assert sm.agents == {}
