"""Tests verifying that old proxy services have been replaced by svc-machine.

These tests document the Phase 3 consolidation: svc-bash, svc-filesystem, and
svc-search have been superseded by svc-machine which provides all those
capabilities through a single service.
"""

from __future__ import annotations

from session_service.agents import AGENTS
from session_service.app import DEFAULT_SERVICES

#: The legacy proxy services that were replaced by svc-machine.
OLD_PROXY_SERVICES = ["svc-bash", "svc-filesystem", "svc-search"]


class TestDefaultServicesConsolidation:
    """Tests for DEFAULT_SERVICES list in session_service.app."""

    def test_default_services_excludes_old_proxy_services(self) -> None:
        """DEFAULT_SERVICES must not contain the old proxy service app-ids.

        svc-bash, svc-filesystem, and svc-search have been consolidated into
        svc-machine and should no longer appear in the default service list.
        """
        for old_svc in OLD_PROXY_SERVICES:
            assert old_svc not in DEFAULT_SERVICES, (
                f"DEFAULT_SERVICES still contains '{old_svc}'; "
                "it should have been replaced by svc-machine"
            )

    def test_default_services_includes_svc_machine(self) -> None:
        """DEFAULT_SERVICES must include svc-machine.

        svc-machine is the consolidated replacement for the old proxy services.
        """
        assert "svc-machine" in DEFAULT_SERVICES, (
            "DEFAULT_SERVICES must include 'svc-machine' (the consolidated replacement "
            "for svc-bash, svc-filesystem, and svc-search)"
        )


class TestAgentsDictConsolidation:
    """Tests for AGENTS dict in session_service.agents."""

    def test_agents_dict_excludes_old_proxy_services(self) -> None:
        """No AGENTS entry's services list should contain old proxy service app-ids.

        All agent definitions must use svc-machine instead of the old individual
        proxy services.
        """
        for agent_name, agent_config in AGENTS.items():
            services: list[str] = agent_config.get("services", [])
            for old_svc in OLD_PROXY_SERVICES:
                assert old_svc not in services, (
                    f"AGENTS['{agent_name}']['services'] still contains '{old_svc}'; "
                    "it should have been replaced by svc-machine"
                )

    def test_agents_dict_includes_svc_machine(self) -> None:
        """Every AGENTS entry's services list must contain svc-machine.

        svc-machine is the consolidated replacement and must be present in all
        agent service definitions.
        """
        for agent_name, agent_config in AGENTS.items():
            services: list[str] = agent_config.get("services", [])
            assert "svc-machine" in services, (
                f"AGENTS['{agent_name}']['services'] does not include 'svc-machine'; "
                "all agent entries must use the consolidated svc-machine service"
            )
