"""Tests for search tools (GrepTool, GlobTool)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from svc_search.tools import GlobTool, GrepTool


class TestGrepTool:
    """Tests for GrepTool.execute."""

    @pytest.fixture
    def tool(self) -> GrepTool:
        """Create a GrepTool pointed at a fake machine URL."""
        return GrepTool(machine_base_url="http://fake-machine:8080")

    async def test_execute_success(self, tool: GrepTool) -> None:
        """execute() calls machine /files/grep and returns success=True with matches."""
        mock_result: dict[str, Any] = {"matches": ["src/foo.py:1:hello world"]}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"pattern": "hello"})

        assert result.success is True
        assert result.output is not None
        assert result.output["matches"] == ["src/foo.py:1:hello world"]

    async def test_execute_missing_pattern(self, tool: GrepTool) -> None:
        """execute() with no pattern returns success=False with descriptive error."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "pattern" in result.error["message"]

    async def test_execute_machine_error(self, tool: GrepTool) -> None:
        """execute() returns success=False when machine returns HTTP error."""
        exc = httpx.HTTPStatusError(
            "Internal Server Error",
            request=httpx.Request("POST", "http://fake-machine:8080/files/grep"),
            response=httpx.Response(500),
        )
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"pattern": "hello"})

        assert result.success is False
        assert result.error is not None
        assert "500" in result.error["message"]

    async def test_execute_unreachable_machine(self, tool: GrepTool) -> None:
        """execute() returns success=False with structured error when machine is unreachable."""
        exc = httpx.ConnectError("Connection refused")
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"pattern": "hello"})

        assert result.success is False
        assert result.error is not None
        assert "unreachable" in result.error["message"]

    async def test_execute_forwards_output_mode(self, tool: GrepTool) -> None:
        """execute() forwards output_mode parameter to the machine payload."""
        mock_result: dict[str, Any] = {"matches": [], "total_matches": 0}
        mock_call = AsyncMock(return_value=mock_result)
        with patch.object(tool, "_call_machine", new=mock_call):
            await tool.execute({"pattern": "hello", "output_mode": "content"})

        payload = mock_call.call_args[0][1]
        assert payload["output_mode"] == "content"

    async def test_execute_forwards_context_params(self, tool: GrepTool) -> None:
        """execute() forwards after_context, before_context, and case_insensitive to payload."""
        mock_result: dict[str, Any] = {"matches": [], "total_matches": 0}
        mock_call = AsyncMock(return_value=mock_result)
        with patch.object(tool, "_call_machine", new=mock_call):
            await tool.execute(
                {
                    "pattern": "hello",
                    "after_context": 3,
                    "before_context": 2,
                    "case_insensitive": True,
                }
            )

        payload = mock_call.call_args[0][1]
        assert payload["after_context"] == 3
        assert payload["before_context"] == 2
        assert payload["case_insensitive"] is True

    async def test_schema_has_full_params(self, tool: GrepTool) -> None:
        """GrepTool.input_schema contains all 14 expected parameter keys."""
        expected_keys = {
            "pattern",
            "path",
            "output_mode",
            "glob",
            "type",
            "after_context",
            "before_context",
            "context",
            "case_insensitive",
            "line_numbers",
            "head_limit",
            "offset",
            "include_ignored",
            "multiline",
        }
        actual_keys = set(tool.input_schema["properties"].keys())
        assert expected_keys == actual_keys


class TestGlobTool:
    """Tests for GlobTool.execute."""

    @pytest.fixture
    def tool(self) -> GlobTool:
        """Create a GlobTool pointed at a fake machine URL."""
        return GlobTool(machine_base_url="http://fake-machine:8080")

    async def test_execute_success(self, tool: GlobTool) -> None:
        """execute() calls machine /files/glob and returns success=True with matches."""
        mock_result: dict[str, Any] = {"matches": ["src/foo.py", "src/bar.py"]}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"pattern": "**/*.py"})

        assert result.success is True
        assert result.output is not None
        assert result.output["matches"] == ["src/foo.py", "src/bar.py"]

    async def test_execute_missing_pattern(self, tool: GlobTool) -> None:
        """execute() with no pattern returns success=False with descriptive error."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "pattern" in result.error["message"]

    async def test_execute_machine_error(self, tool: GlobTool) -> None:
        """execute() returns success=False when machine returns HTTP error."""
        exc = httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("POST", "http://fake-machine:8080/files/glob"),
            response=httpx.Response(404),
        )
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"pattern": "**/*.py"})

        assert result.success is False
        assert result.error is not None
        assert "404" in result.error["message"]

    async def test_execute_unreachable_machine(self, tool: GlobTool) -> None:
        """execute() returns success=False with structured error when machine is unreachable."""
        exc = httpx.ConnectError("Connection refused")
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"pattern": "**/*.py"})

        assert result.success is False
        assert result.error is not None
        assert "unreachable" in result.error["message"]

    async def test_execute_forwards_exclude(self, tool: GlobTool) -> None:
        """execute() forwards exclude list and type parameter to the machine payload."""
        mock_result: dict[str, Any] = {"matches": [], "total_files": 0}
        mock_call = AsyncMock(return_value=mock_result)
        with patch.object(tool, "_call_machine", new=mock_call):
            await tool.execute(
                {
                    "pattern": "**/*.py",
                    "exclude": ["*.test.py"],
                    "type": "file",
                }
            )

        payload = mock_call.call_args[0][1]
        assert payload["exclude"] == ["*.test.py"]
        assert payload["type"] == "file"

    async def test_schema_has_full_params(self, tool: GlobTool) -> None:
        """GlobTool.input_schema contains all 5 expected parameter keys."""
        expected_keys = {"pattern", "path", "exclude", "type", "include_ignored"}
        actual_keys = set(tool.input_schema["properties"].keys())
        assert expected_keys == actual_keys
