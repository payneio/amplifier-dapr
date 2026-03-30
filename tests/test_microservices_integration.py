"""Integration tests for the svc-bash -> svc-machine -> subprocess call chain.

These tests run entirely in-process without Docker or Dapr.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from svc_bash.app import create_bash_app
from svc_bash.tool import BashTool
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


class TestServiceContracts:
    """Verify that both services implement the standard /healthz and /describe contract."""

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

    def test_bash_healthz(self) -> None:
        """GET /healthz on svc-bash (with fake machine URL) returns 200."""
        app = create_bash_app(machine_base_url="http://fake-machine:8080")
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_bash_describe(self) -> None:
        """GET /describe on svc-bash returns name='svc-bash' and includes 'bash' tool."""
        app = create_bash_app(machine_base_url="http://fake-machine:8080")
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-bash"
        tool_names = [t["name"] for t in data["tools"]]
        assert "bash" in tool_names


# ---------------------------------------------------------------------------
# End-to-end execution tests
# ---------------------------------------------------------------------------


class TestEndToEndExecution:
    """End-to-end tests verifying the full svc-bash -> svc-machine -> subprocess chain."""

    async def test_bash_echo_via_machine(self, workspace: Path) -> None:
        """BashTool routes 'echo hello from bash' through the machine service in-process."""
        machine_app = create_machine_app(workspace)
        machine_client = TestClient(machine_app)

        tool = BashTool(machine_base_url="http://fake-machine:8080")

        async def _fake_call(command: str, timeout: int = 30) -> dict[str, Any]:
            resp = machine_client.post(
                "/exec", json={"command": command, "timeout": timeout}
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

        with patch.object(tool, "_call_machine_exec", new=_fake_call):
            result = await tool.execute({"command": "echo hello from bash"})

        assert result.success is True
        assert result.output is not None
        assert "hello from bash" in result.output["stdout"]

    async def test_bash_reads_workspace_file(self, workspace: Path) -> None:
        """BashTool can cat hello.txt via the machine service in-process."""
        machine_app = create_machine_app(workspace)
        machine_client = TestClient(machine_app)

        tool = BashTool(machine_base_url="http://fake-machine:8080")

        async def _fake_call(command: str, timeout: int = 30) -> dict[str, Any]:
            resp = machine_client.post(
                "/exec", json={"command": command, "timeout": timeout}
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]

        with patch.object(tool, "_call_machine_exec", new=_fake_call):
            result = await tool.execute({"command": "cat hello.txt"})

        assert result.success is True
        assert result.output is not None
        assert "Hello, World!" in result.output["stdout"]

    def test_machine_file_operations(
        self, machine_client: TestClient, workspace: Path
    ) -> None:
        """All machine file operations work correctly end-to-end."""
        # --- /files/read ---
        response = machine_client.post("/files/read", json={"path": "hello.txt"})
        assert response.status_code == 200
        read_data = response.json()
        assert "Hello, World!" in read_data["content"]

        # --- /files/write ---
        response = machine_client.post(
            "/files/write",
            json={"path": "output.txt", "content": "written by test\n"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert (workspace / "output.txt").read_text() == "written by test\n"

        # --- /files/list ---
        response = machine_client.post("/files/list", json={"path": "."})
        assert response.status_code == 200
        entry_names = [e["name"] for e in response.json()["entries"]]
        assert "hello.txt" in entry_names
        assert "src" in entry_names

        # --- /files/glob ---
        response = machine_client.post(
            "/files/glob", json={"pattern": "**/*.py", "path": "."}
        )
        assert response.status_code == 200
        matches = response.json()["matches"]
        assert any("main.py" in m for m in matches)

        # --- /files/grep ---
        response = machine_client.post(
            "/files/grep", json={"pattern": "print", "path": "src/main.py"}
        )
        assert response.status_code == 200
        grep_matches = response.json()["matches"]
        assert len(grep_matches) >= 1
        assert any("print" in m["content"] for m in grep_matches)

        # --- /files/edit ---
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
