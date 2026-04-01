"""Tests for session_service.agents — agent registry and resolution."""

from __future__ import annotations

import pytest

from session_service.agents import AGENTS, resolve_agent


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
        expected = {"svc-bash", "svc-filesystem", "svc-search", "svc-web", "svc-providers"}
        assert expected.issubset(set(cfg["services"]))

    @pytest.mark.parametrize("agent_name", list(AGENTS.keys()))
    def test_all_agents_have_required_keys(self, agent_name: str) -> None:
        """Every agent in the registry has at minimum 'services' and 'default_provider'."""
        cfg = resolve_agent(agent_name)
        assert "services" in cfg, f"{agent_name!r} missing 'services'"
        assert "default_provider" in cfg, f"{agent_name!r} missing 'default_provider'"
        assert isinstance(cfg["services"], list)
        assert len(cfg["services"]) > 0
