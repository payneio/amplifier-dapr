"""Tests for Docker Compose generator."""

from pathlib import Path

import yaml

from ampctl.compose import generate_compose, write_compose
from ampctl.models import AgentDefinition, ServiceEntry, ServiceMapEntry
from ampctl.service_map import build_service_map_entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_build_agent() -> tuple[AgentDefinition, ServiceMapEntry]:
    """Minimal agent using build-based (string) service entries."""
    agent = AgentDefinition(
        ref="test/build-agent",
        orchestrator=ServiceEntry(build="./services/svc-orchestrator"),
        context_manager=ServiceEntry(build="./services/svc-context"),
        providers=ServiceEntry(build="./services/svc-providers"),
    )
    sme = build_service_map_entry(agent)
    return agent, sme


def _make_image_agent(suffix: str = "") -> tuple[AgentDefinition, ServiceMapEntry]:
    """Minimal agent using image-based service entries."""
    agent = AgentDefinition(
        ref=f"test/image-agent{suffix}",
        orchestrator=ServiceEntry(image=f"ghcr.io/example/orchestrator{suffix}:latest"),
        context_manager=ServiceEntry(image=f"ghcr.io/example/ctx{suffix}:latest"),
        providers=ServiceEntry(image=f"ghcr.io/example/prov{suffix}:latest"),
    )
    sme = build_service_map_entry(agent)
    return agent, sme


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generate_compose_includes_redis() -> None:
    """Redis service always present with correct image and port."""
    result = generate_compose({})
    services = result["services"]

    assert "redis" in services
    assert services["redis"]["image"] == "redis:7-alpine"
    assert "6379:6379" in services["redis"]["ports"]


def test_generate_compose_single_agent() -> None:
    """One agent produces app services and Dapr sidecars for all service entries."""
    agent, sme = _make_build_agent()
    result = generate_compose({"test/build-agent": (agent, sme)})
    services = result["services"]

    # Names come from the ServiceMapEntry (hashed), not derived from build paths.
    for service_name in [sme.orchestrator, sme.context_manager, sme.providers]:
        assert service_name in services, f"Missing service: {service_name}"
        assert f"{service_name}-dapr" in services, (
            f"Missing sidecar: {service_name}-dapr"
        )


def test_generate_compose_includes_session_service() -> None:
    """Session-service and its Dapr sidecar always present in output."""
    result = generate_compose({})
    services = result["services"]

    assert "session-service" in services
    assert "session-service-dapr" in services

    ss = services["session-service"]
    assert ss["build"] == {
        "context": ".",
        "dockerfile": "services/session-service/Dockerfile",
    }
    assert "${SESSION_SERVICE_PORT:-8090}:8000" in ss["ports"]
    assert "DAPR_HTTP_PORT" in ss["environment"]
    assert "AMPLIFIER_AGENTS_DIR" in ss["environment"]
    assert "AMPLIFIER_SERVICE_MAP" in ss["environment"]
    assert len(ss["volumes"]) > 0


def test_generate_compose_deduplication() -> None:
    """Two agents sharing the same image produce only one compose service entry."""
    shared_image = "ghcr.io/shared/orchestrator:latest"
    agent1 = AgentDefinition(
        ref="test/agent1",
        orchestrator=ServiceEntry(image=shared_image),
        context_manager=ServiceEntry(image="ctx1:latest"),
        providers=ServiceEntry(image="prov1:latest"),
    )
    agent2 = AgentDefinition(
        ref="test/agent2",
        orchestrator=ServiceEntry(image=shared_image),  # same image -> same hash
        context_manager=ServiceEntry(image="ctx2:latest"),
        providers=ServiceEntry(image="prov2:latest"),
    )
    sme1 = build_service_map_entry(agent1)
    sme2 = build_service_map_entry(agent2)

    result = generate_compose(
        {
            "test/agent1": (agent1, sme1),
            "test/agent2": (agent2, sme2),
        }
    )
    services = result["services"]

    # Both agents share the same source_key for orchestrator -> same hash -> one entry
    orch_name = sme1.orchestrator
    assert orch_name == sme2.orchestrator, "Same image must produce same hashed name"
    matching = [k for k in services if k == orch_name]
    assert len(matching) == 1


def test_compose_environment_passthrough() -> None:
    """Environment vars from ServiceEntry appear in the compose service environment."""
    agent = AgentDefinition(
        ref="test/env-agent",
        orchestrator=ServiceEntry(
            image="ghcr.io/example/orchestrator:latest",
            environment={"API_KEY": "secret", "LOG_LEVEL": "debug"},
        ),
        context_manager=ServiceEntry(image="ctx:latest"),
        providers=ServiceEntry(image="prov:latest"),
    )
    sme = build_service_map_entry(agent)
    result = generate_compose({"test/env-agent": (agent, sme)})
    services = result["services"]

    # Service is registered under its hashed name
    orch = services[sme.orchestrator]
    assert orch["environment"]["API_KEY"] == "secret"
    assert orch["environment"]["LOG_LEVEL"] == "debug"
    # DAPR_HTTP_PORT always present
    assert orch["environment"]["DAPR_HTTP_PORT"] == "3500"


def test_compose_volume_passthrough() -> None:
    """Volumes from ServiceEntry appear in the compose service volumes list."""
    agent = AgentDefinition(
        ref="test/vol-agent",
        orchestrator=ServiceEntry(
            image="ghcr.io/example/orchestrator:latest",
            volumes=["./data:/data", "./config:/config"],
        ),
        context_manager=ServiceEntry(image="ctx:latest"),
        providers=ServiceEntry(image="prov:latest"),
    )
    sme = build_service_map_entry(agent)
    result = generate_compose({"test/vol-agent": (agent, sme)})
    services = result["services"]

    # Service is registered under its hashed name
    orch = services[sme.orchestrator]
    assert "./data:/data" in orch["volumes"]
    assert "./config:/config" in orch["volumes"]


def test_compose_dapr_sidecar_format() -> None:
    """Each app service gets a -dapr sidecar with correct image, command and volumes."""
    agent, sme = _make_image_agent()
    result = generate_compose({"test/image-agent": (agent, sme)})
    services = result["services"]

    # Sidecar is named <hashed_service_name>-dapr
    orch_name = sme.orchestrator
    dapr_name = f"{orch_name}-dapr"
    assert dapr_name in services

    sidecar = services[dapr_name]
    assert sidecar["image"] == "daprio/daprd:1.14.4"
    assert sidecar["network_mode"] == f"service:{orch_name}"
    assert sidecar["depends_on"] == [orch_name]

    cmd = sidecar["command"]
    assert "./daprd" in cmd
    assert f"--app-id={orch_name}" in cmd
    assert "--app-port=8000" in cmd
    assert "--dapr-http-port=3500" in cmd
    assert "--dapr-grpc-port=50001" in cmd
    assert "--resources-path=/components" in cmd
    assert "--config=/config/config.yaml" in cmd

    assert "./docker/dapr/components:/components" in sidecar["volumes"]
    assert "./docker/dapr:/config" in sidecar["volumes"]


def test_compose_build_path_expansion() -> None:
    """`build: ./services/svc-bash` expands to a full build dict."""
    agent = AgentDefinition(
        ref="test/bash-agent",
        orchestrator=ServiceEntry(build="./services/svc-bash"),
        context_manager=ServiceEntry(image="ctx:latest"),
        providers=ServiceEntry(image="prov:latest"),
    )
    sme = build_service_map_entry(agent)
    result = generate_compose({"test/bash-agent": (agent, sme)})
    services = result["services"]

    # orchestrator uses build="./services/svc-bash" -> hashed service name
    orch = services[sme.orchestrator]
    assert isinstance(orch["build"], dict)
    assert orch["build"]["context"] == "."
    assert orch["build"]["dockerfile"] == "services/svc-bash/Dockerfile"


# ---------------------------------------------------------------------------
# Hashed naming tests
# ---------------------------------------------------------------------------


def test_compose_service_name_uses_hashed_names() -> None:
    """Service names use hashed names from ServiceMapEntry, not derived simple names."""
    agent, sme = _make_build_agent()
    result = generate_compose({"test/build-agent": (agent, sme)})
    services = result["services"]

    # Hashed names ARE present
    assert sme.orchestrator in services, (
        f"Expected hashed name '{sme.orchestrator}' in services"
    )
    assert sme.context_manager in services
    assert sme.providers in services

    # Simple derived names are NOT present
    assert "svc-orchestrator" not in services, (
        "Simple derived name 'svc-orchestrator' must not be used"
    )
    assert "svc-context" not in services
    assert "svc-providers" not in services


def test_compose_session_service_port_variable() -> None:
    """Session-service port uses ${SESSION_SERVICE_PORT:-8090}:8000 variable."""
    result = generate_compose({})
    ss = result["services"]["session-service"]
    assert "${SESSION_SERVICE_PORT:-8090}:8000" in ss["ports"], (
        f"Expected variable port, got: {ss['ports']}"
    )


def test_compose_session_service_volume_relative() -> None:
    """Session-service agents volume uses relative path ./agents:/agents."""
    result = generate_compose({})
    ss = result["services"]["session-service"]
    assert "./agents:/agents" in ss["volumes"], (
        f"Expected ./agents:/agents, got: {ss.get('volumes')}"
    )


def test_compose_behavior_depends_on() -> None:
    """A behavior with depends_on gets the dep's dapr sidecar in its depends_on."""
    agent = AgentDefinition(
        ref="test/deps-agent",
        orchestrator=ServiceEntry(build="./services/svc-orchestrator"),
        context_manager=ServiceEntry(build="./services/svc-context"),
        providers=ServiceEntry(build="./services/svc-providers"),
        behaviors={
            "machine": ServiceEntry(build="./services/svc-machine"),
            "bash": ServiceEntry(build="./services/svc-bash", depends_on=["machine"]),
        },
    )
    sme = build_service_map_entry(agent)
    result = generate_compose({"test/deps-agent": (agent, sme)})
    services = result["services"]

    # Bash service is registered under its hashed name
    bash_name = sme.behaviors["bash"]
    machine_name = sme.behaviors["machine"]
    bash_svc = services[bash_name]
    assert f"{machine_name}-dapr" in bash_svc["depends_on"], (
        f"Expected {machine_name}-dapr in bash depends_on, got: {bash_svc['depends_on']}"
    )


def test_compose_orchestrator_depends_on_context_and_providers() -> None:
    """Orchestrator depends_on includes context-dapr and providers-dapr."""
    agent, sme = _make_build_agent()
    result = generate_compose({"test/build-agent": (agent, sme)})
    services = result["services"]

    orch_deps = services[sme.orchestrator]["depends_on"]
    assert f"{sme.context_manager}-dapr" in orch_deps, (
        f"Expected {sme.context_manager}-dapr in orchestrator depends_on, got: {orch_deps}"
    )
    assert f"{sme.providers}-dapr" in orch_deps, (
        f"Expected {sme.providers}-dapr in orchestrator depends_on, got: {orch_deps}"
    )


def test_compose_session_service_depends_on_all_daprs() -> None:
    """Session-service depends_on includes all -dapr sidecar services."""
    agent, sme = _make_build_agent()
    result = generate_compose({"test/build-agent": (agent, sme)})
    services = result["services"]
    ss_deps = services["session-service"]["depends_on"]
    dapr_services = [name for name in services if name.endswith("-dapr")]
    # session-service-dapr is not in services yet when we compute deps,
    # but all agent daprs should be present
    for dapr_svc in dapr_services:
        if dapr_svc != "session-service-dapr":
            assert dapr_svc in ss_deps, (
                f"Missing {dapr_svc} in session-service depends_on: {ss_deps}"
            )


def test_compose_session_service_mounts_service_map() -> None:
    """Session-service volumes include read-only service-map mount from ~/.amplifier/."""
    result = generate_compose({})
    ss = result["services"]["session-service"]
    volumes: list[str] = ss["volumes"]
    service_map_mounts = [v for v in volumes if "service-map.yaml" in v]
    assert service_map_mounts, (
        f"Expected a service-map.yaml volume mount in session-service, got: {volumes}"
    )
    mount = service_map_mounts[0]
    assert mount.endswith(":ro"), (
        f"service-map.yaml volume mount must be read-only (:ro), got: {mount}"
    )
    assert mount.startswith("~/.amplifier/service-map.yaml:"), (
        f"service-map.yaml must be sourced from ~/.amplifier/, got: {mount}"
    )
    assert ":/agents/service-map.yaml" in mount, (
        f"service-map.yaml must be mounted at /agents/service-map.yaml, got: {mount}"
    )


def test_write_compose(tmp_path: Path) -> None:
    """write_compose writes the compose dict to a valid YAML file."""
    compose = {
        "services": {
            "redis": {
                "image": "redis:7-alpine",
                "ports": ["6379:6379"],
            }
        }
    }
    out = tmp_path / "docker-compose.yaml"
    write_compose(compose, out)

    assert out.exists()
    data = yaml.safe_load(out.read_text())
    assert data["services"]["redis"]["image"] == "redis:7-alpine"
    assert "6379:6379" in data["services"]["redis"]["ports"]
