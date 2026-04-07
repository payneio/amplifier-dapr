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
    """TestClient wrapping create_machine_app(workspace)."""
    app = create_machine_app(workspace)
    return TestClient(app)


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


class TestMachineFileOperations:
    """Test all machine service file and exec operations end-to-end."""

    def test_exec(self, machine_client: TestClient) -> None:
        """POST /exec runs a shell command and returns stdout."""
        response = machine_client.post(
            "/exec", json={"command": "echo hello from machine"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "hello from machine" in data["stdout"]
        assert data["exit_code"] == 0

    def test_file_read(self, machine_client: TestClient) -> None:
        """POST /files/read returns the content of hello.txt."""
        response = machine_client.post("/files/read", json={"path": "hello.txt"})
        assert response.status_code == 200
        data = response.json()
        assert "Hello, World!" in data["content"]

    def test_file_write_and_read_back(
        self, machine_client: TestClient, workspace: Path
    ) -> None:
        """POST /files/write writes a file; reading it back returns the content."""
        response = machine_client.post(
            "/files/write",
            json={"path": "output.txt", "content": "written by test\n"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert (workspace / "output.txt").read_text() == "written by test\n"

        # Read it back via the API
        response = machine_client.post("/files/read", json={"path": "output.txt"})
        assert response.status_code == 200
        assert "written by test" in response.json()["content"]

    def test_file_list(self, machine_client: TestClient) -> None:
        """POST /files/list returns entries including hello.txt and src."""
        response = machine_client.post("/files/list", json={"path": "."})
        assert response.status_code == 200
        entry_names = [e["name"] for e in response.json()["entries"]]
        assert "hello.txt" in entry_names
        assert "src" in entry_names

    def test_file_glob(self, machine_client: TestClient) -> None:
        """POST /files/glob returns matches for **/*.py including src/main.py."""
        response = machine_client.post(
            "/files/glob", json={"pattern": "**/*.py", "path": "."}
        )
        assert response.status_code == 200
        matches = response.json()["matches"]
        assert any("main.py" in m for m in matches)

    def test_file_grep(self, machine_client: TestClient) -> None:
        """POST /files/grep finds 'print' in src/main.py (files_with_matches mode)."""
        response = machine_client.post(
            "/files/grep", json={"pattern": "print", "path": "src/main.py"}
        )
        assert response.status_code == 200
        grep_matches = response.json()["matches"]
        assert len(grep_matches) >= 1
        # Default output_mode is files_with_matches: matches are file path strings
        assert any("main.py" in m for m in grep_matches)

    def test_file_edit(self, machine_client: TestClient, workspace: Path) -> None:
        """POST /files/edit replaces a string in hello.txt."""
        response = machine_client.post(
            "/files/edit",
            json={
                "path": "hello.txt",
                "old_string": "World",
                "new_string": "Microservices",
            },
        )
        assert response.status_code == 200
        edit_data = response.json()
        assert edit_data["success"] is True
        assert edit_data["replacements_made"] >= 1
        assert "Microservices" in (workspace / "hello.txt").read_text()
