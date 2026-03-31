"""Tests for the svc-content-core describe.yaml configuration file.

TDD test written BEFORE the describe.yaml exists - verifies:
1. CLI import works
2. describe.yaml loads correctly with the expected name and content_dir
3. Dockerfile references correct content source directory
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent.parent
SVC_DIR = REPO_ROOT / "services" / "svc-content-core"
DESCRIBE_YAML = SVC_DIR / "describe.yaml"
DOCKERFILE = SVC_DIR / "Dockerfile"


# ---------------------------------------------------------------------------
# TestCLIImport
# ---------------------------------------------------------------------------


class TestCLIImport:
    def test_load_config_from_yaml_is_importable(self) -> None:
        """CLI module can be imported without errors."""
        from amplifier_service_sdk.cli import load_config_from_yaml  # noqa: F401

        assert callable(load_config_from_yaml)


# ---------------------------------------------------------------------------
# TestDescribeYaml
# ---------------------------------------------------------------------------


class TestDescribeYaml:
    def test_describe_yaml_exists(self) -> None:
        """services/svc-content-core/describe.yaml must exist."""
        assert DESCRIBE_YAML.exists(), f"Expected {DESCRIBE_YAML} to exist"

    def test_describe_yaml_loads_correctly(self) -> None:
        """describe.yaml loads via load_config_from_yaml with correct fields."""
        from amplifier_service_sdk.cli import load_config_from_yaml

        config = load_config_from_yaml(DESCRIBE_YAML)

        assert config.name == "svc-content-core"
        assert config.version == "0.1.0"

    def test_describe_yaml_has_content_dir(self) -> None:
        """describe.yaml must declare content_dir: content, resolved to absolute path."""
        from amplifier_service_sdk.cli import load_config_from_yaml

        config = load_config_from_yaml(DESCRIBE_YAML)

        assert config.content_dir is not None, "content_dir should not be None"
        assert Path(config.content_dir).name == "content", (
            f"Expected content_dir to end in 'content', got {config.content_dir}"
        )

    def test_describe_yaml_raw_content_dir_value(self) -> None:
        """Raw YAML content_dir field is the string 'content'."""
        import yaml

        raw = yaml.safe_load(DESCRIBE_YAML.read_text())
        assert raw.get("content_dir") == "content", (
            f"Expected content_dir='content' in raw YAML, got {raw.get('content_dir')!r}"
        )


# ---------------------------------------------------------------------------
# TestDockerfile
# ---------------------------------------------------------------------------


class TestDockerfile:
    def test_dockerfile_exists(self) -> None:
        """services/svc-content-core/Dockerfile must exist."""
        assert DOCKERFILE.exists(), f"Expected {DOCKERFILE} to exist"

    def test_dockerfile_uses_amplifier_service_base(self) -> None:
        """Dockerfile must reference amplifier-service-base as the base image."""
        content = DOCKERFILE.read_text()
        assert "amplifier-service-base" in content, (
            "Dockerfile should use 'amplifier-service-base' as base image"
        )

    def test_dockerfile_copies_describe_yaml(self) -> None:
        """Dockerfile must COPY describe.yaml to /app/."""
        content = DOCKERFILE.read_text()
        assert "describe.yaml" in content, "Dockerfile should COPY describe.yaml"
        assert "/app/" in content, "Dockerfile should copy describe.yaml to /app/"

    def test_dockerfile_copies_amplifier_core_context(self) -> None:
        """Dockerfile must reference amplifier-core context source directory."""
        content = DOCKERFILE.read_text()
        assert "amplifier-core" in content, (
            "Dockerfile should reference amplifier-core context directory"
        )
        assert "context" in content, (
            "Dockerfile should copy content from context/ directory"
        )

    def test_dockerfile_runs_amplifier_serve_with_config(self) -> None:
        """Dockerfile CMD must run amplifier-serve --config /app/describe.yaml."""
        content = DOCKERFILE.read_text()
        assert "amplifier-serve" in content, "Dockerfile should run amplifier-serve"
        assert "--config" in content, "Dockerfile should pass --config flag"
        assert "/app/describe.yaml" in content, (
            "Dockerfile should point to /app/describe.yaml"
        )
