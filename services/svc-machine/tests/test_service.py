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
    app = create_machine_app()
    return TestClient(app)


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


class TestInstanceLifecycle:
    """Tests for instance lifecycle endpoints: POST/DELETE /instances."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Provide the workspace directory."""
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        """Create a TestClient with a known workspace directory."""
        app = create_machine_app()
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
        app = create_machine_app()
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
        app = create_machine_app()
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


class TestToolDispatchBash:
    """Tests for POST /tools/bash/execute — standard orchestrator dispatch route."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient."""
        app = create_machine_app()
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, tmp_path: Path) -> str:
        """Create a local instance and return its ID."""
        resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(tmp_path)}},
        )
        assert resp.status_code == 200
        return resp.json()["instance_id"]

    def test_bash_execute_runs_command(
        self, client: TestClient, instance_id: str
    ) -> None:
        """POST /tools/bash/execute accepts orchestrator payload and runs the command."""
        response = client.post(
            "/tools/bash/execute",
            json={
                "name": "bash",
                "input": {"command": "echo dispatch_ok"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "dispatch_ok" in data["stdout"]
        assert data["exit_code"] == 0

    def test_bash_execute_missing_command_returns_422(
        self, client: TestClient, instance_id: str
    ) -> None:
        """POST /tools/bash/execute with empty input returns 422."""
        response = client.post(
            "/tools/bash/execute",
            json={"name": "bash", "input": {}, "machine_instance_id": instance_id},
        )
        assert response.status_code == 422

    def test_bash_execute_without_instance_returns_400(
        self, client: TestClient
    ) -> None:
        """POST /tools/bash/execute without machine_instance_id returns 400."""
        response = client.post(
            "/tools/bash/execute",
            json={"name": "bash", "input": {"command": "echo nope"}},
        )
        assert response.status_code == 400
        assert "machine_instance_id" in response.json()["detail"].lower()

    def test_bash_execute_with_unknown_instance_returns_404(
        self, client: TestClient
    ) -> None:
        """POST /tools/bash/execute with unknown machine_instance_id returns 404."""
        response = client.post(
            "/tools/bash/execute",
            json={
                "name": "bash",
                "input": {"command": "echo fallback"},
                "machine_instance_id": "nonexistent-instance-id",
            },
        )
        assert response.status_code == 404


class TestToolDispatchReadFile:
    """Tests for POST /tools/read_file/execute — standard orchestrator dispatch route."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        """Provide the workspace directory."""
        return tmp_path

    @pytest.fixture
    def client(self) -> TestClient:
        app = create_machine_app()
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, workspace: Path) -> str:
        resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        assert resp.status_code == 200
        return resp.json()["instance_id"]

    def test_read_file_execute_returns_content(
        self, client: TestClient, workspace: Path, instance_id: str
    ) -> None:
        """POST /tools/read_file/execute returns file content for existing file."""
        (workspace / "test.txt").write_text("tool dispatch content\n")
        response = client.post(
            "/tools/read_file/execute",
            json={
                "name": "read_file",
                "input": {"file_path": "test.txt"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "tool dispatch content" in data["content"]

    def test_read_file_execute_missing_path_returns_422(
        self, client: TestClient, instance_id: str
    ) -> None:
        """POST /tools/read_file/execute with no file_path returns 422."""
        response = client.post(
            "/tools/read_file/execute",
            json={
                "name": "read_file",
                "input": {},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 422

    def test_read_file_execute_directory_returns_entries(
        self, client: TestClient, workspace: Path, instance_id: str
    ) -> None:
        """POST /tools/read_file/execute on a directory returns entries list."""
        (workspace / "subdir").mkdir()
        (workspace / "subdir" / "a.txt").write_text("a")
        response = client.post(
            "/tools/read_file/execute",
            json={
                "name": "read_file",
                "input": {"file_path": "subdir"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data


class TestToolDispatchWriteFile:
    """Tests for POST /tools/write_file/execute — standard orchestrator dispatch route."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture
    def client(self) -> TestClient:
        app = create_machine_app()
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, workspace: Path) -> str:
        resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        assert resp.status_code == 200
        return resp.json()["instance_id"]

    def test_write_file_execute_creates_file(
        self, client: TestClient, workspace: Path, instance_id: str
    ) -> None:
        """POST /tools/write_file/execute creates file and returns success."""
        response = client.post(
            "/tools/write_file/execute",
            json={
                "name": "write_file",
                "input": {"file_path": "created.txt", "content": "dispatch write\n"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert (workspace / "created.txt").read_text() == "dispatch write\n"

    def test_write_file_execute_missing_fields_returns_422(
        self, client: TestClient, instance_id: str
    ) -> None:
        """POST /tools/write_file/execute with no file_path returns 422."""
        response = client.post(
            "/tools/write_file/execute",
            json={
                "name": "write_file",
                "input": {},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 422


class TestToolDispatchEditFile:
    """Tests for POST /tools/edit_file/execute — standard orchestrator dispatch route."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture
    def client(self) -> TestClient:
        app = create_machine_app()
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, workspace: Path) -> str:
        resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        assert resp.status_code == 200
        return resp.json()["instance_id"]

    def test_edit_file_execute_replaces_string(
        self, client: TestClient, workspace: Path, instance_id: str
    ) -> None:
        """POST /tools/edit_file/execute replaces a string in a file."""
        (workspace / "source.txt").write_text("hello world\n")
        response = client.post(
            "/tools/edit_file/execute",
            json={
                "name": "edit_file",
                "input": {
                    "file_path": "source.txt",
                    "old_string": "world",
                    "new_string": "dispatch",
                },
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["replacements_made"] == 1
        assert (workspace / "source.txt").read_text() == "hello dispatch\n"

    def test_edit_file_execute_missing_fields_returns_422(
        self, client: TestClient, instance_id: str
    ) -> None:
        """POST /tools/edit_file/execute with missing required fields returns 422."""
        response = client.post(
            "/tools/edit_file/execute",
            json={
                "name": "edit_file",
                "input": {"file_path": "x.txt"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 422


class TestToolDispatchGlob:
    """Tests for POST /tools/glob/execute — standard orchestrator dispatch route."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture
    def client(self) -> TestClient:
        app = create_machine_app()
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, workspace: Path) -> str:
        resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        assert resp.status_code == 200
        return resp.json()["instance_id"]

    def test_glob_execute_returns_matches(
        self, client: TestClient, workspace: Path, instance_id: str
    ) -> None:
        """POST /tools/glob/execute returns list of matching file paths."""
        (workspace / "file_a.py").write_text("# a")
        (workspace / "file_b.py").write_text("# b")
        response = client.post(
            "/tools/glob/execute",
            json={
                "name": "glob",
                "input": {"pattern": "*.py"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "matches" in data
        assert len(data["matches"]) == 2

    def test_glob_execute_missing_pattern_returns_422(
        self, client: TestClient, instance_id: str
    ) -> None:
        """POST /tools/glob/execute with no pattern returns 422."""
        response = client.post(
            "/tools/glob/execute",
            json={
                "name": "glob",
                "input": {},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 422


class TestToolDispatchGrep:
    """Tests for POST /tools/grep/execute — standard orchestrator dispatch route."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture
    def client(self) -> TestClient:
        app = create_machine_app()
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, workspace: Path) -> str:
        resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        assert resp.status_code == 200
        return resp.json()["instance_id"]

    def test_grep_execute_returns_results(
        self, client: TestClient, workspace: Path, instance_id: str
    ) -> None:
        """POST /tools/grep/execute returns files containing pattern."""
        (workspace / "match.txt").write_text("the target phrase\n")
        (workspace / "no_match.txt").write_text("nothing here\n")
        response = client.post(
            "/tools/grep/execute",
            json={
                "name": "grep",
                "input": {"pattern": "target phrase"},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_grep_execute_missing_pattern_returns_422(
        self, client: TestClient, instance_id: str
    ) -> None:
        """POST /tools/grep/execute with no pattern returns 422."""
        response = client.post(
            "/tools/grep/execute",
            json={
                "name": "grep",
                "input": {},
                "machine_instance_id": instance_id,
            },
        )
        assert response.status_code == 422
