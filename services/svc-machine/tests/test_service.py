"""Tests for svc-machine FastAPI service endpoints."""

import os
from collections.abc import Generator
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

    def test_describe_exposes_all_machine_tools(self, client: TestClient) -> None:
        """GET /describe returns a tools array with all six machine tool names."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data, "Response must include a 'tools' key"
        assert isinstance(data["tools"], list), "'tools' must be a list"
        tool_names = {tool["name"] for tool in data["tools"]}
        expected_names = {
            "bash",
            "read_file",
            "write_file",
            "edit_file",
            "grep",
            "glob",
        }
        assert tool_names == expected_names, (
            f"Expected tool names {expected_names}, got {tool_names}"
        )


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


@pytest.fixture
def safety_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    """Create a TestClient with SAFETY_PROFILE=strict env var, yields then cleans up."""
    prev = os.environ.get("SAFETY_PROFILE")
    os.environ["SAFETY_PROFILE"] = "strict"
    try:
        app = create_machine_app(workspace_dir=tmp_path)
        yield TestClient(app)
    finally:
        if prev is None:
            os.environ.pop("SAFETY_PROFILE", None)
        else:
            os.environ["SAFETY_PROFILE"] = prev


class TestExecSafety:
    """Tests for safety validation on POST /exec."""

    def test_blocked_command_returns_403(self, safety_client: TestClient) -> None:
        """POST /exec with rm -rf / returns 403 with denied=True and reason present."""
        response = safety_client.post("/exec", json={"command": "rm -rf /"})
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["denied"] is True
        assert "reason" in detail

    def test_allowed_command_passes(self, safety_client: TestClient) -> None:
        """POST /exec with echo safe returns 200 with 'safe' in stdout."""
        response = safety_client.post("/exec", json={"command": "echo safe"})
        assert response.status_code == 200
        assert "safe" in response.json()["stdout"]


class TestExecTruncation:
    """Tests for output truncation on POST /exec."""

    def test_large_output_is_truncated(self, client: TestClient) -> None:
        """POST /exec with 200k-char output returns 200 with truncated=True."""
        response = client.post(
            "/exec",
            json={"command": "python3 -c \"print('x' * 200_000)\"", "timeout": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["truncated"] is True


class TestExecBackground:
    """Tests for background execution on POST /exec."""

    def test_background_returns_pid(self, client: TestClient) -> None:
        """POST /exec with run_in_background=True returns int pid and status 'running'."""
        response = client.post(
            "/exec",
            json={"command": "sleep 60", "run_in_background": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["pid"], int)
        assert data["status"] == "running"


class TestInstanceLifecycle:
    """Tests for instance lifecycle endpoints: POST/DELETE /instances."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Provide the workspace directory."""
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        """Create a TestClient with a known workspace directory."""
        app = create_machine_app(workspace_dir=workspace)
        return TestClient(app)

    def test_create_instance_returns_instance_id(
        self, client: TestClient, workspace: Path
    ) -> None:
        """POST /instances returns 200 with instance_id string."""
        response = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        assert response.status_code == 200
        data = response.json()
        assert "instance_id" in data
        assert isinstance(data["instance_id"], str)
        assert len(data["instance_id"]) > 0

    def test_delete_instance_returns_200(
        self, client: TestClient, workspace: Path
    ) -> None:
        """DELETE /instances/{id} returns 200 after creating instance."""
        create_resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        assert create_resp.status_code == 200
        instance_id = create_resp.json()["instance_id"]

        delete_resp = client.delete(f"/instances/{instance_id}")
        assert delete_resp.status_code == 200

    def test_delete_nonexistent_instance_returns_404(self, client: TestClient) -> None:
        """DELETE /instances/nonexistent returns 404."""
        response = client.delete("/instances/nonexistent_id_xyz")
        assert response.status_code == 404


class TestInstanceExec:
    """Tests for POST /instances/{id}/exec endpoint."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Provide the workspace directory."""
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        """Create a TestClient with a known workspace directory."""
        app = create_machine_app(workspace_dir=workspace)
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, workspace: Path) -> str:
        """Create an instance and return its ID."""
        response = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        assert response.status_code == 200
        return response.json()["instance_id"]

    def test_exec_on_instance_returns_stdout(
        self, client: TestClient, instance_id: str
    ) -> None:
        """POST /instances/{id}/exec runs command and returns stdout."""
        response = client.post(
            f"/instances/{instance_id}/exec",
            json={"command": "echo hello_instance"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "hello_instance" in data["stdout"]
        assert data["exit_code"] == 0

    def test_exec_on_nonexistent_instance_returns_404(self, client: TestClient) -> None:
        """POST /instances/nonexistent/exec returns 404."""
        response = client.post(
            "/instances/nonexistent_id_xyz/exec",
            json={"command": "echo hi"},
        )
        assert response.status_code == 404


class TestInstanceFileOps:
    """Tests for instance-scoped file operation endpoints."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Provide the workspace directory."""
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        """Create a TestClient with a known workspace directory."""
        app = create_machine_app(workspace_dir=workspace)
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, workspace: Path) -> str:
        """Create an instance and return its ID."""
        response = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        assert response.status_code == 200
        return response.json()["instance_id"]

    def test_write_then_read_file(self, client: TestClient, instance_id: str) -> None:
        """Write then read file via instance-scoped endpoints works."""
        write_resp = client.post(
            f"/instances/{instance_id}/files/write",
            json={"path": "test_file.txt", "content": "instance file content\n"},
        )
        assert write_resp.status_code == 200
        assert write_resp.json()["success"] is True

        read_resp = client.post(
            f"/instances/{instance_id}/files/read",
            json={"path": "test_file.txt"},
        )
        assert read_resp.status_code == 200
        data = read_resp.json()
        assert "instance file content" in data["content"]

    def test_edit_file_returns_replacements_made_1(
        self, client: TestClient, instance_id: str
    ) -> None:
        """Edit file via instance-scoped endpoint returns replacements_made: 1."""
        # Write a file first
        client.post(
            f"/instances/{instance_id}/files/write",
            json={"path": "edit_test.txt", "content": "hello world\n"},
        )

        edit_resp = client.post(
            f"/instances/{instance_id}/files/edit",
            json={
                "path": "edit_test.txt",
                "old_string": "world",
                "new_string": "earth",
            },
        )
        assert edit_resp.status_code == 200
        data = edit_resp.json()
        assert data["replacements_made"] == 1
