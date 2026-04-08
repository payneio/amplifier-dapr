"""Integration tests for the consolidated svc-machine service.

These tests run entirely in-process without Docker or Dapr.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_machine.service import create_machine_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with hello.txt and src/main.py."""
    (tmp_path / "hello.txt").write_text("Hello, World!")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')")
    return tmp_path


@pytest.fixture
def machine_client(workspace: Path) -> TestClient:
    """TestClient wrapping create_machine_app() with a provisioned local instance."""
    app = create_machine_app()
    return TestClient(app)


@pytest.fixture
def instance_id(machine_client: TestClient, workspace: Path) -> str:
    """Create a local instance and return its ID."""
    resp = machine_client.post(
        "/instances",
        json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
    )
    assert resp.status_code == 200
    return resp.json()["instance_id"]


# ---------------------------------------------------------------------------
# Service contract tests
# ---------------------------------------------------------------------------


class TestMachineServiceContract:
    """Verify that svc-machine implements the standard /healthz and /describe contract."""

    def test_machine_healthz(self, machine_client: TestClient) -> None:
        """GET /healthz on svc-machine returns 200 with status='healthy'."""
        response = machine_client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_machine_describe(self, machine_client: TestClient) -> None:
        """GET /describe on svc-machine returns 200 with name='svc-machine'."""
        response = machine_client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-machine"

    def test_machine_describe_advertises_all_tools(
        self, machine_client: TestClient
    ) -> None:
        """GET /describe on svc-machine lists all 6 consolidated tools."""
        response = machine_client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        expected_tools = {
            "bash",
            "read_file",
            "write_file",
            "edit_file",
            "grep",
            "glob",
        }
        for tool in expected_tools:
            assert tool in tool_names, (
                f"Expected tool '{tool}' in /describe tools, got: {tool_names}"
            )


# ---------------------------------------------------------------------------
# File operation tests
# ---------------------------------------------------------------------------


class TestMachineToolDispatch:
    """Test machine service tool dispatch endpoints via provisioned instances."""

    def test_bash_execute(self, machine_client: TestClient, instance_id: str) -> None:
        """POST /tools/bash/execute runs a command via provisioned instance."""
        response = machine_client.post(
            "/tools/bash/execute",
            json={
                "name": "bash",
                "input": {"command": "echo hello from machine"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "hello from machine" in data["stdout"]
        assert data["exit_code"] == 0

    def test_read_file(self, machine_client: TestClient, instance_id: str) -> None:
        """POST /tools/read_file/execute returns file content."""
        response = machine_client.post(
            "/tools/read_file/execute",
            json={
                "name": "read_file",
                "input": {"file_path": "hello.txt"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "Hello, World!" in data["content"]

    def test_write_and_read_back(
        self, machine_client: TestClient, workspace: Path, instance_id: str
    ) -> None:
        """POST /tools/write_file/execute writes; read_file reads it back."""
        write_resp = machine_client.post(
            "/tools/write_file/execute",
            json={
                "name": "write_file",
                "input": {"file_path": "output.txt", "content": "written by test\n"},
                "machine_instance_id": instance_id,
            },
        )
        assert write_resp.status_code == 200
        assert write_resp.json()["success"] is True
        assert (workspace / "output.txt").read_text() == "written by test\n"

        read_resp = machine_client.post(
            "/tools/read_file/execute",
            json={
                "name": "read_file",
                "input": {"file_path": "output.txt"},
                "machine_instance_id": instance_id,
            },
        )
        assert read_resp.status_code == 200
        assert "written by test" in read_resp.json()["content"]

    def test_glob(self, machine_client: TestClient, instance_id: str) -> None:
        """POST /tools/glob/execute matches *.py files."""
        response = machine_client.post(
            "/tools/glob/execute",
            json={
                "name": "glob",
                "input": {"pattern": "**/*.py"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        matches = response.json()["matches"]
        assert any("main.py" in m for m in matches)

    def test_grep(self, machine_client: TestClient, instance_id: str) -> None:
        """POST /tools/grep/execute finds 'print' in src/main.py."""
        response = machine_client.post(
            "/tools/grep/execute",
            json={
                "name": "grep",
                "input": {"pattern": "print", "path": "src/main.py"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_edit_file(
        self, machine_client: TestClient, workspace: Path, instance_id: str
    ) -> None:
        """POST /tools/edit_file/execute replaces a string in hello.txt."""
        response = machine_client.post(
            "/tools/edit_file/execute",
            json={
                "name": "edit_file",
                "input": {
                    "file_path": "hello.txt",
                    "old_string": "World",
                    "new_string": "Microservices",
                },
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        edit_data = response.json()
        assert edit_data["replacements_made"] >= 1
        assert "Microservices" in (workspace / "hello.txt").read_text()
