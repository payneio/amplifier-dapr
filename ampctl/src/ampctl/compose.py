"""Docker Compose generator for Amplifier agent deployments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ampctl.models import AgentDefinition, ServiceEntry, ServiceMapEntry
from ampctl.paths import agents_dir


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _expand_build(build_path: str) -> dict[str, str]:
    """Expand a shorthand build path string to a compose ``build:`` dict.

    Agent definitions use ``./services/svc-bash`` as shorthand.  The compose
    generator translates this to ``{context: ".", dockerfile: "services/svc-bash/Dockerfile"}``
    to match the repo-root context convention.
    """
    # Strip a leading "./" so the dockerfile path is relative to context "."
    if build_path.startswith("./"):
        clean = build_path[2:]
    else:
        clean = build_path
    return {"context": ".", "dockerfile": f"{clean}/Dockerfile"}


def _get_service_name(role_key: str, sme: ServiceMapEntry) -> str:
    """Resolve a role key to its Dapr app-id from the service map entry."""
    if role_key == "orchestrator":
        return sme.orchestrator
    if role_key == "context_manager":
        return sme.context_manager
    if role_key == "providers":
        return sme.providers
    return sme.behaviors[role_key]


def _make_app_service(entry: ServiceEntry) -> dict[str, Any]:
    """Build the compose service dict for an application container."""
    service: dict[str, Any] = {}

    if entry.image is not None:
        service["image"] = entry.image
    elif isinstance(entry.build, dict):
        service["build"] = dict(entry.build)
    elif isinstance(entry.build, str):
        service["build"] = _expand_build(entry.build)

    # DAPR_HTTP_PORT is always injected; entry-level env vars are merged on top.
    env: dict[str, str] = {"DAPR_HTTP_PORT": "3500"}
    if entry.environment:
        env.update(entry.environment)
    service["environment"] = env

    service["depends_on"] = ["redis"]

    if entry.volumes:
        service["volumes"] = list(entry.volumes)

    return service


def _make_dapr_sidecar(service_name: str, dapr_image: str) -> dict[str, Any]:
    """Build the compose service dict for a Dapr sidecar container."""
    return {
        "image": dapr_image,
        "command": [
            "./daprd",
            f"--app-id={service_name}",
            "--app-port=8000",
            "--dapr-http-port=3500",
            "--dapr-grpc-port=50001",
            "--resources-path=/components",
            "--config=/config/config.yaml",
        ],
        "volumes": [
            "./docker/dapr/components:/components",
            "./docker/dapr:/config",
        ],
        "network_mode": f"service:{service_name}",
        "depends_on": [service_name],
    }


def _merge_service(
    existing: dict[str, Any],
    entry: ServiceEntry,
) -> None:
    """Merge environment and volumes from *entry* into an *existing* service dict."""
    if entry.environment:
        existing_env: dict[str, str] = existing.get("environment", {})
        existing_env.update(entry.environment)
        existing["environment"] = existing_env

    if entry.volumes:
        existing_vols: list[str] = existing.get("volumes", [])
        for vol in entry.volumes:
            if vol not in existing_vols:
                existing_vols.append(vol)
        existing["volumes"] = existing_vols


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_compose(
    agents: dict[str, tuple[AgentDefinition, ServiceMapEntry]],
    session_service_build: str = ".",
    dapr_image: str = "daprio/daprd:1.14.4",
    workspace_path: str = "${WORKSPACE_PATH:-.}",
) -> dict[str, Any]:
    """Generate a complete docker-compose dict from installed agents.

    Args:
        agents: Mapping of agent ref -> (AgentDefinition, ServiceMapEntry).
        session_service_build: Build context for the session-service image.
        dapr_image: Dapr sidecar image tag to use for all sidecars.
        workspace_path: Host path (or compose variable) for workspace mounts.

    Returns:
        A dict suitable for ``yaml.dump()`` as a valid docker-compose file.
    """
    services: dict[str, Any] = {}

    # --- Redis (always present) ---
    services["redis"] = {
        "image": "redis:7-alpine",
        "ports": ["6379:6379"],
    }

    # --- Agent-derived services (deduplicated by service name) ---
    seen: set[str] = set()

    for _agent_ref, (agent_def, sme) in agents.items():
        for role_key, service_entry in agent_def.all_service_entries():
            service_name = _get_service_name(role_key, sme)

            if service_name in seen:
                # Deduplicated: merge any additional env/volumes from this definition.
                _merge_service(services[service_name], service_entry)
                continue

            seen.add(service_name)
            services[service_name] = _make_app_service(service_entry)
            services[f"{service_name}-dapr"] = _make_dapr_sidecar(
                service_name, dapr_image
            )

    # --- Session service (always present) ---
    agent_definitions_path = str(agents_dir())
    services["session-service"] = {
        "build": {
            "context": session_service_build,
            "dockerfile": "services/session-service/Dockerfile",
        },
        "ports": ["8080:8000"],
        "environment": {
            "DAPR_HTTP_PORT": "3500",
            "AMPLIFIER_AGENTS_DIR": "/agents",
            "AMPLIFIER_SERVICE_MAP": "/agents/service-map.yaml",
        },
        "volumes": [f"{agent_definitions_path}:/agents"],
        "depends_on": ["redis"],
    }
    services["session-service-dapr"] = _make_dapr_sidecar("session-service", dapr_image)

    return {"services": services}


def write_compose(compose_dict: dict[str, Any], output_path: Path) -> None:
    """Write a compose dict to a YAML file at *output_path*.

    Parent directories are created automatically if they do not exist.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as fh:
        yaml.dump(compose_dict, fh, default_flow_style=False, sort_keys=False)
