"""Tests for the FastAPI service factory (create_app / ServiceConfig)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amplifier_service_sdk import ToolCapability
from amplifier_service_sdk.models import HookRegistration
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
    return ServiceConfig(name="svc-test", content_dir=str(content_dir))


@pytest.fixture
def config_with_tools(content_dir: Path) -> ServiceConfig:
    """Config that includes an 'echo' tool capability."""
    echo_tool = ToolCapability(
        name="echo",
        description="Echoes the input back",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    return ServiceConfig(
        name="svc-test", content_dir=str(content_dir), tools=[echo_tool]
    )


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


# ---------------------------------------------------------------------------
# TestHookRegistration in ServiceConfig
# ---------------------------------------------------------------------------


class TestServiceConfigHooks:
    def test_service_config_accepts_hooks(self) -> None:
        """ServiceConfig is a Pydantic BaseModel that accepts HookRegistration list."""
        from pydantic import BaseModel

        hooks = [
            HookRegistration(name="pre-tool", events=["tool_call"], priority=10),
            HookRegistration(name="post-response", events=["response"], mode="async"),
        ]
        config = ServiceConfig(name="hook-svc", hooks=hooks)
        # ServiceConfig must be a Pydantic BaseModel (not a dataclass)
        assert isinstance(config, BaseModel), (
            "ServiceConfig must be a pydantic BaseModel"
        )
        assert len(config.hooks) == 2
        assert config.hooks[0].name == "pre-tool"
        assert config.hooks[1].name == "post-response"
        # hooks must be HookRegistration instances, not raw dicts
        assert isinstance(config.hooks[0], HookRegistration)

    def test_describe_endpoint_includes_hooks(self) -> None:
        """GET /describe returns hooks list with correct names."""
        hooks = [
            HookRegistration(name="pre-tool", events=["tool_call"]),
            HookRegistration(name="post-response", events=["response"], mode="async"),
        ]
        config = ServiceConfig(name="hook-svc", hooks=hooks)
        app = create_app(config)
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert "hooks" in data
        hook_names = [h["name"] for h in data["hooks"]]
        assert "pre-tool" in hook_names
        assert "post-response" in hook_names
