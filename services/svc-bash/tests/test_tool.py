"""Tests for BashTool and the bash app."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from svc_bash.app import create_bash_app
from svc_bash.tool import BashTool


class TestBashTool:
    """Tests for BashTool.execute."""

    @pytest.fixture
    def tool(self) -> BashTool:
        """Create a BashTool pointed at a fake machine URL."""
        return BashTool(machine_base_url="http://fake-machine:8080")

    @pytest.mark.asyncio
    async def test_execute_calls_machine_service(self, tool: BashTool) -> None:
        """execute() calls _call_machine_exec and returns success=True with stdout."""
        mock_result: dict[str, Any] = {
            "exit_code": 0,
            "stdout": "hello world",
            "stderr": "",
        }
        with patch.object(
            tool, "_call_machine_exec", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"command": "echo hello world"})

        assert result.success is True
        assert result.output is not None
        assert result.output["stdout"] == "hello world"
        assert result.output["returncode"] == 0

    @pytest.mark.asyncio
    async def test_execute_missing_command(self, tool: BashTool) -> None:
        """execute() with empty input returns success=False."""
        result = await tool.execute({})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_machine_failure(self, tool: BashTool) -> None:
        """execute() returns success=False when exit_code is non-zero."""
        mock_result: dict[str, Any] = {
            "exit_code": 127,
            "stdout": "",
            "stderr": "command not found",
        }
        with patch.object(
            tool, "_call_machine_exec", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"command": "nonexistent_command"})

        assert result.success is False
        assert result.output is not None
        assert result.output["returncode"] == 127


class TestBashApp:
    """Tests for the bash FastAPI application."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the bash app with a fake machine URL."""
        app = create_bash_app(machine_base_url="http://fake-machine:8080")
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe_includes_bash_tool(self, client: TestClient) -> None:
        """GET /describe returns tools list containing bash tool."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "bash" in tool_names
