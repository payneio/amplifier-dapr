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

    async def test_execute_success(self, tool: ReadFileTool) -> None:
        """execute() calls machine /files/read and returns success=True with formatted content."""
        mock_result: dict[str, Any] = {"content": "hello world\n", "total_lines": 1}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"file_path": "/tmp/test.txt"})

        assert result.success is True
        assert result.output is not None
        content = result.output["content"]
        assert "hello world" in content
        assert "1\t" in content  # content formatted with line numbers

    async def test_execute_missing_file_path(self, tool: ReadFileTool) -> None:
        """execute() with no file_path returns success=False with descriptive error."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "file_path" in result.error["message"]

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

    async def test_execute_success(self, tool: WriteFileTool) -> None:
        """execute() calls machine /files/write and returns success=True."""
        mock_result: dict[str, Any] = {"success": True}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute(
                {"file_path": "/tmp/test.txt", "content": "hello"}
            )

        assert result.success is True

    async def test_execute_missing_file_path(self, tool: WriteFileTool) -> None:
        """execute() with no file_path returns success=False."""
        result = await tool.execute({"content": "hello"})
        assert result.success is False
        assert result.error is not None
        assert "file_path" in result.error["message"]

    async def test_execute_missing_content(self, tool: WriteFileTool) -> None:
        """execute() with no content returns success=False."""
        result = await tool.execute({"file_path": "/tmp/test.txt"})
        assert result.success is False
        assert result.error is not None
        assert "content" in result.error["message"]

    async def test_execute_http_error(self, tool: WriteFileTool) -> None:
        """execute() returns success=False when machine returns HTTP error."""
        exc = httpx.HTTPStatusError(
            "Internal Server Error",
            request=httpx.Request("POST", "http://fake-machine:8080/files/write"),
            response=httpx.Response(500),
        )
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute(
                {"file_path": "/tmp/test.txt", "content": "hello"}
            )

        assert result.success is False
        assert result.error is not None
        assert "500" in result.error["message"]

    async def test_execute_unreachable_machine(self, tool: WriteFileTool) -> None:
        """execute() returns success=False when machine is unreachable."""
        exc = httpx.ConnectError("Connection refused")
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute(
                {"file_path": "/tmp/test.txt", "content": "hello"}
            )

        assert result.success is False
        assert result.error is not None
        assert "unreachable" in result.error["message"]


class TestEditFileTool:
    """Tests for EditFileTool.execute."""

    @pytest.fixture
    def tool(self) -> EditFileTool:
        """Create an EditFileTool pointed at a fake machine URL."""
        return EditFileTool(machine_base_url="http://fake-machine:8080")

    async def test_execute_success(self, tool: EditFileTool) -> None:
        """execute() calls machine /files/edit and returns success=True."""
        mock_result: dict[str, Any] = {"success": True, "replacements_made": 1}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute(
                {
                    "file_path": "/tmp/test.txt",
                    "old_string": "hello",
                    "new_string": "world",
                }
            )

        assert result.success is True

    async def test_execute_missing_old_string(self, tool: EditFileTool) -> None:
        """execute() with missing old_string returns success=False with descriptive error."""
        result = await tool.execute({"file_path": "/tmp/test.txt"})
        assert result.success is False
        assert result.error is not None
        assert "old_string" in result.error["message"]

    async def test_execute_missing_new_string(self, tool: EditFileTool) -> None:
        """execute() with missing new_string returns success=False with descriptive error."""
        result = await tool.execute(
            {"file_path": "/tmp/test.txt", "old_string": "hello"}
        )
        assert result.success is False
        assert result.error is not None
        assert "new_string" in result.error["message"]

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

    async def test_execute_http_error(self, tool: EditFileTool) -> None:
        """execute() returns success=False when machine returns HTTP error."""
        exc = httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("POST", "http://fake-machine:8080/files/edit"),
            response=httpx.Response(404),
        )
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute(
                {
                    "file_path": "/tmp/test.txt",
                    "old_string": "hello",
                    "new_string": "world",
                }
            )

        assert result.success is False
        assert result.error is not None
        assert "404" in result.error["message"]

    async def test_execute_unreachable_machine(self, tool: EditFileTool) -> None:
        """execute() returns success=False when machine is unreachable."""
        exc = httpx.ConnectError("Connection refused")
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute(
                {
                    "file_path": "/tmp/test.txt",
                    "old_string": "hello",
                    "new_string": "world",
                }
            )

        assert result.success is False
        assert result.error is not None
        assert "unreachable" in result.error["message"]


class TestReadFileToolDirectoryListing:
    """Tests for ReadFileTool.execute handling directory listing responses."""

    @pytest.fixture
    def tool(self) -> ReadFileTool:
        """Create a ReadFileTool pointed at a fake machine URL."""
        return ReadFileTool(machine_base_url="http://fake-machine:8080")

    async def test_directory_returns_listing(self, tool: ReadFileTool) -> None:
        """execute() formats directory entries with DIR/FILE labels in content."""
        mock_result: dict[str, Any] = {
            "entries": [
                {"name": "src", "type": "dir"},
                {"name": "main.py", "type": "file", "size": 100},
            ]
        }
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"file_path": "some_dir/"})

        assert result.success is True
        assert result.output is not None
        content = result.output["content"]
        assert "DIR" in content
        assert "FILE" in content
        assert "src" in content
        assert "main.py" in content


class TestReadFileToolLineFormatting:
    """Tests for ReadFileTool.execute applying cat -n style line formatting."""

    @pytest.fixture
    def tool(self) -> ReadFileTool:
        """Create a ReadFileTool pointed at a fake machine URL."""
        return ReadFileTool(machine_base_url="http://fake-machine:8080")

    async def test_output_has_line_numbers(self, tool: ReadFileTool) -> None:
        """execute() adds line numbers in cat -n format (N<tab>content)."""
        mock_result: dict[str, Any] = {
            "content": "line1\nline2\nline3\n",
            "total_lines": 3,
        }
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"file_path": "some_file.txt"})

        assert result.success is True
        assert result.output is not None
        content = result.output["content"]
        assert "1\t" in content
        assert "line1" in content

    async def test_long_lines_truncated(self, tool: ReadFileTool) -> None:
        """execute() truncates lines longer than 2000 chars."""
        mock_result: dict[str, Any] = {
            "content": "x" * 3000 + "\n",
            "total_lines": 1,
        }
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"file_path": "some_file.txt"})

        assert result.success is True
        assert result.output is not None
        first_line = result.output["content"].splitlines()[0]
        assert len(first_line) < 2200
