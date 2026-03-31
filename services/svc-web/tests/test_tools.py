"""Tests for web tools (WebSearchTool, WebFetchTool)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from svc_web.tools import WebFetchTool, WebSearchTool


class TestWebSearchTool:
    """Tests for WebSearchTool.execute."""

    @pytest.fixture
    def tool(self) -> WebSearchTool:
        """Create a WebSearchTool instance."""
        return WebSearchTool()

    async def test_execute_missing_query(self, tool: WebSearchTool) -> None:
        """execute() with no query returns success=False with descriptive error."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "query" in result.error["message"].lower()

    async def test_execute_returns_results(self, tool: WebSearchTool) -> None:
        """execute() with a query returns success=True with results and count."""
        mock_results = [
            {
                "title": "Result 1",
                "url": "https://example.com/1",
                "snippet": "Snippet 1",
            },
            {
                "title": "Result 2",
                "url": "https://example.com/2",
                "snippet": "Snippet 2",
            },
        ]
        with patch.object(
            tool, "_real_search", new=AsyncMock(return_value=mock_results)
        ):
            result = await tool.execute({"query": "test query"})

        assert result.success is True
        assert result.output is not None
        assert result.output["query"] == "test query"
        assert result.output["results"] == mock_results
        assert result.output["count"] == 2

    async def test_execute_search_error(self, tool: WebSearchTool) -> None:
        """execute() returns success=False when search raises an exception."""
        with patch.object(
            tool,
            "_real_search",
            new=AsyncMock(side_effect=Exception("Search failed")),
        ):
            result = await tool.execute({"query": "test query"})

        assert result.success is False
        assert result.error is not None
        assert "Search failed" in result.error["message"]


class TestWebFetchTool:
    """Tests for WebFetchTool.execute."""

    @pytest.fixture
    def tool(self) -> WebFetchTool:
        """Create a WebFetchTool instance."""
        return WebFetchTool()

    async def test_execute_missing_url(self, tool: WebFetchTool) -> None:
        """execute() with no url returns success=False with descriptive error."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "url" in result.error["message"].lower()

    async def test_execute_blocked_localhost(self, tool: WebFetchTool) -> None:
        """execute() with a localhost URL returns success=False."""
        result = await tool.execute({"url": "http://localhost:8080/api"})
        assert result.success is False
        assert result.error is not None
        assert (
            "blocked" in result.error["message"].lower()
            or "invalid" in result.error["message"].lower()
        )

    async def test_execute_invalid_scheme_ftp(self, tool: WebFetchTool) -> None:
        """execute() with ftp:// URL returns success=False (only http/https allowed)."""
        result = await tool.execute({"url": "ftp://example.com/file.txt"})
        assert result.success is False
        assert result.error is not None
        assert (
            "blocked" in result.error["message"].lower()
            or "invalid" in result.error["message"].lower()
        )
