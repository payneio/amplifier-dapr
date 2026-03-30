"""Tests for the FastAPI service factory (create_app / ServiceConfig)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amplifier_service_sdk import ToolCapability
from amplifier_service_sdk.service import ServiceConfig, create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    """Temporary content directory with one file: context/guide.md."""
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "guide.md").write_text("# Guide")
    return tmp_path


@pytest.fixture
def basic_config(content_dir: Path) -> ServiceConfig:
    """Minimal config pointing at the temp content directory."""
    return ServiceConfig(name="svc-test", content_dir=content_dir)


@pytest.fixture
def config_with_tools(content_dir: Path) -> ServiceConfig:
    """Config that includes an 'echo' tool capability."""
    echo_tool = ToolCapability(
        name="echo",
        description="Echoes the input back",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    return ServiceConfig(name="svc-test", content_dir=content_dir, tools=[echo_tool])


# ---------------------------------------------------------------------------
# TestHealthEndpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_healthz_returns_200(self, basic_config: ServiceConfig) -> None:
        """GET /healthz returns 200 with status='healthy' and service_name."""
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service_name"] == "svc-test"


# ---------------------------------------------------------------------------
# TestDescribeEndpoint
# ---------------------------------------------------------------------------


class TestDescribeEndpoint:
    def test_describe_returns_name_and_version(
        self, basic_config: ServiceConfig
    ) -> None:
        """GET /describe returns the service name and version."""
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-test"
        assert data["version"] == "0.1.0"

    def test_describe_includes_content_paths(self, basic_config: ServiceConfig) -> None:
        """GET /describe lists content_paths discovered from the content directory."""
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert "context/guide.md" in data["content_paths"]

    def test_describe_includes_tools(self, config_with_tools: ServiceConfig) -> None:
        """GET /describe returns the tools registered in the config."""
        app = create_app(config_with_tools)
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "echo" in tool_names


# ---------------------------------------------------------------------------
# TestContentEndpoint
# ---------------------------------------------------------------------------


class TestContentEndpoint:
    def test_content_serves_file(self, basic_config: ServiceConfig) -> None:
        """GET /content/{path} returns 200 and the file content for existing files."""
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/content/context/guide.md")
        assert response.status_code == 200
        data = response.json()
        assert "# Guide" in data["content"]

    def test_content_404_for_missing_file(self, basic_config: ServiceConfig) -> None:
        """GET /content/{path} returns 404 when the requested file does not exist."""
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/content/does/not/exist.md")
        assert response.status_code == 404

    def test_content_403_for_path_traversal(self, basic_config: ServiceConfig) -> None:
        """GET /content/{path} returns 403 or 404 for path-traversal attempts."""
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/content/../../etc/passwd")
        assert response.status_code in (403, 404)
