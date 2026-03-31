"""Tests for filesystem tools (ReadFileTool, WriteFileTool, EditFileTool)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from svc_filesystem.tools import EditFileTool, ReadFileTool, WriteFileTool


class TestReadFileTool:
    """Tests for ReadFileTool.execute."""

    @pytest.fixture
    def tool(self) -> ReadFileTool:
        """Create a ReadFileTool pointed at a fake machine URL."""
        return ReadFileTool(machine_base_url="http://fake-machine:8080")

    @pytest.mark.asyncio
    async def test_execute_success(self, tool: ReadFileTool) -> None:
        """execute() calls machine /files/read and returns success=True with content."""
        mock_result: dict[str, Any] = {"content": "hello world\n", "total_lines": 1}
        with patch.object(tool, "_call_machine", new=AsyncMock(return_value=mock_result)):
            result = await tool.execute({"file_path": "/tmp/test.txt"})

        assert result.success is True
        assert result.output is not None
        assert result.output["content"] == "hello world\n"

    @pytest.mark.asyncio
    async def test_execute_missing_file_path(self, tool: ReadFileTool) -> None:
        """execute() with no file_path returns success=False with descriptive error."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "file_path" in result.error["message"]

    @pytest.mark.asyncio
    async def test_execute_http_error(self, tool: ReadFileTool) -> None:
        """execute() returns success=False when machine returns HTTP error."""
        exc = httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("POST", "http://fake-machine:8080/files/read"),
            response=httpx.Response(404),
        )
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"file_path": "/tmp/test.txt"})

        assert result.success is False
        assert result.error is not None
        assert "404" in result.error["message"]

    @pytest.mark.asyncio
    async def test_execute_unreachable_machine(self, tool: ReadFileTool) -> None:
        """execute() returns success=False with structured error when machine is unreachable."""
        exc = httpx.ConnectError("Connection refused")
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"file_path": "/tmp/test.txt"})

        assert result.success is False
        assert result.error is not None
        assert "unreachable" in result.error["message"]


class TestWriteFileTool:
    """Tests for WriteFileTool.execute."""

    @pytest.fixture
    def tool(self) -> WriteFileTool:
        """Create a WriteFileTool pointed at a fake machine URL."""
        return WriteFileTool(machine_base_url="http://fake-machine:8080")

    @pytest.mark.asyncio
    async def test_execute_success(self, tool: WriteFileTool) -> None:
        """execute() calls machine /files/write and returns success=True."""
        mock_result: dict[str, Any] = {"success": True}
        with patch.object(tool, "_call_machine", new=AsyncMock(return_value=mock_result)):
            result = await tool.execute(
                {"file_path": "/tmp/test.txt", "content": "hello"}
            )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_missing_file_path(self, tool: WriteFileTool) -> None:
        """execute() with no file_path returns success=False."""
        result = await tool.execute({"content": "hello"})
        assert result.success is False
        assert result.error is not None
        assert "file_path" in result.error["message"]

    @pytest.mark.asyncio
    async def test_execute_missing_content(self, tool: WriteFileTool) -> None:
        """execute() with no content returns success=False."""
        result = await tool.execute({"file_path": "/tmp/test.txt"})
        assert result.success is False
        assert result.error is not None
        assert "content" in result.error["message"]


class TestEditFileTool:
    """Tests for EditFileTool.execute."""

    @pytest.fixture
    def tool(self) -> EditFileTool:
        """Create an EditFileTool pointed at a fake machine URL."""
        return EditFileTool(machine_base_url="http://fake-machine:8080")

    @pytest.mark.asyncio
    async def test_execute_success(self, tool: EditFileTool) -> None:
        """execute() calls machine /files/edit and returns success=True."""
        mock_result: dict[str, Any] = {"success": True, "replacements_made": 1}
        with patch.object(tool, "_call_machine", new=AsyncMock(return_value=mock_result)):
            result = await tool.execute(
                {
                    "file_path": "/tmp/test.txt",
                    "old_string": "hello",
                    "new_string": "world",
                }
            )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_missing_fields(self, tool: EditFileTool) -> None:
        """execute() with missing old_string/new_string returns success=False."""
        result = await tool.execute({"file_path": "/tmp/test.txt"})
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_same_strings(self, tool: EditFileTool) -> None:
        """execute() with old_string == new_string returns success=False."""
        result = await tool.execute(
            {
                "file_path": "/tmp/test.txt",
                "old_string": "hello",
                "new_string": "hello",
            }
        )
        assert result.success is False
        assert result.error is not None
