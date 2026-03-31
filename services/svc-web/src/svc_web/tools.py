"""WebSearchTool and WebFetchTool — web search and page fetch capabilities."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
from amplifier_service_sdk.models import ToolResult
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


class WebSearchTool:
    """Tool that searches the web using DuckDuckGo."""

    name: str = "web_search"
    description: str = "Search the web for information"

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query to execute"},
        },
        "required": ["query"],
    }

    def __init__(self) -> None:
        self.max_results = 5

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Execute web search.

        Args:
            params: Tool input dict. Must contain ``query``.

        Returns:
            ToolResult with success=True and output on success, or
            success=False with an error message on failure.
        """
        query = params.get("query")
        if not query:
            return ToolResult(
                success=False,
                error={"message": "query is required"},
            )

        try:
            results = await self._real_search(query)
            return ToolResult(
                success=True,
                output={"query": query, "results": results, "count": len(results)},
            )
        except Exception as e:
            logger.error(f"Search error: {e}")
            return ToolResult(
                success=False,
                error={"message": str(e)},
            )

    async def _real_search(self, query: str) -> list[dict[str, str]]:
        """Perform real web search using DuckDuckGo via run_in_executor."""

        def search_sync() -> list[dict[str, str]]:
            ddgs = DDGS()
            results: list[dict[str, str]] = []
            for r in ddgs.text(query, max_results=self.max_results):  # pyright: ignore[reportAttributeAccessIssue]
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                )
            return results

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, search_sync)


class WebFetchTool:
    """Tool that fetches and parses web pages with streaming support."""

    name: str = "web_fetch"
    description: str = (
        "Fetch content from a web URL.\n\n"
        "Content is limited to 200KB by default to avoid overwhelming responses.\n"
        "For larger content:\n"
        "- Use save_to_file parameter to save full content to a file\n"
        "- Use offset/limit parameters to paginate through large content\n\n"
        "Response includes:\n"
        "- truncated: boolean indicating if content was cut off\n"
        "- total_bytes: original content size (when available)\n"
        "- Use these to decide if you need the full content via save_to_file"
    )

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch content from",
            },
            "save_to_file": {
                "type": "string",
                "description": "Save full content to this file path instead of returning in response.",
            },
            "offset": {
                "type": "integer",
                "description": "Start reading from byte N (default 0). Use for pagination.",
                "default": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Max bytes to return (default 200KB). Use for pagination.",
                "default": 204800,
            },
        },
        "required": ["url"],
    }

    DEFAULT_LIMIT = 200 * 1024
    CHUNK_SIZE = 8192
    PREVIEW_SIZE = 1000

    def __init__(self) -> None:
        self.timeout = 10
        self.default_limit = self.DEFAULT_LIMIT
        self.blocked_domains: list[str] = [
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "192.168.",
            "10.",
            "172.16.",
        ]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Fetch content from URL with streaming and truncation support.

        Args:
            params: Tool input dict. Must contain ``url``.

        Returns:
            ToolResult with success=True and output on success, or
            success=False with an error message on failure.
        """
        url = params.get("url")
        if not url:
            return ToolResult(
                success=False,
                error={"message": "url is required"},
            )

        if not self._is_valid_url(url):
            return ToolResult(
                success=False,
                error={"message": f"Invalid or blocked URL: {url}"},
            )

        offset = params.get("offset", 0)
        limit = params.get("limit", self.default_limit)
        save_to_file = params.get("save_to_file")

        try:
            session = aiohttp.ClientSession()
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    headers={"User-Agent": "Amplifier/1.0"},
                ) as response:
                    if response.status != 200:
                        return ToolResult(
                            success=False,
                            error={
                                "message": f"HTTP {response.status}: {response.reason}"
                            },
                        )

                    content_length_header = response.headers.get("Content-Length")
                    declared_size = (
                        int(content_length_header) if content_length_header else None
                    )

                    if save_to_file:
                        return await self._fetch_to_file(
                            response, url, save_to_file, declared_size
                        )
                    else:
                        return await self._fetch_with_limit(
                            response, url, offset, limit, declared_size
                        )
            finally:
                if not session.closed:
                    await session.close()

        except TimeoutError:
            error_msg = f"Timeout fetching {url}"
            return ToolResult(
                success=False,
                error={"message": error_msg},
            )
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return ToolResult(
                success=False,
                error={"message": str(e)},
            )

    def _is_valid_url(self, url: str) -> bool:
        """Validate URL for safety — only http/https, no internal/localhost URLs."""
        try:
            parsed = urlparse(url)

            if not parsed.scheme or not parsed.netloc:
                return False

            if parsed.scheme not in ["http", "https"]:
                return False

            host = parsed.netloc.split(":")[0]  # strip optional port
            for blocked in self.blocked_domains:
                if blocked.endswith("."):
                    # IP prefix (e.g. "10.", "192.168.") — check host start
                    matched = host.startswith(blocked)
                else:
                    # Exact hostname or IP, with subdomain support
                    matched = host == blocked or host.endswith("." + blocked)
                if matched:
                    logger.warning(f"Blocked domain: {parsed.netloc}")
                    return False

            return True

        except Exception:
            return False

    async def _fetch_with_limit(
        self,
        response: aiohttp.ClientResponse,
        url: str,
        offset: int,
        limit: int,
        declared_size: Optional[int],
    ) -> ToolResult:
        """Fetch content with streaming and hard byte limit."""
        chunks: list[bytes] = []
        total_read = 0
        truncated = False

        max_to_read = offset + limit + 1

        async for chunk in response.content.iter_chunked(self.CHUNK_SIZE):
            chunk_len = len(chunk)
            chunk_end = total_read + chunk_len

            if chunk_end > offset and total_read < offset + limit:
                start_in_chunk = max(0, offset - total_read)
                end_in_chunk = min(chunk_len, offset + limit - total_read)
                chunks.append(chunk[start_in_chunk:end_in_chunk])

            total_read += chunk_len

            if total_read >= max_to_read:
                truncated = True
                break

        actual_total: Optional[int] = None
        if truncated:
            remaining_size = 0
            async for chunk in response.content.iter_chunked(self.CHUNK_SIZE):
                remaining_size += len(chunk)
            actual_total = total_read + remaining_size
        else:
            actual_total = total_read
            if total_read > offset + limit:
                truncated = True

        if declared_size and (actual_total is None or declared_size > actual_total):
            actual_total = declared_size

        raw_content = b"".join(chunks)
        content = self._decode_bytes(raw_content)

        content_type = response.content_type or ""
        text = self._extract_text(content, content_type)

        result_content = text
        if truncated:
            result_content = (
                f"{text}\n\n"
                f"[Content truncated at {limit} bytes. "
                f"Total: {actual_total or 'unknown'} bytes. "
                f"Use offset/limit to paginate or save_to_file for full content.]"
            )

        return ToolResult(
            success=True,
            output={
                "url": url,
                "content": result_content,
                "content_type": content_type,
                "truncated": truncated,
                "total_bytes": actual_total,
                "offset": offset,
                "limit": limit,
                "returned_bytes": len(raw_content),
            },
        )

    async def _fetch_to_file(
        self,
        response: aiohttp.ClientResponse,
        url: str,
        file_path: str,
        declared_size: Optional[int],
    ) -> ToolResult:
        """Fetch full content and save to file, return metadata + preview."""
        from pathlib import Path

        chunks: list[bytes] = []
        total_bytes = 0

        async for chunk in response.content.iter_chunked(self.CHUNK_SIZE):
            chunks.append(chunk)
            total_bytes += len(chunk)

        raw_content = b"".join(chunks)
        content = self._decode_bytes(raw_content)

        content_type = response.content_type or ""
        text = self._extract_text(content, content_type)

        try:
            path = Path(file_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except Exception as e:
            return ToolResult(
                success=False, error={"message": f"Failed to write file: {e}"}
            )

        preview = text[: self.PREVIEW_SIZE]
        if len(text) > self.PREVIEW_SIZE:
            preview += f"\n\n[... {len(text) - self.PREVIEW_SIZE} more characters saved to {file_path}]"

        return ToolResult(
            success=True,
            output={
                "url": url,
                "content": preview,
                "content_type": content_type,
                "truncated": False,
                "total_bytes": total_bytes,
                "saved_to": str(path),
                "saved_bytes": len(text.encode("utf-8")),
            },
        )

    def _decode_bytes(self, raw: bytes) -> str:
        """Decode raw bytes to str, falling back to latin-1 if utf-8 fails."""
        try:
            return raw.decode("utf-8")
        except Exception:
            return raw.decode("latin-1", errors="replace")

    def _extract_text(self, content: str, content_type: str) -> str:
        """Extract text from HTML content using BeautifulSoup."""
        if "html" in content_type:
            try:
                soup = BeautifulSoup(content, "html.parser")

                for script in soup(["script", "style"]):
                    script.decompose()

                text = soup.get_text()

                lines = (line.strip() for line in text.splitlines())
                chunks = (
                    phrase.strip() for line in lines for phrase in line.split("  ")
                )
                return "\n".join(chunk for chunk in chunks if chunk)

            except Exception as e:
                logger.warning(f"Failed to extract text: {e}")
                return content
        else:
            return content
