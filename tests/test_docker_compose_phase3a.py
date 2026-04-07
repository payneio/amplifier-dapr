"""Tests for Phase 3a docker-compose.yaml structure.

TDD: These tests were written BEFORE the docker-compose.yaml was updated.
Validates that all Phase 3a services are defined with proper Dapr sidecars
and dependency chains.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
COMPOSE_PATH = REPO_ROOT / "docker-compose.yaml"

# Tool services (4 pairs) — depend on redis
TOOL_SERVICES = [
    "svc-web",
    "svc-skills",
    "svc-todo",
    "svc-modes",
]

# Services that depend on svc-machine-dapr in addition to redis
# (svc-filesystem and svc-search have been consolidated into svc-machine)
MACHINE_DEPENDENT_TOOL_SERVICES: list[str] = []

# Provider service (1 pair)
PROVIDER_SERVICES = [
    "svc-providers",
]

# Content services (8 pairs) — each depends on redis
CONTENT_SERVICES = [
    "svc-content-core",
    "svc-content-amplifier",
    "svc-content-browser-tester",
    "svc-content-design-intelligence",
    "svc-content-filesystem",
    "svc-content-recipes",
    "svc-content-superpowers",
    "svc-content-foundation",
]

# All new Phase 3a application services
PHASE3A_SERVICES = TOOL_SERVICES + PROVIDER_SERVICES + CONTENT_SERVICES

# All new Phase 3a sidecar names
PHASE3A_SIDECARS = [f"{svc}-dapr" for svc in PHASE3A_SERVICES]


def _load_compose() -> dict:
    """Load and parse the docker-compose.yaml; fails with a clear message if missing."""
    assert COMPOSE_PATH.exists(), f"Required file not found: {COMPOSE_PATH}."
    with COMPOSE_PATH.open() as f:
        return yaml.safe_load(f)


def _services(compose: dict) -> dict:
    """Return the services dict from a parsed compose file."""
    return compose.get("services", {})


class TestPhase3aServicesExist:
    """All 15 Phase 3a application services + sidecars must be defined."""

    def test_all_tool_services_present(self) -> None:
        """docker-compose.yaml defines all 6 tool services."""
        compose = _load_compose()
        services = _services(compose)
        for svc in TOOL_SERVICES:
            assert svc in services, (
                f"Tool service '{svc}' not found in docker-compose.yaml. "
                f"Found: {sorted(services.keys())}"
            )

    def test_all_tool_sidecars_present(self) -> None:
        """docker-compose.yaml defines all 6 tool service Dapr sidecars."""
        compose = _load_compose()
        services = _services(compose)
        for svc in TOOL_SERVICES:
            sidecar = f"{svc}-dapr"
            assert sidecar in services, (
                f"Tool sidecar '{sidecar}' not found in docker-compose.yaml."
            )

    def test_provider_service_present(self) -> None:
        """docker-compose.yaml defines svc-providers."""
        compose = _load_compose()
        services = _services(compose)
        assert "svc-providers" in services, (
            "Service 'svc-providers' not found in docker-compose.yaml."
        )

    def test_provider_sidecar_present(self) -> None:
        """docker-compose.yaml defines svc-providers-dapr."""
        compose = _load_compose()
        services = _services(compose)
        assert "svc-providers-dapr" in services, (
            "Sidecar 'svc-providers-dapr' not found in docker-compose.yaml."
        )

    def test_all_content_services_present(self) -> None:
        """docker-compose.yaml defines all 8 content services."""
        compose = _load_compose()
        services = _services(compose)
        for svc in CONTENT_SERVICES:
            assert svc in services, (
                f"Content service '{svc}' not found in docker-compose.yaml. "
                f"Found: {sorted(services.keys())}"
            )

    def test_all_content_sidecars_present(self) -> None:
        """docker-compose.yaml defines all 8 content service Dapr sidecars."""
        compose = _load_compose()
        services = _services(compose)
        for svc in CONTENT_SERVICES:
            sidecar = f"{svc}-dapr"
            assert sidecar in services, (
                f"Content sidecar '{sidecar}' not found in docker-compose.yaml."
            )


class TestPhase3aBuildContexts:
    """Each new application service must have build context . and correct dockerfile."""

    def test_all_services_have_build_context(self) -> None:
        """All Phase 3a services use build context '.'."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            build = services[svc].get("build", {})
            context = build.get("context", "")
            assert context == ".", (
                f"Service '{svc}' should have build context '.', got '{context}'"
            )

    def test_all_services_have_dockerfile(self) -> None:
        """All Phase 3a services specify a dockerfile path."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            build = services[svc].get("build", {})
            dockerfile = build.get("dockerfile", "")
            assert dockerfile, (
                f"Service '{svc}' should specify a dockerfile path, got: {build}"
            )
            assert "Dockerfile" in dockerfile, (
                f"Service '{svc}' dockerfile path should reference 'Dockerfile', got '{dockerfile}'"
            )


class TestPhase3aDaprHttpPort:
    """Each new application service must have DAPR_HTTP_PORT: 3500."""

    def test_all_services_have_dapr_http_port(self) -> None:
        """All Phase 3a services have DAPR_HTTP_PORT=3500 environment variable."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            env = services[svc].get("environment", {})
            if isinstance(env, list):
                env_str = " ".join(str(e) for e in env)
                has_dapr_port = "DAPR_HTTP_PORT" in env_str and "3500" in env_str
            else:
                has_dapr_port = str(env.get("DAPR_HTTP_PORT", "")) == "3500"
            assert has_dapr_port, (
                f"Service '{svc}' should have DAPR_HTTP_PORT=3500 in environment, got: {env}"
            )


class TestPhase3aDependencies:
    """Verify correct dependency chains for Phase 3a services."""

    def test_all_services_depend_on_redis(self) -> None:
        """All Phase 3a services depend on redis."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            deps = services[svc].get("depends_on", [])
            deps_list = list(deps) if isinstance(deps, dict) else deps
            assert "redis" in deps_list, (
                f"Service '{svc}' should depend on redis, got: {deps_list}"
            )

    def test_machine_dependent_services_depend_on_svc_machine_dapr(self) -> None:
        """No tool services require svc-machine-dapr (filesystem/search consolidated into svc-machine)."""
        # svc-filesystem and svc-search have been consolidated into svc-machine.
        # MACHINE_DEPENDENT_TOOL_SERVICES is now empty; this test is a no-op.
        compose = _load_compose()
        services = _services(compose)
        for svc in MACHINE_DEPENDENT_TOOL_SERVICES:
            deps = services[svc].get("depends_on", [])
            deps_list = list(deps) if isinstance(deps, dict) else deps
            assert "svc-machine-dapr" in deps_list, (
                f"Service '{svc}' should depend on svc-machine-dapr, got: {deps_list}"
            )

    def test_non_machine_dependent_services_do_not_require_machine_dapr(self) -> None:
        """svc-web, svc-skills, svc-todo, svc-modes do NOT need svc-machine-dapr."""
        compose = _load_compose()
        services = _services(compose)
        non_machine_services = [
            s for s in TOOL_SERVICES if s not in MACHINE_DEPENDENT_TOOL_SERVICES
        ]
        for svc in non_machine_services:
            deps = services[svc].get("depends_on", [])
            deps_list = list(deps) if isinstance(deps, dict) else deps
            # They should only depend on redis (not svc-machine-dapr)
            assert "redis" in deps_list, (
                f"Service '{svc}' should depend on redis, got: {deps_list}"
            )


class TestPhase3aProviderEnvVars:
    """svc-providers must expose ANTHROPIC_API_KEY and OPENAI_API_KEY from host."""

    def test_providers_has_anthropic_api_key(self) -> None:
        """svc-providers has ANTHROPIC_API_KEY environment variable (from host)."""
        compose = _load_compose()
        services = _services(compose)
        env = services["svc-providers"].get("environment", {})
        if isinstance(env, list):
            env_str = " ".join(str(e) for e in env)
            assert "ANTHROPIC_API_KEY" in env_str, (
                f"svc-providers should have ANTHROPIC_API_KEY in environment, got: {env}"
            )
        else:
            assert "ANTHROPIC_API_KEY" in env, (
                f"svc-providers should have ANTHROPIC_API_KEY in environment, got: {env}"
            )

    def test_providers_has_openai_api_key(self) -> None:
        """svc-providers has OPENAI_API_KEY environment variable (from host)."""
        compose = _load_compose()
        services = _services(compose)
        env = services["svc-providers"].get("environment", {})
        if isinstance(env, list):
            env_str = " ".join(str(e) for e in env)
            assert "OPENAI_API_KEY" in env_str, (
                f"svc-providers should have OPENAI_API_KEY in environment, got: {env}"
            )
        else:
            assert "OPENAI_API_KEY" in env, (
                f"svc-providers should have OPENAI_API_KEY in environment, got: {env}"
            )


class TestPhase3aDaprSidecars:
    """Each Phase 3a Dapr sidecar must follow the established pattern."""

    def test_all_sidecars_use_correct_image(self) -> None:
        """All Phase 3a Dapr sidecars use daprio/daprd:1.14.4."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            img = services[sidecar].get("image", "")
            assert img == "daprio/daprd:1.14.4", (
                f"{sidecar} should use image 'daprio/daprd:1.14.4', got '{img}'"
            )

    def test_all_sidecars_correct_app_id(self) -> None:
        """Each sidecar's command includes --app-id=<service-name>."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert f"--app-id={svc}" in cmd_str, (
                f"{sidecar} command should include '--app-id={svc}', got: {cmd_str}"
            )

    def test_all_sidecars_app_port_8000(self) -> None:
        """Each sidecar's command includes --app-port=8000."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--app-port=8000" in cmd_str, (
                f"{sidecar} command should include '--app-port=8000', got: {cmd_str}"
            )

    def test_all_sidecars_dapr_http_port(self) -> None:
        """Each sidecar's command includes --dapr-http-port=3500."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--dapr-http-port=3500" in cmd_str, (
                f"{sidecar} command should include '--dapr-http-port=3500', got: {cmd_str}"
            )

    def test_all_sidecars_dapr_grpc_port(self) -> None:
        """Each sidecar's command includes --dapr-grpc-port=50001."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--dapr-grpc-port=50001" in cmd_str, (
                f"{sidecar} command should include '--dapr-grpc-port=50001', got: {cmd_str}"
            )

    def test_all_sidecars_resources_path(self) -> None:
        """Each sidecar's command includes --resources-path=/components."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--resources-path=/components" in cmd_str, (
                f"{sidecar} command should include '--resources-path=/components', got: {cmd_str}"
            )

    def test_all_sidecars_config(self) -> None:
        """Each sidecar's command includes --config=/config/config.yaml."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--config=/config/config.yaml" in cmd_str, (
                f"{sidecar} command should include '--config=/config/config.yaml', got: {cmd_str}"
            )

    def test_all_sidecars_volumes(self) -> None:
        """Each Dapr sidecar mounts components and config volumes."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            volumes = services[sidecar].get("volumes", [])
            volumes_str = " ".join(str(v) for v in volumes)
            assert "components" in volumes_str, (
                f"{sidecar} should mount a components volume, got: {volumes}"
            )
            assert "config" in volumes_str or "dapr" in volumes_str, (
                f"{sidecar} should mount a config/dapr volume, got: {volumes}"
            )

    def test_all_sidecars_network_mode(self) -> None:
        """Each Dapr sidecar uses network_mode: service:<svc>."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            network_mode = services[sidecar].get("network_mode", "")
            expected = f"service:{svc}"
            assert network_mode == expected, (
                f"{sidecar} network_mode should be '{expected}', got '{network_mode}'"
            )

    def test_all_sidecars_depend_on_their_service(self) -> None:
        """Each Dapr sidecar depends on its own application service."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE3A_SERVICES:
            sidecar = f"{svc}-dapr"
            deps = services[sidecar].get("depends_on", [])
            deps_list = list(deps) if isinstance(deps, dict) else deps
            assert svc in deps_list, (
                f"{sidecar} should depend on '{svc}', got: {deps_list}"
            )


class TestSessionServiceUpdated:
    """session-service depends_on must include all new Phase 3a Dapr sidecars."""

    def test_session_service_depends_on_all_phase3a_sidecars(self) -> None:
        """session-service depends_on includes all 15 new Phase 3a Dapr sidecars."""
        compose = _load_compose()
        services = _services(compose)
        deps = services["session-service"].get("depends_on", [])
        deps_list = list(deps) if isinstance(deps, dict) else deps
        for sidecar in PHASE3A_SIDECARS:
            assert sidecar in deps_list, (
                f"session-service should depend on '{sidecar}', got: {deps_list}"
            )
