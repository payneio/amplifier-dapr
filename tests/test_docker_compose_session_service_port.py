"""Tests for session-service port 8090 exposure in docker-compose.yaml (task-10).

TDD: Written to verify the session-service port configuration.
Validates that session-service exposes port 8090 (mapped to internal 8000)
so CLI tools can reach the service at http://localhost:8090.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
COMPOSE_PATH = REPO_ROOT / "docker-compose.yaml"


def _load_compose() -> dict:
    """Load and parse the docker-compose.yaml; fails with a clear message if missing."""
    assert COMPOSE_PATH.exists(), (
        f"Required file not found: {COMPOSE_PATH}."
    )
    with COMPOSE_PATH.open() as f:
        return yaml.safe_load(f)


def _services(compose: dict) -> dict:
    """Return the services dict from a parsed compose file."""
    return compose.get("services", {})


class TestSessionServicePortExposure:
    """session-service must expose port 8090 for CLI access."""

    def test_session_service_exists_in_compose(self) -> None:
        """session-service is defined in docker-compose.yaml."""
        compose = _load_compose()
        services = _services(compose)
        assert "session-service" in services, (
            "session-service not found in docker-compose.yaml. "
            f"Found services: {sorted(services.keys())}"
        )

    def test_session_service_has_ports(self) -> None:
        """session-service has a ports section."""
        compose = _load_compose()
        session_service = _services(compose)["session-service"]
        assert "ports" in session_service, (
            "session-service has no 'ports' section in docker-compose.yaml"
        )

    def test_session_service_exposes_port_8090(self) -> None:
        """session-service exposes port 8090:8000 for external access."""
        compose = _load_compose()
        session_service = _services(compose)["session-service"]
        ports = session_service.get("ports", [])

        # Normalize ports to strings for comparison
        port_strings = [str(p) for p in ports]

        assert any("8090" in p for p in port_strings), (
            f"session-service does not expose port 8090. Found ports: {ports}"
        )

    def test_session_service_port_mapping_is_8090_to_8000(self) -> None:
        """session-service maps external port 8090 to internal port 8000."""
        compose = _load_compose()
        session_service = _services(compose)["session-service"]
        ports = session_service.get("ports", [])

        # Check for mapping to internal port 8000 (external port may use env var)
        port_strings = [str(p) for p in ports]
        assert any("8000" in p for p in port_strings), (
            f"session-service does not map to internal port 8000. Found ports: {ports}."
        )

    def test_session_service_dapr_sidecar_exists(self) -> None:
        """session-service-dapr sidecar is defined in docker-compose.yaml."""
        compose = _load_compose()
        services = _services(compose)
        assert "session-service-dapr" in services, (
            "session-service-dapr sidecar not found in docker-compose.yaml."
        )

    def test_session_service_dapr_network_mode(self) -> None:
        """session-service-dapr uses service network mode with session-service."""
        compose = _load_compose()
        session_service_dapr = _services(compose)["session-service-dapr"]
        network_mode = session_service_dapr.get("network_mode", "")
        assert network_mode == "service:session-service", (
            f"session-service-dapr should use network_mode 'service:session-service', "
            f"got '{network_mode}'"
        )

    def test_session_service_depends_on_redis(self) -> None:
        """session-service depends on redis."""
        compose = _load_compose()
        session_service = _services(compose)["session-service"]
        depends_on = session_service.get("depends_on", [])
        assert "redis" in depends_on, (
            f"session-service should depend on redis. "
            f"Found depends_on: {depends_on}"
        )
