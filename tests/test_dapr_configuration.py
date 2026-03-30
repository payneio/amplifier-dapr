"""Tests for Dapr component configuration YAML files.

TDD: These tests were written BEFORE the YAML files were created.
Validates statestore, pubsub, and dapr config YAML structure/content.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Resolve the repo root relative to this test file (tests/ → project root)
REPO_ROOT = Path(__file__).parent.parent

STATESTORE_PATH = REPO_ROOT / "docker" / "dapr" / "components" / "statestore.yaml"
PUBSUB_PATH = REPO_ROOT / "docker" / "dapr" / "components" / "pubsub.yaml"
CONFIG_PATH = REPO_ROOT / "docker" / "dapr" / "config.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(path: Path) -> dict:
    """Load and parse a YAML file; fails with a clear message if missing."""
    assert path.exists(), (
        f"Required file not found: {path}. Create it per the Dapr configuration spec."
    )
    with path.open() as f:
        return yaml.safe_load(f)


def _metadata_value(doc: dict, name: str) -> str | None:
    """Return the value for the given metadata item name."""
    items = doc.get("spec", {}).get("metadata", []) or []
    for item in items:
        if item.get("name") == name:
            return item.get("value")
    return None


# ---------------------------------------------------------------------------
# statestore.yaml
# ---------------------------------------------------------------------------


class TestStatestoreYaml:
    """Validate docker/dapr/components/statestore.yaml."""

    def test_file_exists(self) -> None:
        """statestore.yaml exists at the expected path."""
        assert STATESTORE_PATH.exists(), f"Expected {STATESTORE_PATH} to exist"

    def test_is_valid_yaml(self) -> None:
        """statestore.yaml is parseable as valid YAML."""
        _load(STATESTORE_PATH)  # raises on invalid YAML

    def test_api_version(self) -> None:
        """apiVersion must be dapr.io/v1alpha1."""
        doc = _load(STATESTORE_PATH)
        assert doc["apiVersion"] == "dapr.io/v1alpha1"

    def test_kind(self) -> None:
        """kind must be Component."""
        doc = _load(STATESTORE_PATH)
        assert doc["kind"] == "Component"

    def test_metadata_name(self) -> None:
        """metadata.name must be statestore."""
        doc = _load(STATESTORE_PATH)
        assert doc["metadata"]["name"] == "statestore"

    def test_spec_type(self) -> None:
        """spec.type must be state.redis."""
        doc = _load(STATESTORE_PATH)
        assert doc["spec"]["type"] == "state.redis"

    def test_spec_version(self) -> None:
        """spec.version must be v1."""
        doc = _load(STATESTORE_PATH)
        assert doc["spec"]["version"] == "v1"

    def test_redis_host(self) -> None:
        """spec.metadata redisHost must be redis:6379."""
        doc = _load(STATESTORE_PATH)
        assert _metadata_value(doc, "redisHost") == "redis:6379"

    def test_redis_password(self) -> None:
        """spec.metadata redisPassword must be empty string."""
        doc = _load(STATESTORE_PATH)
        val = _metadata_value(doc, "redisPassword")
        assert val == "" or val is None or val == "''"

    def test_actor_state_store(self) -> None:
        """spec.metadata actorStateStore must be 'true'."""
        doc = _load(STATESTORE_PATH)
        val = _metadata_value(doc, "actorStateStore")
        assert str(val).lower() in ("true", "'true'"), (
            f"actorStateStore should be 'true', got {val!r}"
        )


# ---------------------------------------------------------------------------
# pubsub.yaml
# ---------------------------------------------------------------------------


class TestPubsubYaml:
    """Validate docker/dapr/components/pubsub.yaml."""

    def test_file_exists(self) -> None:
        """pubsub.yaml exists at the expected path."""
        assert PUBSUB_PATH.exists(), f"Expected {PUBSUB_PATH} to exist"

    def test_is_valid_yaml(self) -> None:
        """pubsub.yaml is parseable as valid YAML."""
        _load(PUBSUB_PATH)  # raises on invalid YAML

    def test_api_version(self) -> None:
        """apiVersion must be dapr.io/v1alpha1."""
        doc = _load(PUBSUB_PATH)
        assert doc["apiVersion"] == "dapr.io/v1alpha1"

    def test_kind(self) -> None:
        """kind must be Component."""
        doc = _load(PUBSUB_PATH)
        assert doc["kind"] == "Component"

    def test_metadata_name(self) -> None:
        """metadata.name must be pubsub."""
        doc = _load(PUBSUB_PATH)
        assert doc["metadata"]["name"] == "pubsub"

    def test_spec_type(self) -> None:
        """spec.type must be pubsub.redis."""
        doc = _load(PUBSUB_PATH)
        assert doc["spec"]["type"] == "pubsub.redis"

    def test_spec_version(self) -> None:
        """spec.version must be v1."""
        doc = _load(PUBSUB_PATH)
        assert doc["spec"]["version"] == "v1"

    def test_redis_host(self) -> None:
        """spec.metadata redisHost must be redis:6379."""
        doc = _load(PUBSUB_PATH)
        assert _metadata_value(doc, "redisHost") == "redis:6379"

    def test_redis_password(self) -> None:
        """spec.metadata redisPassword must be empty string."""
        doc = _load(PUBSUB_PATH)
        val = _metadata_value(doc, "redisPassword")
        assert val == "" or val is None or val == "''"


# ---------------------------------------------------------------------------
# config.yaml
# ---------------------------------------------------------------------------


class TestDaprConfigYaml:
    """Validate docker/dapr/config.yaml."""

    def test_file_exists(self) -> None:
        """config.yaml exists at the expected path."""
        assert CONFIG_PATH.exists(), f"Expected {CONFIG_PATH} to exist"

    def test_is_valid_yaml(self) -> None:
        """config.yaml is parseable as valid YAML."""
        _load(CONFIG_PATH)  # raises on invalid YAML

    def test_api_version(self) -> None:
        """apiVersion must be dapr.io/v1alpha1."""
        doc = _load(CONFIG_PATH)
        assert doc["apiVersion"] == "dapr.io/v1alpha1"

    def test_kind(self) -> None:
        """kind must be Configuration."""
        doc = _load(CONFIG_PATH)
        assert doc["kind"] == "Configuration"

    def test_metadata_name(self) -> None:
        """metadata.name must be amplifier-config."""
        doc = _load(CONFIG_PATH)
        assert doc["metadata"]["name"] == "amplifier-config"

    def test_tracing_sampling_rate(self) -> None:
        """spec.tracing.samplingRate must be '1'."""
        doc = _load(CONFIG_PATH)
        rate = doc["spec"]["tracing"]["samplingRate"]
        assert str(rate) == "1", f"Expected samplingRate '1', got {rate!r}"

    def test_metric_enabled(self) -> None:
        """spec.metric.enabled must be true."""
        doc = _load(CONFIG_PATH)
        assert doc["spec"]["metric"]["enabled"] is True
