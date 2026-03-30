"""Tests for svc-machine FastAPI service endpoints."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_machine.service import create_machine_app


class TestModuleLevelApp:
    """Tests for the module-level app object."""

    def test_module_exposes_app(self) -> None:
        """svc_machine.service must expose a module-level FastAPI 'app' object."""
        from svc_machine import service  # noqa: PLC0415

        assert hasattr(service, "app"), "service.py must define a module-level 'app'"
        assert isinstance(service.app, FastAPI)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a TestClient for the machine service."""
    app = create_machine_app(workspace_dir=tmp_path)
    return TestClient(app)


class TestExecEndpoint:
    """Tests for POST /exec endpoint."""

    def test_echo(self, client: TestClient) -> None:
        """POST /exec executes a command and returns stdout/stderr/exit_code."""
        response = client.post(
            "/exec",
            json={"command": "echo hello_world"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "hello_world" in data["stdout"]
        assert data["exit_code"] == 0
        assert "stderr" in data

    def test_missing_command(self, client: TestClient) -> None:
        """POST /exec returns 422 when command field is missing."""
        response = client.post("/exec", json={})
        assert response.status_code == 422

    def test_working_dir_outside_workspace_returns_422(
        self, client: TestClient
    ) -> None:
        """POST /exec returns 422 with error detail when working_dir escapes workspace."""
        response = client.post(
            "/exec",
            json={"command": "echo hi", "working_dir": "/etc"},
        )
        assert response.status_code == 422
        assert "outside workspace" in response.json()["detail"]


class TestHealthz:
    """Tests for GET /healthz endpoint."""

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestDescribe:
    """Tests for GET /describe endpoint."""

    def test_describe(self, client: TestClient) -> None:
        """GET /describe returns service name and version."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-machine"
        assert "version" in data


class TestFileReadEndpoint:
    """Tests for POST /files/read endpoint."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Provide the workspace directory."""
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        """Create a TestClient with a known workspace directory."""
        app = create_machine_app(workspace_dir=workspace)
        return TestClient(app)

    def test_read_file(self, client: TestClient, workspace: Path) -> None:
        """POST /files/read returns content and total_lines for an existing file."""
        (workspace / "hello.txt").write_text("line1\nline2\nline3\n")
        response = client.post("/files/read", json={"path": "hello.txt"})
        assert response.status_code == 200
        data = response.json()
        assert "line1" in data["content"]
        assert data["total_lines"] == 3

    def test_read_missing_file(self, client: TestClient) -> None:
        """POST /files/read returns 404 when file does not exist."""
        response = client.post("/files/read", json={"path": "missing.txt"})
        assert response.status_code == 404


class TestFileWriteEndpoint:
    """Tests for POST /files/write endpoint."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Provide the workspace directory."""
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        """Create a TestClient with a known workspace directory."""
        app = create_machine_app(workspace_dir=workspace)
        return TestClient(app)

    def test_write_file(self, client: TestClient, workspace: Path) -> None:
        """POST /files/write creates file and returns success."""
        response = client.post(
            "/files/write",
            json={"path": "output.txt", "content": "written content\n"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert (workspace / "output.txt").read_text() == "written content\n"


class TestFileEditEndpoint:
    """Tests for POST /files/edit endpoint."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Provide the workspace directory."""
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        """Create a TestClient with a known workspace directory."""
        app = create_machine_app(workspace_dir=workspace)
        return TestClient(app)

    def test_edit_file(self, client: TestClient, workspace: Path) -> None:
        """POST /files/edit replaces a string and returns replacements_made=1."""
        (workspace / "edit_me.txt").write_text("hello world\n")
        response = client.post(
            "/files/edit",
            json={"path": "edit_me.txt", "old_string": "world", "new_string": "earth"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["replacements_made"] == 1
        assert (workspace / "edit_me.txt").read_text() == "hello earth\n"
