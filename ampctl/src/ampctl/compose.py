"""Docker Compose generator for Amplifier agent deployments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ampctl.models import AgentDefinition, ServiceEntry, ServiceMapEntry


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _expand_build(build_path: str) -> dict[str, str]:
    """Expand a shorthand build path string to a compose ``build:`` dict.

    Agent definitions use ``./services/svc-machine`` as shorthand.  The compose
    generator translates this to ``{context: ".", dockerfile: "services/svc-machine/Dockerfile"}``
    to match the repo-root context convention.
    """
    # Strip a leading "./" so the dockerfile path is relative to context "."
    if build_path.startswith("./"):
        clean = build_path[2:]
    else:
        clean = build_path
    return {"context": ".", "dockerfile": f"{clean}/Dockerfile"}


def _get_service_name(role_key: str, sme: ServiceMapEntry) -> str:
    """Look up the hashed service name from the ServiceMapEntry."""
    if role_key == "orchestrator":
        return sme.orchestrator
    if role_key == "context_manager":
        return sme.context_manager
    if role_key == "providers":
        return sme.providers
    return sme.behaviors.get(role_key, f"svc-{role_key}")


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
) -> dict[str, Any]:
    """Generate a complete docker-compose dict from installed agents.

    Args:
        agents: Mapping of agent ref -> (AgentDefinition, ServiceMapEntry).
        session_service_build: Build context for the session-service image.
        dapr_image: Dapr sidecar image tag to use for all sidecars.

    Returns:
        A dict suitable for ``yaml.dump()`` as a valid docker-compose file.
    """
    services: dict[str, Any] = {}

    # --- Redis (always present) ---
    services["redis"] = {
        "image": "redis:7-alpine",
        "ports": ["6379:6379"],
    }

    # --- Pass 1: collect role_key -> service_name mapping ---
    # Needed so that depends_on references can be resolved in pass 2 even when
    # the dependency's entry appears later in iteration order.
    all_role_names: dict[str, str] = {}
    for _agent_ref, (agent_def, sme) in agents.items():
        for role_key, _service_entry in agent_def.all_service_entries():
            all_role_names[role_key] = _get_service_name(role_key, sme)

    # --- Pass 2: build services (deduplicated by hashed name) ---
    seen: set[str] = set()
    for _agent_ref, (agent_def, sme) in agents.items():
        for role_key, service_entry in agent_def.all_service_entries():
            service_name = _get_service_name(role_key, sme)

            if service_name in seen:
                # Deduplicated: merge any additional env/volumes from this definition.
                _merge_service(services[service_name], service_entry)
                continue

            seen.add(service_name)
            svc = _make_app_service(service_entry)

            # Resolve behavior-key depends_on references to dapr sidecar names.
            if service_entry.depends_on:
                deps: list[str] = svc["depends_on"]
                for dep_key in service_entry.depends_on:
                    dep_svc_name = all_role_names.get(dep_key)
                    if dep_svc_name:
                        dapr_dep = f"{dep_svc_name}-dapr"
                        if dapr_dep not in deps:
                            deps.append(dapr_dep)

            services[service_name] = svc
            services[f"{service_name}-dapr"] = _make_dapr_sidecar(
                service_name, dapr_image
            )

    # --- Orchestrator depends_on: add context + providers + all behavior daprs ---
    orch_name = all_role_names.get("orchestrator")
    if orch_name and orch_name in services:
        orch_deps: list[str] = services[orch_name]["depends_on"]
        for key in ("context_manager", "providers"):
            name = all_role_names.get(key)
            if name:
                dep = f"{name}-dapr"
                if dep not in orch_deps:
                    orch_deps.append(dep)
        # Add all behavior daprs
        for _agent_ref, (agent_def, sme) in agents.items():
            for role_key, _entry in agent_def.all_service_entries():
                if role_key not in ("orchestrator", "context_manager", "providers"):
                    name = _get_service_name(role_key, sme)
                    dep = f"{name}-dapr"
                    if dep not in orch_deps:
                        orch_deps.append(dep)

    # --- Session service (always present) ---
    all_dapr_services = sorted(name for name in services if name.endswith("-dapr"))
    session_deps: list[str] = ["redis"] + all_dapr_services
    services["session-service"] = {
        "build": {
            "context": session_service_build,
            "dockerfile": "services/session-service/Dockerfile",
        },
        "ports": ["${SESSION_SERVICE_PORT:-8090}:8000"],
        "environment": {
            "DAPR_HTTP_PORT": "3500",
            "AMPLIFIER_AGENTS_DIR": "/agents",
            "AMPLIFIER_SERVICE_MAP": "/agents/service-map.yaml",
        },
        "volumes": [
            "./agents:/agents",
            "~/.amplifier/service-map.yaml:/agents/service-map.yaml:ro",
        ],
        "depends_on": session_deps,
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
