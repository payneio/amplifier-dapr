"""Tests for svc-machine FastAPI service endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_machine.service import create_machine_app


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
