"""Tests for the agent definition YAML files in agents/.

These tests verify that agents/foundation.yaml and agents/default.yaml
exist, parse correctly, and contain the expected structure.
"""

from __future__ import annotations

from pathlib import Path

from ampctl.models import AgentDefinition
from ampctl.parser import fetch_definition

# Resolve path to agents/ directory (two levels up from ampctl/tests/)
AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"
FOUNDATION_YAML = AGENTS_DIR / "foundation.yaml"
DEFAULT_YAML = AGENTS_DIR / "default.yaml"


# ---------------------------------------------------------------------------
# foundation.yaml
# ---------------------------------------------------------------------------


def test_foundation_yaml_exists() -> None:
    assert FOUNDATION_YAML.exists(), f"Missing file: {FOUNDATION_YAML}"


def test_foundation_parses_as_agent_definition() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    assert isinstance(d, AgentDefinition)


def test_foundation_ref() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    assert d.ref == "foundation"


def test_foundation_has_instruction() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    assert d.instruction is not None
    assert len(d.instruction) > 0


def test_foundation_orchestrator_uses_svc_orchestrator() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    assert "svc-orchestrator" in d.orchestrator.source_key


def test_foundation_context_manager_uses_svc_context() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    assert "svc-context" in d.context_manager.source_key


def test_foundation_providers_uses_svc_providers() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    assert "svc-providers" in d.providers.source_key


def test_foundation_providers_has_api_key_env_vars() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    assert d.providers.environment is not None
    assert "ANTHROPIC_API_KEY" in d.providers.environment


def test_foundation_machine_behavior_has_workspace_volume() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    assert "machine" in d.behaviors, "Expected 'machine' behavior"
    machine = d.behaviors["machine"]
    assert machine.volumes is not None
    assert any("/workspace" in v for v in machine.volumes)


def test_foundation_has_expected_tool_behaviors() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    expected = {
        "bash",
        "filesystem",
        "search",
        "web",
        "skills",
        "todo",
        "modes",
        "delegation",
    }
    missing = expected - set(d.behaviors.keys())
    assert not missing, f"Missing behaviors: {missing}"


def test_foundation_has_expected_hook_behaviors() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    expected = {"hooks-approval", "hooks-routing", "hooks-async", "hooks-shell"}
    missing = expected - set(d.behaviors.keys())
    assert not missing, f"Missing hook behaviors: {missing}"


def test_foundation_has_expected_content_behaviors() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    expected = {
        "content-core",
        "content-amplifier",
        "content-browser-tester",
        "content-design-intelligence",
        "content-filesystem",
        "content-recipes",
        "content-superpowers",
        "content-system-design-intelligence",
    }
    missing = expected - set(d.behaviors.keys())
    assert not missing, f"Missing content behaviors: {missing}"


def test_foundation_behavior_build_paths_reference_services() -> None:
    d = fetch_definition(str(FOUNDATION_YAML))
    for name, entry in d.behaviors.items():
        assert entry.build is not None or entry.image is not None, (
            f"Behavior '{name}' has no build or image"
        )


# ---------------------------------------------------------------------------
# default.yaml
# ---------------------------------------------------------------------------


def test_default_yaml_exists() -> None:
    assert DEFAULT_YAML.exists(), f"Missing file: {DEFAULT_YAML}"


def test_default_parses_as_agent_definition() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    assert isinstance(d, AgentDefinition)


def test_default_ref() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    assert d.ref == "default"


def test_default_providers_uses_mock_provider() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    assert "svc-mock-provider" in d.providers.source_key


def test_default_orchestrator_uses_svc_orchestrator() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    assert "svc-orchestrator" in d.orchestrator.source_key


def test_default_context_manager_uses_svc_context() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    assert "svc-context" in d.context_manager.source_key


def test_default_machine_behavior_has_workspace_volume() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    assert "machine" in d.behaviors, "Expected 'machine' behavior"
    machine = d.behaviors["machine"]
    assert machine.volumes is not None
    assert any("/workspace" in v for v in machine.volumes)


def test_default_has_expected_tool_behaviors() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    expected = {
        "bash",
        "filesystem",
        "search",
        "web",
        "skills",
        "todo",
        "modes",
        "delegation",
    }
    missing = expected - set(d.behaviors.keys())
    assert not missing, f"Missing behaviors: {missing}"


def test_default_has_expected_hook_behaviors() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    expected = {"hooks-approval", "hooks-routing", "hooks-async", "hooks-shell"}
    missing = expected - set(d.behaviors.keys())
    assert not missing, f"Missing hook behaviors: {missing}"


def test_default_has_expected_content_behaviors() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    expected = {
        "content-core",
        "content-amplifier",
        "content-browser-tester",
        "content-design-intelligence",
        "content-filesystem",
        "content-recipes",
        "content-superpowers",
        "content-system-design-intelligence",
    }
    missing = expected - set(d.behaviors.keys())
    assert not missing, f"Missing content behaviors: {missing}"


def test_default_all_service_entries_have_source() -> None:
    d = fetch_definition(str(DEFAULT_YAML))
    for role, entry in d.all_service_entries():
        assert entry.source_key, f"Role '{role}' has empty source_key"
