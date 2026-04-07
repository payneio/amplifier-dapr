"""
Tests verifying that docker-compose.yaml is regenerated correctly:
- No references to svc-bash, svc-filesystem, or svc-search
- svc-machine IS present
- agents/service-map.yaml also excludes old services

These are acceptance criteria tests for task-3: Regenerate docker-compose.yaml via ampctl compose.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.yaml"
SERVICE_MAP_FILE = REPO_ROOT / "agents" / "service-map.yaml"


# ---------------------------------------------------------------------------
# docker-compose.yaml tests
# ---------------------------------------------------------------------------


def test_compose_file_exists():
    """docker-compose.yaml must exist at the repo root."""
    assert COMPOSE_FILE.exists(), "docker-compose.yaml not found at repo root"


def test_compose_no_svc_bash():
    """docker-compose.yaml must not contain any reference to svc-bash."""
    content = COMPOSE_FILE.read_text()
    assert "svc-bash" not in content, (
        "docker-compose.yaml still contains 'svc-bash' — regenerate with ampctl compose"
    )


def test_compose_no_svc_filesystem():
    """docker-compose.yaml must not contain any reference to svc-filesystem."""
    content = COMPOSE_FILE.read_text()
    assert "svc-filesystem" not in content, (
        "docker-compose.yaml still contains 'svc-filesystem' — regenerate with ampctl compose"
    )


def test_compose_no_svc_search():
    """docker-compose.yaml must not contain any reference to svc-search."""
    content = COMPOSE_FILE.read_text()
    assert "svc-search" not in content, (
        "docker-compose.yaml still contains 'svc-search' — regenerate with ampctl compose"
    )


def test_compose_has_svc_machine():
    """docker-compose.yaml must contain svc-machine (positive presence check)."""
    content = COMPOSE_FILE.read_text()
    assert "svc-machine" in content, (
        "docker-compose.yaml is missing 'svc-machine' — it must be present"
    )


def test_compose_is_valid_yaml():
    """docker-compose.yaml must be parseable as valid YAML."""
    with COMPOSE_FILE.open() as f:
        data = yaml.safe_load(f)
    assert data is not None, "docker-compose.yaml is empty or invalid YAML"
    assert "services" in data, "docker-compose.yaml must have a 'services' key"


def test_compose_svc_machine_count():
    """docker-compose.yaml must have at least one line with 'svc-machine'."""
    content = COMPOSE_FILE.read_text()
    count = content.count("svc-machine")
    assert count > 0, f"Expected svc-machine count > 0 but got {count}"


# ---------------------------------------------------------------------------
# agents/service-map.yaml tests
# ---------------------------------------------------------------------------


def test_service_map_no_svc_bash():
    """agents/service-map.yaml must not contain any reference to svc-bash."""
    if not SERVICE_MAP_FILE.exists() or SERVICE_MAP_FILE.stat().st_size == 0:
        pytest.skip("agents/service-map.yaml is empty or does not exist — skipping")
    content = SERVICE_MAP_FILE.read_text()
    assert "svc-bash" not in content, (
        "agents/service-map.yaml still contains 'svc-bash'"
    )


def test_service_map_no_svc_filesystem():
    """agents/service-map.yaml must not contain any reference to svc-filesystem."""
    if not SERVICE_MAP_FILE.exists() or SERVICE_MAP_FILE.stat().st_size == 0:
        pytest.skip("agents/service-map.yaml is empty or does not exist — skipping")
    content = SERVICE_MAP_FILE.read_text()
    assert "svc-filesystem" not in content, (
        "agents/service-map.yaml still contains 'svc-filesystem'"
    )


def test_service_map_no_svc_search():
    """agents/service-map.yaml must not contain any reference to svc-search."""
    if not SERVICE_MAP_FILE.exists() or SERVICE_MAP_FILE.stat().st_size == 0:
        pytest.skip("agents/service-map.yaml is empty or does not exist — skipping")
    content = SERVICE_MAP_FILE.read_text()
    assert "svc-search" not in content, (
        "agents/service-map.yaml still contains 'svc-search'"
    )
