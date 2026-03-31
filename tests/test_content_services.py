"""
TDD tests for 8 content services (task-11-content-services).
Run BEFORE creating files to verify RED state, then again after to verify GREEN.
"""
import os
import pytest
import yaml
from pathlib import Path

REPO_ROOT = Path("/data/labs/amplifier-ipc")
SERVICES_DIR = REPO_ROOT / "services"

SERVICES = [
    {
        "name": "svc-content-amplifier",
        "source_context": "services/amplifier-amplifier/src/amplifier_amplifier/context/",
    },
    {
        "name": "svc-content-browser-tester",
        "source_context": "services/amplifier-browser-tester/src/amplifier_browser_tester/context/",
    },
    {
        "name": "svc-content-design-intelligence",
        "source_context": "services/amplifier-design-intelligence/src/amplifier_design_intelligence/context/",
    },
    {
        "name": "svc-content-filesystem",
        "source_context": "services/amplifier-filesystem/src/amplifier_filesystem/context/",
    },
    {
        "name": "svc-content-recipes",
        "source_context": "services/amplifier-recipes/src/amplifier_recipes/context/",
    },
    {
        "name": "svc-content-superpowers",
        "source_context": "services/amplifier-superpowers/src/amplifier_superpowers/context/",
    },
    {
        "name": "svc-content-system-design-intelligence",
        "source_context": "services/amplifier-system-design-intelligence/src/amplifier_system_design_intelligence/",
    },
]


class TestDescribeYaml:
    @pytest.mark.parametrize("svc", SERVICES, ids=[s["name"] for s in SERVICES])
    def test_describe_yaml_exists(self, svc):
        path = SERVICES_DIR / svc["name"] / "describe.yaml"
        assert path.exists(), f"Missing: {path}"

    @pytest.mark.parametrize("svc", SERVICES, ids=[s["name"] for s in SERVICES])
    def test_describe_yaml_has_correct_name(self, svc):
        path = SERVICES_DIR / svc["name"] / "describe.yaml"
        data = yaml.safe_load(path.read_text())
        assert data["name"] == svc["name"], f"Expected name={svc['name']}, got {data.get('name')}"

    @pytest.mark.parametrize("svc", SERVICES, ids=[s["name"] for s in SERVICES])
    def test_describe_yaml_has_version(self, svc):
        path = SERVICES_DIR / svc["name"] / "describe.yaml"
        data = yaml.safe_load(path.read_text())
        assert data["version"] == "0.1.0", f"Expected version=0.1.0, got {data.get('version')}"

    @pytest.mark.parametrize("svc", SERVICES, ids=[s["name"] for s in SERVICES])
    def test_describe_yaml_has_content_dir(self, svc):
        path = SERVICES_DIR / svc["name"] / "describe.yaml"
        data = yaml.safe_load(path.read_text())
        assert data["content_dir"] == "content", f"Expected content_dir=content, got {data.get('content_dir')}"


class TestDockerfile:
    @pytest.mark.parametrize("svc", SERVICES, ids=[s["name"] for s in SERVICES])
    def test_dockerfile_exists(self, svc):
        path = SERVICES_DIR / svc["name"] / "Dockerfile"
        assert path.exists(), f"Missing: {path}"

    @pytest.mark.parametrize("svc", SERVICES, ids=[s["name"] for s in SERVICES])
    def test_dockerfile_from_base(self, svc):
        path = SERVICES_DIR / svc["name"] / "Dockerfile"
        content = path.read_text()
        assert "FROM amplifier-service-base" in content

    @pytest.mark.parametrize("svc", SERVICES, ids=[s["name"] for s in SERVICES])
    def test_dockerfile_copies_describe_yaml(self, svc):
        path = SERVICES_DIR / svc["name"] / "Dockerfile"
        content = path.read_text()
        assert f"COPY services/{svc['name']}/describe.yaml /app/describe.yaml" in content

    @pytest.mark.parametrize("svc", SERVICES, ids=[s["name"] for s in SERVICES])
    def test_dockerfile_copies_content(self, svc):
        path = SERVICES_DIR / svc["name"] / "Dockerfile"
        content = path.read_text()
        assert f"COPY {svc['source_context']}" in content
        assert "/app/content/" in content

    @pytest.mark.parametrize("svc", SERVICES, ids=[s["name"] for s in SERVICES])
    def test_dockerfile_has_cmd(self, svc):
        path = SERVICES_DIR / svc["name"] / "Dockerfile"
        content = path.read_text()
        assert 'amplifier-serve' in content
        assert '/app/describe.yaml' in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
