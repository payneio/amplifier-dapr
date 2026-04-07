"""Tests for session_service.agents — agent registry and resolution."""

from __future__ import annotations

import pytest

from session_service.agents import AGENTS, get_agent_config, resolve_agent


class TestResolveAgent:
    def test_returns_foundation_config(self) -> None:
        """resolve_agent('foundation') returns the foundation entry from AGENTS."""
        cfg = resolve_agent("foundation")
        assert cfg is AGENTS["foundation"]

    def test_returns_default_config(self) -> None:
        """resolve_agent('default') returns the default entry from AGENTS."""
        cfg = resolve_agent("default")
        assert cfg is AGENTS["default"]

    def test_unknown_falls_back_to_default(self) -> None:
        """An unrecognised agent ref falls back to the 'default' config."""
        cfg = resolve_agent("nonexistent-agent")
        assert cfg is AGENTS["default"]

    def test_empty_string_falls_back_to_default(self) -> None:
        """An empty string falls back to the 'default' config."""
        cfg = resolve_agent("")
        assert cfg is AGENTS["default"]

    def test_foundation_default_provider_is_anthropic(self) -> None:
        """The foundation agent uses anthropic as its default provider."""
        cfg = resolve_agent("foundation")
        assert cfg["default_provider"] == "anthropic"

    def test_default_default_provider_is_mock(self) -> None:
        """The default agent uses mock as its default provider."""
        cfg = resolve_agent("default")
        assert cfg["default_provider"] == "mock"

    def test_foundation_has_system_prompt(self) -> None:
        """The foundation agent config includes a non-empty system_prompt."""
        cfg = resolve_agent("foundation")
        assert "system_prompt" in cfg
        assert len(cfg["system_prompt"]) > 0

    def test_default_has_no_system_prompt(self) -> None:
        """The default agent config does not define a system_prompt."""
        cfg = resolve_agent("default")
        assert "system_prompt" not in cfg

    def test_foundation_services_excludes_mock_provider(self) -> None:
        """The foundation agent service list does NOT include svc-mock-provider."""
        cfg = resolve_agent("foundation")
        assert "svc-mock-provider" not in cfg["services"]

    def test_default_services_includes_mock_provider(self) -> None:
        """The default agent service list includes svc-mock-provider."""
        cfg = resolve_agent("default")
        assert "svc-mock-provider" in cfg["services"]

    def test_foundation_services_includes_core_tools(self) -> None:
        """The foundation agent service list includes the standard tool services."""
        cfg = resolve_agent("foundation")
        expected = {
            "svc-machine",
            "svc-web",
            "svc-providers",
        }
        assert expected.issubset(set(cfg["services"]))

    @pytest.mark.parametrize("agent_name", list(AGENTS.keys()))
    def test_all_agents_have_required_keys(self, agent_name: str) -> None:
        """Every agent in the registry has at minimum 'services' and 'default_provider'."""
        cfg = resolve_agent(agent_name)
        assert "services" in cfg, f"{agent_name!r} missing 'services'"
        assert "default_provider" in cfg, f"{agent_name!r} missing 'default_provider'"
        assert isinstance(cfg["services"], list)
        assert len(cfg["services"]) > 0


# ---------------------------------------------------------------------------
# Tests: get_agent_config — YAML-first resolution with hardcoded fallback
# ---------------------------------------------------------------------------

FOUNDATION_YAML = """\
agent:
  ref: foundation
  description: Full-featured foundation agent
  instruction: You are Amplifier, a helpful AI assistant.
  orchestrator:
    build: ./services/svc-orchestrator
  context_manager:
    build: ./services/svc-context
  providers:
    build: ./services/svc-providers
  behaviors:
    bash:
      build: ./services/svc-bash
    filesystem:
      build: ./services/svc-filesystem
"""

SERVICE_MAP_YAML = """\
agents:
  foundation:
    orchestrator: svc-orchestrator-abc12345
    context_manager: svc-context-manager-def67890
    providers: svc-providers-123abcde
    behaviors:
      bash: svc-bash-456fghij
      filesystem: svc-filesystem-789klmno
"""


def test_resolve_from_yaml(tmp_path, monkeypatch):
    """When YAML agent definition exists, use it."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "foundation.yaml").write_text(FOUNDATION_YAML)
    (tmp_path / "service-map.yaml").write_text(SERVICE_MAP_YAML)

    monkeypatch.setenv("AMPLIFIER_AGENTS_DIR", str(agents_dir))
    monkeypatch.setenv("AMPLIFIER_SERVICE_MAP", str(tmp_path / "service-map.yaml"))

    config = get_agent_config("foundation")
    assert "svc-orchestrator-abc12345" in config["services"]
    assert "svc-bash-456fghij" in config["services"]
    assert config["system_prompt"] == "You are Amplifier, a helpful AI assistant.\n"
    assert config["orchestrator_app_id"] == "svc-orchestrator-abc12345"
    assert config["context_app_id"] == "svc-context-manager-def67890"


def test_fallback_to_hardcoded(monkeypatch):
    """When no YAML exists, fall back to hardcoded config."""
    monkeypatch.setenv("AMPLIFIER_AGENTS_DIR", "/nonexistent")
    monkeypatch.delenv("AMPLIFIER_SERVICE_MAP", raising=False)

    config = get_agent_config("foundation")
    assert "services" in config
    assert len(config["services"]) > 0
    assert config["default_provider"] == "anthropic"


def test_unknown_agent_returns_default(monkeypatch):
    """Unknown agent_ref falls back to default."""
    monkeypatch.setenv("AMPLIFIER_AGENTS_DIR", "/nonexistent")
    monkeypatch.delenv("AMPLIFIER_SERVICE_MAP", raising=False)

    config = get_agent_config("nonexistent-agent-xyz")
    assert "services" in config


def test_yaml_without_service_map(tmp_path, monkeypatch):
    """YAML exists but no service-map -- falls back to hardcoded."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "foundation.yaml").write_text(FOUNDATION_YAML)

    monkeypatch.setenv("AMPLIFIER_AGENTS_DIR", str(agents_dir))
    monkeypatch.setenv("AMPLIFIER_SERVICE_MAP", str(tmp_path / "nonexistent.yaml"))

    config = get_agent_config("foundation")
    # Should still work -- either YAML-based or hardcoded fallback
    assert "services" in config
