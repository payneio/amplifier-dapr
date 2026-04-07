"""Tests for Phase 2 docker-compose.yaml structure.

TDD: These tests were written BEFORE the docker-compose.yaml was updated.
Validates that all Phase 2 services are defined with proper Dapr sidecars
and dependency chains.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
COMPOSE_PATH = REPO_ROOT / "docker-compose.yaml"

# The 5 application services (not sidecars) required in Phase 2
PHASE2_SERVICES = [
    "svc-machine",
    "svc-context",
    "svc-mock-provider",
    "svc-orchestrator",
    "session-service",
]

# All service names expected (application services + sidecars + redis)
ALL_EXPECTED_SERVICES = (
    ["redis"] + PHASE2_SERVICES + [f"{svc}-dapr" for svc in PHASE2_SERVICES]
)


def _load_compose() -> dict:
    """Load and parse the docker-compose.yaml; fails with a clear message if missing."""
    assert COMPOSE_PATH.exists(), f"Required file not found: {COMPOSE_PATH}."
    with COMPOSE_PATH.open() as f:
        return yaml.safe_load(f)


def _services(compose: dict) -> dict:
    """Return the services dict from a parsed compose file."""
    return compose.get("services", {})


class TestPhase2ServicesExist:
    """All 6 Phase 2 application services must be defined."""

    def test_all_services_present(self) -> None:
        """docker-compose.yaml defines all required service names."""
        compose = _load_compose()
        services = _services(compose)
        for svc in ALL_EXPECTED_SERVICES:
            assert svc in services, (
                f"Service '{svc}' not found in docker-compose.yaml. "
                f"Found: {sorted(services.keys())}"
            )

    def test_redis_service(self) -> None:
        """redis service uses redis:7-alpine and exposes port 6379."""
        compose = _load_compose()
        redis = _services(compose)["redis"]
        assert redis["image"] == "redis:7-alpine"
        ports = redis.get("ports", [])
        assert any("6379" in str(p) for p in ports), (
            f"redis should expose port 6379, got ports: {ports}"
        )


class TestDaprSidecars:
    """Each Phase 2 service must have a corresponding Dapr sidecar."""

    def test_all_dapr_sidecars_present(self) -> None:
        """Each application service has a corresponding *-dapr sidecar."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            assert sidecar in services, (
                f"Dapr sidecar '{sidecar}' not found in docker-compose.yaml"
            )

    def test_dapr_sidecars_use_correct_image(self) -> None:
        """All Dapr sidecars use daprio/daprd:1.14.4."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            img = services[sidecar].get("image", "")
            assert img == "daprio/daprd:1.14.4", (
                f"{sidecar} should use image 'daprio/daprd:1.14.4', got '{img}'"
            )

    def test_dapr_sidecars_network_mode(self) -> None:
        """Each Dapr sidecar uses network_mode: service:<svc>."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            network_mode = services[sidecar].get("network_mode", "")
            expected = f"service:{svc}"
            assert network_mode == expected, (
                f"{sidecar} network_mode should be '{expected}', got '{network_mode}'"
            )

    def test_dapr_sidecars_app_id(self) -> None:
        """Each sidecar's command includes the correct --app-id."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            expected_flag = f"--app-id={svc}"
            assert expected_flag in cmd_str, (
                f"{sidecar} command should include '{expected_flag}', got: {cmd_str}"
            )

    def test_dapr_sidecars_app_port(self) -> None:
        """Each sidecar's command includes --app-port=8000."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--app-port=8000" in cmd_str, (
                f"{sidecar} command should include '--app-port=8000', got: {cmd_str}"
            )

    def test_dapr_sidecars_dapr_http_port(self) -> None:
        """Each sidecar's command includes --dapr-http-port=3500."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--dapr-http-port=3500" in cmd_str, (
                f"{sidecar} command should include '--dapr-http-port=3500', got: {cmd_str}"
            )

    def test_dapr_sidecars_dapr_grpc_port(self) -> None:
        """Each sidecar's command includes --dapr-grpc-port=50001."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--dapr-grpc-port=50001" in cmd_str, (
                f"{sidecar} command should include '--dapr-grpc-port=50001', got: {cmd_str}"
            )

    def test_dapr_sidecars_resources_path(self) -> None:
        """Each sidecar's command includes --resources-path=/components."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--resources-path=/components" in cmd_str, (
                f"{sidecar} command should include '--resources-path=/components', got: {cmd_str}"
            )

    def test_dapr_sidecars_config(self) -> None:
        """Each sidecar's command includes --config=/config/config.yaml."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--config=/config/config.yaml" in cmd_str, (
                f"{sidecar} command should include '--config=/config/config.yaml', got: {cmd_str}"
            )

    def test_dapr_sidecars_volumes(self) -> None:
        """Each Dapr sidecar mounts components and config volumes."""
        compose = _load_compose()
        services = _services(compose)
        for svc in PHASE2_SERVICES:
            sidecar = f"{svc}-dapr"
            volumes = services[sidecar].get("volumes", [])
            volumes_str = " ".join(str(v) for v in volumes)
            assert "components" in volumes_str, (
                f"{sidecar} should mount a components volume, got: {volumes}"
            )
            assert "config" in volumes_str or "dapr" in volumes_str, (
                f"{sidecar} should mount a config/dapr volume, got: {volumes}"
            )


class TestSessionServicePort:
    """session-service must expose port 8090:8000."""

    def test_session_service_port_mapping(self) -> None:
        """session-service exposes port 8090:8000."""
        compose = _load_compose()
        services = _services(compose)
        session_svc = services["session-service"]
        ports = session_svc.get("ports", [])
        ports_str = " ".join(str(p) for p in ports)
        assert "8090" in ports_str and "8000" in ports_str, (
            f"session-service should expose port 8090:8000, got ports: {ports}"
        )


class TestDependencyChains:
    """Verify correct dependency chains."""

    def test_svc_context_depends_on_redis(self) -> None:
        """svc-context depends on redis."""
        compose = _load_compose()
        services = _services(compose)
        deps = services["svc-context"].get("depends_on", [])
        deps_list = list(deps) if isinstance(deps, dict) else deps
        assert "redis" in deps_list, (
            f"svc-context should depend on redis, got: {deps_list}"
        )

    def test_svc_mock_provider_depends_on_redis(self) -> None:
        """svc-mock-provider depends on redis."""
        compose = _load_compose()
        services = _services(compose)
        deps = services["svc-mock-provider"].get("depends_on", [])
        deps_list = list(deps) if isinstance(deps, dict) else deps
        assert "redis" in deps_list, (
            f"svc-mock-provider should depend on redis, got: {deps_list}"
        )

    def test_svc_orchestrator_depends_on_sidecars(self) -> None:
        """svc-orchestrator depends on context, provider, and bash dapr sidecars."""
        compose = _load_compose()
        services = _services(compose)
        deps = services["svc-orchestrator"].get("depends_on", [])
        deps_list = list(deps) if isinstance(deps, dict) else deps
        for required in [
            "svc-context-dapr",
            "svc-mock-provider-dapr",
            "svc-machine-dapr",
        ]:
            assert required in deps_list, (
                f"svc-orchestrator should depend on '{required}', got: {deps_list}"
            )

    def test_session_service_depends_on_all_sidecars(self) -> None:
        """session-service depends on redis and all other Dapr sidecars (not its own)."""
        compose = _load_compose()
        services = _services(compose)
        deps = services["session-service"].get("depends_on", [])
        deps_list = list(deps) if isinstance(deps, dict) else deps
        # Must depend on redis
        assert "redis" in deps_list, (
            f"session-service should depend on redis, got: {deps_list}"
        )
        # Must depend on all other dapr sidecars (session-service-dapr would be circular)
        other_sidecars = [
            f"{svc}-dapr" for svc in PHASE2_SERVICES if svc != "session-service"
        ]
        for sidecar in other_sidecars:
            assert sidecar in deps_list, (
                f"session-service should depend on '{sidecar}', got: {deps_list}"
            )

    def test_svc_machine_dapr_http_port_env(self) -> None:
        """svc-machine has DAPR_HTTP_PORT=3500 environment variable."""
        compose = _load_compose()
        services = _services(compose)
        # Handle hash-suffixed service names (e.g., svc-machine-<hash>)
        svc_machine_key = next(
            (k for k in services if k == "svc-machine" or k.startswith("svc-machine-")),
            None,
        )
        assert svc_machine_key is not None, (
            f"svc-machine service not found in docker-compose.yaml. Found: {sorted(services.keys())}"
        )
        env = services[svc_machine_key].get("environment", {})
        if isinstance(env, list):
            env_str = " ".join(str(e) for e in env)
            assert "DAPR_HTTP_PORT" in env_str and "3500" in env_str, (
                f"svc-machine should have DAPR_HTTP_PORT=3500 in environment, got: {env}"
            )
        else:
            assert str(env.get("DAPR_HTTP_PORT", "")) == "3500", (
                f"svc-machine should have DAPR_HTTP_PORT=3500, got: {env}"
            )

    def test_new_services_dapr_http_port_env(self) -> None:
        """New services (svc-context, svc-mock-provider, svc-orchestrator, session-service) have DAPR_HTTP_PORT=3500."""
        compose = _load_compose()
        services = _services(compose)
        for svc in [
            "svc-context",
            "svc-mock-provider",
            "svc-orchestrator",
            "session-service",
        ]:
            env = services[svc].get("environment", {})
            if isinstance(env, list):
                env_str = " ".join(str(e) for e in env)
                has_dapr_port = "DAPR_HTTP_PORT" in env_str and "3500" in env_str
            else:
                has_dapr_port = str(env.get("DAPR_HTTP_PORT", "")) == "3500"
            assert has_dapr_port, (
                f"{svc} should have DAPR_HTTP_PORT=3500 in environment, got: {env}"
            )


class TestSvcMachineWorkspaceVolume:
    """svc-machine should include a workspace volume."""

    def test_svc_machine_has_workspace_volume(self) -> None:
        """svc-machine mounts a workspace volume."""
        compose = _load_compose()
        services = _services(compose)
        volumes = services["svc-machine"].get("volumes", [])
        volumes_str = " ".join(str(v) for v in volumes)
        assert "workspace" in volumes_str, (
            f"svc-machine should have a workspace volume, got: {volumes}"
        )
