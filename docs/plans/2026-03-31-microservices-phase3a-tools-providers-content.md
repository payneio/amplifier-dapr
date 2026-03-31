# Phase 3a: Tool Services + Providers + Content Services — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Migrate all remaining tool services (filesystem, search, web, skills, todo, modes), all LLM providers, and all content-only services to the microservices architecture.

**Architecture:** Each tool service follows the svc-bash pattern: a tool class that forwards requests via httpx to svc-machine (for filesystem/search tools) or handles them self-contained (web, skills, todo, modes). Provider services accept `ChatRequest` and return `ChatResponse` via SDK models. Content-only services use the `amplifier-serve --config describe.yaml` CLI with zero Python code.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, httpx, amplifier-service-sdk, uv, pytest with asyncio_mode="auto", Docker, Dapr sidecars

---

## Reference: Existing Patterns

Before implementing, understand these existing patterns by reading these files:

- **Tool service pattern:** `services/svc-bash/src/svc_bash/tool.py` (tool class), `services/svc-bash/src/svc_bash/app.py` (app factory), `services/svc-bash/tests/test_tool.py` (tests)
- **Provider service pattern:** `services/svc-mock-provider/src/svc_mock_provider/app.py` (provider app factory)
- **SDK models:** `amplifier-service-sdk/src/amplifier_service_sdk/models.py` (ToolResult, ToolRequest, ChatRequest, ChatResponse, etc.)
- **SDK app factory:** `amplifier-service-sdk/src/amplifier_service_sdk/service.py` (ServiceConfig, create_app)
- **SDK CLI:** `amplifier-service-sdk/src/amplifier_service_sdk/cli.py` (amplifier-serve --config)
- **Machine API:** `services/svc-machine/src/svc_machine/service.py` (endpoints: POST /files/read, /files/write, /files/edit, /files/list, /files/glob, /files/grep, /exec)
- **Docker Compose:** `docker-compose.yaml` (existing service + sidecar pattern)

---

## Task 1: svc-filesystem — Filesystem Tool Service

**Files:**
- Create: `services/svc-filesystem/pyproject.toml`
- Create: `services/svc-filesystem/Dockerfile`
- Create: `services/svc-filesystem/describe.yaml`
- Create: `services/svc-filesystem/src/svc_filesystem/__init__.py`
- Create: `services/svc-filesystem/src/svc_filesystem/tools.py`
- Create: `services/svc-filesystem/src/svc_filesystem/app.py`
- Create: `services/svc-filesystem/tests/__init__.py`
- Create: `services/svc-filesystem/tests/test_tools.py`
- Create: `services/svc-filesystem/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-filesystem/tests/__init__.py` (empty).

Create `services/svc-filesystem/tests/test_tools.py`:

```python
"""Tests for filesystem tools — ReadFileTool, WriteFileTool, EditFileTool."""

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
        return ReadFileTool(machine_base_url="http://fake-machine:8080")

    @pytest.mark.asyncio
    async def test_execute_reads_file(self, tool: ReadFileTool) -> None:
        """execute() calls machine /files/read and returns file content."""
        mock_response = {"content": "     1\thello world", "total_lines": 1}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_response)
        ):
            result = await tool.execute({"file_path": "/tmp/test.txt"})

        assert result.success is True
        assert result.output is not None
        assert "content" in result.output

    @pytest.mark.asyncio
    async def test_execute_missing_file_path(self, tool: ReadFileTool) -> None:
        """execute() with no file_path returns error."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "file_path" in result.error["message"]

    @pytest.mark.asyncio
    async def test_execute_machine_http_error(self, tool: ReadFileTool) -> None:
        """execute() returns error when machine returns HTTP error."""
        exc = httpx.HTTPStatusError(
            "Not Found",
            request=httpx.Request("POST", "http://fake-machine:8080/files/read"),
            response=httpx.Response(404),
        )
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"file_path": "/nonexistent.txt"})

        assert result.success is False
        assert "404" in result.error["message"]

    @pytest.mark.asyncio
    async def test_execute_machine_unreachable(self, tool: ReadFileTool) -> None:
        """execute() returns error when machine service is unreachable."""
        exc = httpx.ConnectError("Connection refused")
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"file_path": "/tmp/test.txt"})

        assert result.success is False
        assert "unreachable" in result.error["message"]


class TestWriteFileTool:
    """Tests for WriteFileTool.execute."""

    @pytest.fixture
    def tool(self) -> WriteFileTool:
        return WriteFileTool(machine_base_url="http://fake-machine:8080")

    @pytest.mark.asyncio
    async def test_execute_writes_file(self, tool: WriteFileTool) -> None:
        """execute() calls machine /files/write and returns success."""
        mock_response = {"success": True}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_response)
        ):
            result = await tool.execute(
                {"file_path": "/tmp/test.txt", "content": "hello"}
            )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_missing_file_path(self, tool: WriteFileTool) -> None:
        """execute() with no file_path returns error."""
        result = await tool.execute({"content": "hello"})
        assert result.success is False
        assert "file_path" in result.error["message"]

    @pytest.mark.asyncio
    async def test_execute_missing_content(self, tool: WriteFileTool) -> None:
        """execute() with no content returns error."""
        result = await tool.execute({"file_path": "/tmp/test.txt"})
        assert result.success is False
        assert "content" in result.error["message"]


class TestEditFileTool:
    """Tests for EditFileTool.execute."""

    @pytest.fixture
    def tool(self) -> EditFileTool:
        return EditFileTool(machine_base_url="http://fake-machine:8080")

    @pytest.mark.asyncio
    async def test_execute_edits_file(self, tool: EditFileTool) -> None:
        """execute() calls machine /files/edit and returns success."""
        mock_response = {"success": True, "replacements_made": 1}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_response)
        ):
            result = await tool.execute(
                {
                    "file_path": "/tmp/test.txt",
                    "old_string": "hello",
                    "new_string": "world",
                }
            )

        assert result.success is True
        assert result.output["replacements_made"] == 1

    @pytest.mark.asyncio
    async def test_execute_missing_required_fields(self, tool: EditFileTool) -> None:
        """execute() with missing fields returns error."""
        result = await tool.execute({"file_path": "/tmp/test.txt"})
        assert result.success is False
        assert "old_string" in result.error["message"]

    @pytest.mark.asyncio
    async def test_execute_same_strings(self, tool: EditFileTool) -> None:
        """execute() with identical old/new strings returns error."""
        result = await tool.execute(
            {
                "file_path": "/tmp/test.txt",
                "old_string": "same",
                "new_string": "same",
            }
        )
        assert result.success is False
        assert "different" in result.error["message"]
```

Create `services/svc-filesystem/tests/test_app.py`:

```python
"""Tests for the svc-filesystem FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_filesystem.app import create_filesystem_app


class TestFilesystemApp:
    """Tests for the filesystem FastAPI application."""

    def setup_method(self) -> None:
        self.app = create_filesystem_app(
            machine_base_url="http://fake-machine:8080"
        )
        self.client = TestClient(self.app)

    def test_module_exposes_app(self) -> None:
        """svc_filesystem.app must expose a module-level FastAPI 'app' object."""
        from svc_filesystem import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)

    def test_healthz(self) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_all_tools(self) -> None:
        """GET /describe returns tools list containing all filesystem tools."""
        response = self.client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "edit_file" in tool_names
```

**Step 2: Create the project scaffold**

Create `services/svc-filesystem/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-filesystem"
version = "0.1.0"
description = "Amplifier filesystem tool service — read, write, edit files via svc-machine"
requires-python = ">=3.12"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/svc_filesystem"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.12"
extraPaths = ["src"]
venvPath = "."
venv = ".venv"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.28",
]
```

Create `services/svc-filesystem/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-filesystem/ /build/svc-filesystem/
RUN cd /build/svc-filesystem && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_filesystem.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `services/svc-filesystem/describe.yaml`:

```yaml
name: svc-filesystem
version: '0.1.0'
tools:
  - name: read_file
    description: >
      Reads a file or lists a directory from the local filesystem.
      Supports absolute and relative paths, line offset/limit pagination,
      line numbering in cat -n format.
    input_schema:
      type: object
      properties:
        file_path:
          type: string
          description: The absolute path to the file/directory to read
        offset:
          type: integer
          description: The line number to start reading from (1-indexed)
        limit:
          type: integer
          description: The number of lines to read
      required:
        - file_path
  - name: write_file
    description: >
      Writes a file to the local filesystem. Overwrites existing files.
      Creates parent directories as needed.
    input_schema:
      type: object
      properties:
        file_path:
          type: string
          description: The absolute path to the file to write
        content:
          type: string
          description: The content to write to the file
      required:
        - file_path
        - content
  - name: edit_file
    description: >
      Performs exact string replacements in files. Fails if old_string
      is not unique unless replace_all is true.
    input_schema:
      type: object
      properties:
        file_path:
          type: string
          description: The absolute path to the file to modify
        old_string:
          type: string
          description: The text to replace
        new_string:
          type: string
          description: The text to replace it with
        replace_all:
          type: boolean
          default: false
          description: Replace all occurrences of old_string
      required:
        - file_path
        - old_string
        - new_string
```

Create `services/svc-filesystem/src/svc_filesystem/__init__.py` (empty).

**Step 3: Write the implementation**

Create `services/svc-filesystem/src/svc_filesystem/tools.py`:

```python
"""Filesystem tools — read, write, edit files by calling svc-machine via httpx."""

from __future__ import annotations

from typing import Any

import httpx

from amplifier_service_sdk.models import ToolResult


class ReadFileTool:
    """Read files/directories by forwarding to svc-machine /files/read."""

    name: str = "read_file"
    description: str = "Read a file or list a directory from the filesystem"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "The absolute path to the file/directory to read",
            },
            "offset": {
                "type": "integer",
                "description": "The line number to start reading from (1-indexed)",
            },
            "limit": {
                "type": "integer",
                "description": "The number of lines to read",
            },
        },
        "required": ["file_path"],
    }

    def __init__(self, machine_base_url: str) -> None:
        self._base_url = machine_base_url.rstrip("/")

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Read a file or directory via the machine service."""
        file_path = input.get("file_path")
        if not file_path:
            return ToolResult(
                success=False,
                error={"message": "file_path is required"},
            )

        payload: dict[str, Any] = {"path": file_path}
        if "offset" in input:
            payload["offset"] = input["offset"]
        if "limit" in input:
            payload["limit"] = input["limit"]

        try:
            result = await self._call_machine(payload)
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service error: {exc.response.status_code}"},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service unreachable: {exc}"},
            )

        return ToolResult(
            success=True,
            output={
                "file_path": file_path,
                "content": result.get("content", ""),
                "total_lines": result.get("total_lines", 0),
            },
        )

    async def _call_machine(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to svc-machine /files/read."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._base_url}/files/read", json=payload
            )
            response.raise_for_status()
            return response.json()


class WriteFileTool:
    """Write files by forwarding to svc-machine /files/write."""

    name: str = "write_file"
    description: str = "Write content to a file on the filesystem"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "The absolute path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "The content to write to the file",
            },
        },
        "required": ["file_path", "content"],
    }

    def __init__(self, machine_base_url: str) -> None:
        self._base_url = machine_base_url.rstrip("/")

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Write content to a file via the machine service."""
        file_path = input.get("file_path")
        if not file_path:
            return ToolResult(
                success=False,
                error={"message": "file_path is required"},
            )
        content = input.get("content")
        if content is None:
            return ToolResult(
                success=False,
                error={"message": "content is required"},
            )

        try:
            result = await self._call_machine(
                {"path": file_path, "content": content}
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service error: {exc.response.status_code}"},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service unreachable: {exc}"},
            )

        return ToolResult(
            success=True,
            output={"file_path": file_path, "success": result.get("success", True)},
        )

    async def _call_machine(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to svc-machine /files/write."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._base_url}/files/write", json=payload
            )
            response.raise_for_status()
            return response.json()


class EditFileTool:
    """Edit files by forwarding to svc-machine /files/edit."""

    name: str = "edit_file"
    description: str = "Perform exact string replacements in files"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "The absolute path to the file to modify",
            },
            "old_string": {
                "type": "string",
                "description": "The text to replace",
            },
            "new_string": {
                "type": "string",
                "description": "The text to replace it with",
            },
            "replace_all": {
                "type": "boolean",
                "default": False,
                "description": "Replace all occurrences of old_string",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    def __init__(self, machine_base_url: str) -> None:
        self._base_url = machine_base_url.rstrip("/")

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Edit a file via the machine service."""
        file_path = input.get("file_path")
        if not file_path:
            return ToolResult(
                success=False,
                error={"message": "file_path is required"},
            )

        old_string = input.get("old_string")
        if not old_string:
            return ToolResult(
                success=False,
                error={"message": "old_string is required"},
            )

        new_string = input.get("new_string")
        if new_string is None:
            return ToolResult(
                success=False,
                error={"message": "new_string is required"},
            )

        if old_string == new_string:
            return ToolResult(
                success=False,
                error={
                    "message": "old_string and new_string must be different (no changes to make)"
                },
            )

        replace_all = input.get("replace_all", False)

        try:
            result = await self._call_machine(
                {
                    "path": file_path,
                    "old_string": old_string,
                    "new_string": new_string,
                    "replace_all": replace_all,
                }
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service error: {exc.response.status_code}"},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service unreachable: {exc}"},
            )

        return ToolResult(
            success=result.get("success", True),
            output={
                "file_path": file_path,
                "replacements_made": result.get("replacements_made", 0),
            },
        )

    async def _call_machine(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to svc-machine /files/edit."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._base_url}/files/edit", json=payload
            )
            response.raise_for_status()
            return response.json()
```

Create `services/svc-filesystem/src/svc_filesystem/app.py`:

```python
"""FastAPI app factory for svc-filesystem — filesystem tool service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_filesystem.tools import EditFileTool, ReadFileTool, WriteFileTool

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")


def create_filesystem_app(machine_base_url: str | None = None) -> FastAPI:
    """Create the svc-filesystem FastAPI application.

    Args:
        machine_base_url: Base URL for the machine service. Defaults to
            Dapr sidecar invocation URL for svc-machine.

    Returns:
        Configured FastAPI application.
    """
    if machine_base_url is None:
        machine_base_url = (
            f"http://localhost:{_DAPR_HTTP_PORT}/v1.0/invoke/svc-machine/method"
        )

    read_tool = ReadFileTool(machine_base_url=machine_base_url)
    write_tool = WriteFileTool(machine_base_url=machine_base_url)
    edit_tool = EditFileTool(machine_base_url=machine_base_url)

    config = ServiceConfig(
        name="svc-filesystem",
        tools=[
            ToolCapability(
                name=read_tool.name,
                description=read_tool.description,
                input_schema=read_tool.input_schema,
            ),
            ToolCapability(
                name=write_tool.name,
                description=write_tool.description,
                input_schema=write_tool.input_schema,
            ),
            ToolCapability(
                name=edit_tool.name,
                description=edit_tool.description,
                input_schema=edit_tool.input_schema,
            ),
        ],
    )
    app = create_app(config)

    @app.post("/tools/read_file/execute")
    async def execute_read(request: ToolRequest) -> dict[str, Any]:
        """Read a file or directory via the machine service."""
        result = await read_tool.execute(request.input)
        return result.model_dump()

    @app.post("/tools/write_file/execute")
    async def execute_write(request: ToolRequest) -> dict[str, Any]:
        """Write content to a file via the machine service."""
        result = await write_tool.execute(request.input)
        return result.model_dump()

    @app.post("/tools/edit_file/execute")
    async def execute_edit(request: ToolRequest) -> dict[str, Any]:
        """Edit a file via the machine service."""
        result = await edit_tool.execute(request.input)
        return result.model_dump()

    return app


app = create_filesystem_app()
```

**Step 4: Install dependencies and run tests**

Run:
```bash
cd services/svc-filesystem && uv sync && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-filesystem/ && git commit -m "feat(svc-filesystem): add filesystem tool service with read/write/edit tools"
```

---

## Task 2: svc-search — Search Tool Service

**Files:**
- Create: `services/svc-search/pyproject.toml`
- Create: `services/svc-search/Dockerfile`
- Create: `services/svc-search/describe.yaml`
- Create: `services/svc-search/src/svc_search/__init__.py`
- Create: `services/svc-search/src/svc_search/tools.py`
- Create: `services/svc-search/src/svc_search/app.py`
- Create: `services/svc-search/tests/__init__.py`
- Create: `services/svc-search/tests/test_tools.py`
- Create: `services/svc-search/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-search/tests/__init__.py` (empty).

Create `services/svc-search/tests/test_tools.py`:

```python
"""Tests for search tools — GrepTool, GlobTool."""

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
        return GrepTool(machine_base_url="http://fake-machine:8080")

    @pytest.mark.asyncio
    async def test_execute_grep(self, tool: GrepTool) -> None:
        """execute() calls machine /files/grep and returns matches."""
        mock_response = {"matches": ["file1.py:10:match line"]}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_response)
        ):
            result = await tool.execute({"pattern": "test"})

        assert result.success is True
        assert result.output is not None

    @pytest.mark.asyncio
    async def test_execute_missing_pattern(self, tool: GrepTool) -> None:
        """execute() with no pattern returns error."""
        result = await tool.execute({})
        assert result.success is False
        assert "pattern" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_machine_error(self, tool: GrepTool) -> None:
        """execute() returns error on machine HTTP error."""
        exc = httpx.HTTPStatusError(
            "Error",
            request=httpx.Request("POST", "http://fake-machine:8080/files/grep"),
            response=httpx.Response(500),
        )
        with patch.object(tool, "_call_machine", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"pattern": "test"})

        assert result.success is False


class TestGlobTool:
    """Tests for GlobTool.execute."""

    @pytest.fixture
    def tool(self) -> GlobTool:
        return GlobTool(machine_base_url="http://fake-machine:8080")

    @pytest.mark.asyncio
    async def test_execute_glob(self, tool: GlobTool) -> None:
        """execute() calls machine /files/glob and returns matches."""
        mock_response = {"matches": ["src/main.py", "src/utils.py"]}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_response)
        ):
            result = await tool.execute({"pattern": "**/*.py"})

        assert result.success is True
        assert result.output is not None

    @pytest.mark.asyncio
    async def test_execute_missing_pattern(self, tool: GlobTool) -> None:
        """execute() with no pattern returns error."""
        result = await tool.execute({})
        assert result.success is False
        assert "pattern" in result.error["message"].lower()
```

Create `services/svc-search/tests/test_app.py`:

```python
"""Tests for the svc-search FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_search.app import create_search_app


class TestSearchApp:
    def setup_method(self) -> None:
        self.app = create_search_app(machine_base_url="http://fake-machine:8080")
        self.client = TestClient(self.app)

    def test_module_exposes_app(self) -> None:
        from svc_search import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_all_tools(self) -> None:
        response = self.client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "grep" in tool_names
        assert "glob" in tool_names
```

**Step 2: Create the project scaffold**

Create `services/svc-search/pyproject.toml` (same structure as svc-filesystem, name `svc-search`, packages `svc_search`).

Create `services/svc-search/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-search/ /build/svc-search/
RUN cd /build/svc-search && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_search.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `services/svc-search/describe.yaml` with `grep` and `glob` tool schemas matching the input schemas from `services/amplifier-foundation/src/amplifier_foundation/tools/search/grep.py` (the `input_schema` property) and `glob.py`.

**Step 3: Write the implementation**

Create `services/svc-search/src/svc_search/__init__.py` (empty).

Create `services/svc-search/src/svc_search/tools.py`:

```python
"""Search tools — grep and glob by calling svc-machine via httpx."""

from __future__ import annotations

from typing import Any

import httpx

from amplifier_service_sdk.models import ToolResult


class GrepTool:
    """Search file contents by forwarding to svc-machine /files/grep."""

    name: str = "grep"
    description: str = "Search file contents with regex patterns"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The regular expression pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, machine_base_url: str) -> None:
        self._base_url = machine_base_url.rstrip("/")

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Search files via the machine service."""
        pattern = input.get("pattern")
        if not pattern:
            return ToolResult(
                success=False,
                error={"message": "Pattern is required"},
            )

        payload: dict[str, Any] = {"pattern": pattern}
        if "path" in input:
            payload["path"] = input["path"]

        try:
            result = await self._call_machine(payload)
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service error: {exc.response.status_code}"},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service unreachable: {exc}"},
            )

        return ToolResult(
            success=True,
            output={"pattern": pattern, "matches": result.get("matches", [])},
        )

    async def _call_machine(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to svc-machine /files/grep."""
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self._base_url}/files/grep", json=payload
            )
            response.raise_for_status()
            return response.json()


class GlobTool:
    """Find files matching glob patterns by forwarding to svc-machine /files/glob."""

    name: str = "glob"
    description: str = "Find files matching glob patterns"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files (e.g., '**/*.py')",
            },
            "path": {
                "type": "string",
                "description": "Base path to search from",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, machine_base_url: str) -> None:
        self._base_url = machine_base_url.rstrip("/")

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Find files via the machine service."""
        pattern = input.get("pattern")
        if not pattern:
            return ToolResult(
                success=False,
                error={"message": "Pattern is required"},
            )

        payload: dict[str, Any] = {"pattern": pattern}
        if "path" in input:
            payload["path"] = input["path"]

        try:
            result = await self._call_machine(payload)
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service error: {exc.response.status_code}"},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service unreachable: {exc}"},
            )

        return ToolResult(
            success=True,
            output={
                "pattern": pattern,
                "matches": result.get("matches", []),
            },
        )

    async def _call_machine(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to svc-machine /files/glob."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._base_url}/files/glob", json=payload
            )
            response.raise_for_status()
            return response.json()
```

Create `services/svc-search/src/svc_search/app.py`:

```python
"""FastAPI app factory for svc-search — grep and glob tool service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_search.tools import GlobTool, GrepTool

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")


def create_search_app(machine_base_url: str | None = None) -> FastAPI:
    """Create the svc-search FastAPI application."""
    if machine_base_url is None:
        machine_base_url = (
            f"http://localhost:{_DAPR_HTTP_PORT}/v1.0/invoke/svc-machine/method"
        )

    grep_tool = GrepTool(machine_base_url=machine_base_url)
    glob_tool = GlobTool(machine_base_url=machine_base_url)

    config = ServiceConfig(
        name="svc-search",
        tools=[
            ToolCapability(
                name=grep_tool.name,
                description=grep_tool.description,
                input_schema=grep_tool.input_schema,
            ),
            ToolCapability(
                name=glob_tool.name,
                description=glob_tool.description,
                input_schema=glob_tool.input_schema,
            ),
        ],
    )
    app = create_app(config)

    @app.post("/tools/grep/execute")
    async def execute_grep(request: ToolRequest) -> dict[str, Any]:
        """Search file contents via the machine service."""
        result = await grep_tool.execute(request.input)
        return result.model_dump()

    @app.post("/tools/glob/execute")
    async def execute_glob(request: ToolRequest) -> dict[str, Any]:
        """Find files matching glob pattern via the machine service."""
        result = await glob_tool.execute(request.input)
        return result.model_dump()

    return app


app = create_search_app()
```

**Step 4: Run tests**

```bash
cd services/svc-search && uv sync && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-search/ && git commit -m "feat(svc-search): add search tool service with grep and glob tools"
```

---

## Task 3: svc-web — Web Tool Service

**Files:**
- Create: `services/svc-web/pyproject.toml`
- Create: `services/svc-web/Dockerfile`
- Create: `services/svc-web/describe.yaml`
- Create: `services/svc-web/src/svc_web/__init__.py`
- Create: `services/svc-web/src/svc_web/tools.py`
- Create: `services/svc-web/src/svc_web/app.py`
- Create: `services/svc-web/tests/__init__.py`
- Create: `services/svc-web/tests/test_tools.py`
- Create: `services/svc-web/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-web/tests/test_tools.py`:

```python
"""Tests for web tools — WebSearchTool, WebFetchTool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from svc_web.tools import WebFetchTool, WebSearchTool


class TestWebSearchTool:

    @pytest.fixture
    def tool(self) -> WebSearchTool:
        return WebSearchTool()

    @pytest.mark.asyncio
    async def test_execute_missing_query(self, tool: WebSearchTool) -> None:
        result = await tool.execute({})
        assert result.success is False
        assert "query" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_search_returns_results(self, tool: WebSearchTool) -> None:
        """execute() with mocked search returns results."""
        mock_results = [
            {"title": "Test", "url": "https://example.com", "snippet": "A result"}
        ]
        with patch.object(
            tool, "_search", new=AsyncMock(return_value=mock_results)
        ):
            result = await tool.execute({"query": "test query"})

        assert result.success is True
        assert result.output["count"] == 1

    @pytest.mark.asyncio
    async def test_execute_search_error(self, tool: WebSearchTool) -> None:
        """execute() returns error on search failure."""
        with patch.object(
            tool, "_search", new=AsyncMock(side_effect=Exception("Network error"))
        ):
            result = await tool.execute({"query": "test"})

        assert result.success is False


class TestWebFetchTool:

    @pytest.fixture
    def tool(self) -> WebFetchTool:
        return WebFetchTool()

    @pytest.mark.asyncio
    async def test_execute_missing_url(self, tool: WebFetchTool) -> None:
        result = await tool.execute({})
        assert result.success is False
        assert "url" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_blocked_url(self, tool: WebFetchTool) -> None:
        result = await tool.execute({"url": "http://localhost:8080"})
        assert result.success is False
        assert "blocked" in result.error["message"].lower() or "invalid" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_invalid_scheme(self, tool: WebFetchTool) -> None:
        result = await tool.execute({"url": "ftp://example.com"})
        assert result.success is False
```

Create `services/svc-web/tests/test_app.py`:

```python
"""Tests for the svc-web FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_web.app import create_web_app


class TestWebApp:
    def setup_method(self) -> None:
        self.app = create_web_app()
        self.client = TestClient(self.app)

    def test_module_exposes_app(self) -> None:
        from svc_web import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_all_tools(self) -> None:
        response = self.client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "web_search" in tool_names
        assert "web_fetch" in tool_names
```

**Step 2: Create project scaffold**

Create `services/svc-web/pyproject.toml` — same structure as svc-filesystem but with:
- `name = "svc-web"`
- `packages = ["src/svc_web"]`
- Dependencies: `"amplifier-service-sdk"`, `"aiohttp>=3.9"`, `"beautifulsoup4>=4.12"`, `"duckduckgo-search>=6.0"`

Create `services/svc-web/Dockerfile`, `services/svc-web/describe.yaml` (with `web_search` and `web_fetch` tool schemas).

**Step 3: Write the implementation**

Create `services/svc-web/src/svc_web/tools.py` — port from `services/amplifier-foundation/src/amplifier_foundation/tools/web.py`. Key changes:
- Replace `from amplifier_ipc.protocol import ToolResult` with `from amplifier_service_sdk.models import ToolResult`
- Remove `@tool` decorators
- Keep all the business logic: DuckDuckGo search via `DDGS`, aiohttp fetch with BeautifulSoup extraction, URL validation with blocked domains, streaming with byte limits

The `WebSearchTool._search` method wraps `DDGS().text()` in `run_in_executor`. The `WebFetchTool` uses `aiohttp.ClientSession` with streaming chunk reads and pagination support.

Create `services/svc-web/src/svc_web/app.py` — same pattern as svc-filesystem but with web tools and no machine_base_url.

**Step 4: Run tests**

```bash
cd services/svc-web && uv sync && uv run pytest tests/ -v
```

**Step 5: Commit**

```bash
git add services/svc-web/ && git commit -m "feat(svc-web): add web tool service with search and fetch tools"
```

---

## Task 4: svc-skills — Skills Tool Service

**Files:**
- Create: `services/svc-skills/pyproject.toml`
- Create: `services/svc-skills/Dockerfile`
- Create: `services/svc-skills/describe.yaml`
- Create: `services/svc-skills/src/svc_skills/__init__.py`
- Create: `services/svc-skills/src/svc_skills/tool.py`
- Create: `services/svc-skills/src/svc_skills/discovery.py`
- Create: `services/svc-skills/src/svc_skills/sources.py`
- Create: `services/svc-skills/src/svc_skills/app.py`
- Create: `services/svc-skills/tests/__init__.py`
- Create: `services/svc-skills/tests/test_tool.py`
- Create: `services/svc-skills/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-skills/tests/test_tool.py`:

```python
"""Tests for SkillsTool."""

from __future__ import annotations

from pathlib import Path

import pytest

from svc_skills.tool import SkillsTool


class TestSkillsTool:

    @pytest.fixture
    def tool(self, tmp_path: Path) -> SkillsTool:
        """Create a SkillsTool with a test skills directory."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # Create a test skill
        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: test-skill\ndescription: A test skill\nversion: '1.0'\n---\n\nTest skill body content."
        )
        tool = SkillsTool()
        tool.skills_dirs = [skills_dir]
        tool._initialized = False
        return tool

    @pytest.mark.asyncio
    async def test_list_skills(self, tool: SkillsTool) -> None:
        result = await tool.execute({"list": True})
        assert result.success is True
        assert "skills" in result.output

    @pytest.mark.asyncio
    async def test_search_skills(self, tool: SkillsTool) -> None:
        result = await tool.execute({"search": "test"})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_load_skill(self, tool: SkillsTool) -> None:
        result = await tool.execute({"skill_name": "test-skill"})
        assert result.success is True
        assert "content" in result.output

    @pytest.mark.asyncio
    async def test_skill_info(self, tool: SkillsTool) -> None:
        result = await tool.execute({"info": "test-skill"})
        assert result.success is True
        assert result.output["name"] == "test-skill"

    @pytest.mark.asyncio
    async def test_load_nonexistent_skill(self, tool: SkillsTool) -> None:
        result = await tool.execute({"skill_name": "nonexistent"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_no_params_returns_error(self, tool: SkillsTool) -> None:
        result = await tool.execute({})
        assert result.success is False
```

Create `services/svc-skills/tests/test_app.py` — same pattern: test /healthz, /describe includes `load_skill`, module-level app.

**Step 2: Create project scaffold**

`pyproject.toml` with dependencies: `"amplifier-service-sdk"`, `"pyyaml>=6.0"`

**Step 3: Write the implementation**

- Port `services/amplifier-skills/src/amplifier_skills/tools/skills/discovery.py` to `services/svc-skills/src/svc_skills/discovery.py` — replace `from amplifier_ipc.protocol import ToolResult` references, keep SkillMetadata dataclass, `discover_skills`, `discover_skills_multi_source`, `get_default_skills_dirs`, `extract_skill_body`, `parse_skill_frontmatter`
- Port `services/amplifier-skills/src/amplifier_skills/tools/skills/sources.py` to `services/svc-skills/src/svc_skills/sources.py` — keep `is_remote_source`, `resolve_skill_source`
- Port `services/amplifier-skills/src/amplifier_skills/tools/skills/tool.py` to `services/svc-skills/src/svc_skills/tool.py` — replace `from amplifier_ipc.protocol import ToolResult, tool` with `from amplifier_service_sdk.models import ToolResult`, remove `@tool` decorator, keep all execute logic
- Create `services/svc-skills/src/svc_skills/app.py` — register one tool endpoint `/tools/load_skill/execute`

**Step 4: Run tests**

```bash
cd services/svc-skills && uv sync && uv run pytest tests/ -v
```

**Step 5: Commit**

```bash
git add services/svc-skills/ && git commit -m "feat(svc-skills): add skills tool service with skill discovery"
```

---

## Task 5: svc-todo — Todo Tool + Hooks Service

**Files:**
- Create: `services/svc-todo/pyproject.toml`
- Create: `services/svc-todo/Dockerfile`
- Create: `services/svc-todo/describe.yaml`
- Create: `services/svc-todo/src/svc_todo/__init__.py`
- Create: `services/svc-todo/src/svc_todo/tool.py`
- Create: `services/svc-todo/src/svc_todo/hooks.py`
- Create: `services/svc-todo/src/svc_todo/app.py`
- Create: `services/svc-todo/tests/__init__.py`
- Create: `services/svc-todo/tests/test_tool.py`
- Create: `services/svc-todo/tests/test_hooks.py`
- Create: `services/svc-todo/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-todo/tests/test_tool.py`:

```python
"""Tests for TodoTool."""

from __future__ import annotations

import pytest

from svc_todo.tool import TodoTool


class TestTodoTool:

    @pytest.fixture
    def tool(self) -> TodoTool:
        return TodoTool()

    @pytest.mark.asyncio
    async def test_create_todos(self, tool: TodoTool) -> None:
        result = await tool.execute({
            "action": "create",
            "todos": [
                {"content": "Task 1", "activeForm": "Doing task 1", "status": "pending"},
            ],
        })
        assert result.success is True
        assert result.output["count"] == 1

    @pytest.mark.asyncio
    async def test_update_todos(self, tool: TodoTool) -> None:
        await tool.execute({
            "action": "create",
            "todos": [
                {"content": "Task 1", "activeForm": "Doing task 1", "status": "pending"},
            ],
        })
        result = await tool.execute({
            "action": "update",
            "todos": [
                {"content": "Task 1", "activeForm": "Doing task 1", "status": "completed"},
            ],
        })
        assert result.success is True
        assert result.output["completed"] == 1

    @pytest.mark.asyncio
    async def test_list_todos(self, tool: TodoTool) -> None:
        result = await tool.execute({"action": "list"})
        assert result.success is True
        assert result.output["count"] == 0

    @pytest.mark.asyncio
    async def test_invalid_action(self, tool: TodoTool) -> None:
        result = await tool.execute({"action": "delete"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_invalid_status(self, tool: TodoTool) -> None:
        result = await tool.execute({
            "action": "create",
            "todos": [
                {"content": "Task", "activeForm": "Tasking", "status": "invalid"},
            ],
        })
        assert result.success is False

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, tool: TodoTool) -> None:
        result = await tool.execute({
            "action": "create",
            "todos": [{"content": "Task"}],
        })
        assert result.success is False
```

Create `services/svc-todo/tests/test_hooks.py`:

```python
"""Tests for TodoReminderHook and TodoDisplayHook."""

from __future__ import annotations

import pytest

from svc_todo.hooks import TodoDisplayHook, TodoReminderHook


class TestTodoReminderHook:

    @pytest.mark.asyncio
    async def test_handle_returns_continue(self) -> None:
        hook = TodoReminderHook()
        result = await hook.handle("tool:post", {})
        assert result["action"] == "CONTINUE"


class TestTodoDisplayHook:

    @pytest.mark.asyncio
    async def test_handle_returns_continue(self) -> None:
        hook = TodoDisplayHook()
        result = await hook.handle("tool:post", {})
        assert result["action"] == "CONTINUE"
```

Create `services/svc-todo/tests/test_app.py` — test /healthz, /describe includes `todo`, module-level app.

**Step 2: Create project scaffold**

`pyproject.toml` — dependencies: `"amplifier-service-sdk"`

**Step 3: Write the implementation**

Port `services/amplifier-foundation/src/amplifier_foundation/tools/todo.py` to `services/svc-todo/src/svc_todo/tool.py`:
- Replace `from amplifier_ipc.protocol import ToolResult, tool` with `from amplifier_service_sdk.models import ToolResult`
- Remove `@tool` decorator
- Keep all execute logic (create, update, list, validation)

Create `services/svc-todo/src/svc_todo/hooks.py` — stub implementations:

```python
"""Todo hooks — in-process stubs for TodoReminderHook and TodoDisplayHook."""

from __future__ import annotations

from typing import Any


class TodoReminderHook:
    """Injects current todo list reminders. Stubbed until shared state available."""

    name = "todo_reminder"

    async def handle(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"action": "CONTINUE"}


class TodoDisplayHook:
    """Renders todo progress display. Stubbed until shared state available."""

    name = "todo_display"

    async def handle(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"action": "CONTINUE"}
```

Create `services/svc-todo/src/svc_todo/app.py` — register `/tools/todo/execute`.

**Step 4: Run tests**

```bash
cd services/svc-todo && uv sync && uv run pytest tests/ -v
```

**Step 5: Commit**

```bash
git add services/svc-todo/ && git commit -m "feat(svc-todo): add todo tool service with in-process hook stubs"
```

---

## Task 6: svc-modes — Mode Tool + Hook Service

**Files:**
- Create: `services/svc-modes/pyproject.toml`
- Create: `services/svc-modes/Dockerfile`
- Create: `services/svc-modes/describe.yaml`
- Create: `services/svc-modes/src/svc_modes/__init__.py`
- Create: `services/svc-modes/src/svc_modes/tool.py`
- Create: `services/svc-modes/src/svc_modes/hook.py`
- Create: `services/svc-modes/src/svc_modes/app.py`
- Create: `services/svc-modes/tests/__init__.py`
- Create: `services/svc-modes/tests/test_tool.py`
- Create: `services/svc-modes/tests/test_hook.py`
- Create: `services/svc-modes/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-modes/tests/test_tool.py`:

```python
"""Tests for ModeTool."""

from __future__ import annotations

import pytest

from svc_modes.hook import ModeDefinition, ModeHooks
from svc_modes.tool import ModeTool


class TestModeTool:

    @pytest.fixture
    def tool(self) -> ModeTool:
        hook = ModeHooks()
        t = ModeTool()
        t._mode_hooks = hook
        return t

    @pytest.mark.asyncio
    async def test_list_modes(self, tool: ModeTool) -> None:
        result = await tool.execute({"operation": "list"})
        assert result.success is True
        assert "modes" in result.output

    @pytest.mark.asyncio
    async def test_current_no_mode(self, tool: ModeTool) -> None:
        result = await tool.execute({"operation": "current"})
        assert result.success is True
        assert result.output["active_mode"] is None

    @pytest.mark.asyncio
    async def test_set_and_current(self, tool: ModeTool) -> None:
        """Set a mode via hooks directly and verify current."""
        mode = ModeDefinition(name="test", description="Test mode")
        tool._mode_hooks.set_active_mode(mode)
        result = await tool.execute({"operation": "current"})
        assert result.success is True
        assert result.output["active_mode"] == "test"

    @pytest.mark.asyncio
    async def test_clear_mode(self, tool: ModeTool) -> None:
        mode = ModeDefinition(name="test", description="Test mode")
        tool._mode_hooks.set_active_mode(mode)
        result = await tool.execute({"operation": "clear"})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_invalid_operation(self, tool: ModeTool) -> None:
        result = await tool.execute({"operation": "invalid"})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_not_ready(self) -> None:
        """Tool without mode_hooks returns not_ready error."""
        tool = ModeTool()
        result = await tool.execute({"operation": "list"})
        assert result.success is False
        assert "not_ready" in str(result.error)
```

Create `services/svc-modes/tests/test_hook.py`:

```python
"""Tests for ModeHooks."""

from __future__ import annotations

import pytest

from svc_modes.hook import ModeDefinition, ModeHooks


class TestModeHooks:

    @pytest.fixture
    def hooks(self) -> ModeHooks:
        return ModeHooks()

    def test_no_active_mode(self, hooks: ModeHooks) -> None:
        assert hooks.get_active_mode() is None

    def test_set_active_mode(self, hooks: ModeHooks) -> None:
        mode = ModeDefinition(name="plan", description="Planning mode")
        hooks.set_active_mode(mode)
        assert hooks.get_active_mode() is not None
        assert hooks.get_active_mode().name == "plan"

    def test_clear_active_mode(self, hooks: ModeHooks) -> None:
        mode = ModeDefinition(name="plan", description="Planning mode")
        hooks.set_active_mode(mode)
        hooks.clear_active_mode()
        assert hooks.get_active_mode() is None

    @pytest.mark.asyncio
    async def test_handle_no_mode_continues(self, hooks: ModeHooks) -> None:
        result = await hooks.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_handle_safe_tool_continues(self, hooks: ModeHooks) -> None:
        mode = ModeDefinition(
            name="plan", description="Plan", safe_tools=["read_file"]
        )
        hooks.set_active_mode(mode)
        result = await hooks.handle("tool:pre", {"tool_name": "read_file"})
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_handle_blocked_tool_denies(self, hooks: ModeHooks) -> None:
        mode = ModeDefinition(
            name="plan", description="Plan", block_tools=["bash"]
        )
        hooks.set_active_mode(mode)
        result = await hooks.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "DENY"
```

Create `services/svc-modes/tests/test_app.py` — test /healthz, /describe includes `mode`, module-level app.

**Step 2: Create project scaffold**

`pyproject.toml` — dependencies: `"amplifier-service-sdk"`, `"pyyaml>=6.0"`

**Step 3: Write the implementation**

Port `services/amplifier-modes/src/amplifier_modes/hooks/mode.py` to `services/svc-modes/src/svc_modes/hook.py`:
- Replace `from amplifier_ipc.protocol import HookAction, HookResult, hook` with local dataclass-based `HookResult`
- Keep `ModeDefinition` dataclass, `parse_mode_file`, `ModeHooks` class
- Remove `@hook` decorator
- `ModeHooks.handle()` returns a simple `HookResult` dataclass with `action: str` and optional `reason: str`

Define a simple HookResult:

```python
from dataclasses import dataclass

@dataclass
class HookResult:
    action: str = "CONTINUE"
    reason: str | None = None
    context_injection: str | None = None
    context_injection_role: str | None = None
    ephemeral: bool = False
```

Port `services/amplifier-modes/src/amplifier_modes/tools/mode.py` to `services/svc-modes/src/svc_modes/tool.py`:
- Replace `from amplifier_ipc.protocol import ToolResult, tool` with `from amplifier_service_sdk.models import ToolResult`
- Import `ModeDefinition, ModeHooks, parse_mode_file` from `svc_modes.hook`
- Remove `@tool` decorator

Create `services/svc-modes/src/svc_modes/app.py`:
- Instantiate `ModeHooks`, wire to `ModeTool._mode_hooks`
- Register `/tools/mode/execute`

**Step 4: Run tests**

```bash
cd services/svc-modes && uv sync && uv run pytest tests/ -v
```

**Step 5: Commit**

```bash
git add services/svc-modes/ && git commit -m "feat(svc-modes): add mode tool service with in-process hook"
```

---

## Task 7: svc-providers — Base Provider + Anthropic

**Files:**
- Create: `services/svc-providers/pyproject.toml`
- Create: `services/svc-providers/Dockerfile`
- Create: `services/svc-providers/describe.yaml`
- Create: `services/svc-providers/src/svc_providers/__init__.py`
- Create: `services/svc-providers/src/svc_providers/base.py`
- Create: `services/svc-providers/src/svc_providers/anthropic_provider.py`
- Create: `services/svc-providers/src/svc_providers/app.py`
- Create: `services/svc-providers/tests/__init__.py`
- Create: `services/svc-providers/tests/test_anthropic.py`
- Create: `services/svc-providers/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-providers/tests/test_anthropic.py`:

```python
"""Tests for AnthropicProvider — mock-based, no real API calls."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from svc_providers.anthropic_provider import AnthropicProvider


class TestAnthropicProvider:

    @pytest.fixture
    def provider(self) -> AnthropicProvider:
        return AnthropicProvider(config={"api_key": "test-key"})

    def test_provider_name(self, provider: AnthropicProvider) -> None:
        assert provider.name == "anthropic"

    def test_provider_config(self, provider: AnthropicProvider) -> None:
        assert provider.model is not None
        assert provider.max_tokens > 0

    @pytest.mark.asyncio
    async def test_complete_text_response(self, provider: AnthropicProvider) -> None:
        """complete() with mocked API returns ChatResponse with text."""
        from amplifier_service_sdk.models import ChatRequest, Message

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "Hello from Claude"

        mock_usage = MagicMock()
        mock_usage.input_tokens = 10
        mock_usage.output_tokens = 5
        mock_usage.cache_read_input_tokens = 0
        mock_usage.cache_creation_input_tokens = 0

        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.usage = mock_usage
        mock_response.stop_reason = "end_turn"
        mock_response.model = "claude-sonnet-4-20250514"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        request = ChatRequest(
            messages=[Message(role="user", content="Hello")],
            system="You are a helpful assistant",
        )
        response = await provider.complete(request)

        assert response.text == "Hello from Claude"
        assert response.usage is not None
        assert response.usage.input_tokens == 10
```

Create `services/svc-providers/tests/test_app.py`:

```python
"""Tests for the svc-providers FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_providers.app import create_providers_app


class TestProvidersApp:
    def setup_method(self) -> None:
        self.app = create_providers_app()
        self.client = TestClient(self.app)

    def test_module_exposes_app(self) -> None:
        from svc_providers import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_providers(self) -> None:
        response = self.client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        provider_names = [p["name"] for p in data["providers"]]
        assert "anthropic" in provider_names
```

**Step 2: Create project scaffold**

`pyproject.toml` — dependencies: `"amplifier-service-sdk"`, `"anthropic>=0.40"`. Mark anthropic as optional if possible, but for simplicity include it.

**Step 3: Write the implementation**

Create `services/svc-providers/src/svc_providers/base.py`:

```python
"""BaseProvider — abstract interface for all LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from amplifier_service_sdk.models import ChatRequest, ChatResponse


class BaseProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str = ""

    @abstractmethod
    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Process a chat request and return a response."""
        ...
```

Port `services/amplifier-providers/src/amplifier_providers/providers/anthropic_provider.py` to `services/svc-providers/src/svc_providers/anthropic_provider.py`:
- Replace `from amplifier_ipc.protocol import ChatRequest, ChatResponse, provider` with `from amplifier_service_sdk.models import ChatRequest, ChatResponse, Message, ToolCall, TokenUsage`
- Remove `@provider` decorator
- Replace `from amplifier_ipc.protocol.models import TextBlock, ThinkingBlock, ToolCall, ToolCallBlock, ToolSpec, Usage` with SDK equivalents. Since the SDK models don't have TextBlock/ThinkingBlock, simplify: convert Anthropic blocks to `ChatResponse` with `content` (text string or list) and `tool_calls` (list of `ToolCall`)
- Keep the retry logic, rate limiting, message conversion
- Inherit from `BaseProvider`

The `_convert_to_chat_response` should produce a `ChatResponse` using the SDK's existing models: `ChatResponse(content=text, tool_calls=[ToolCall(...)], usage=TokenUsage(input_tokens=..., output_tokens=...), stop_reason=...)`

Create `services/svc-providers/src/svc_providers/app.py`:

```python
"""FastAPI app factory for svc-providers — all LLM providers in one service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ChatRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_providers.anthropic_provider import AnthropicProvider


def create_providers_app() -> FastAPI:
    """Create the svc-providers FastAPI application."""
    anthropic = AnthropicProvider()

    config = ServiceConfig(
        name="svc-providers",
        providers=[
            {"name": "anthropic", "description": "Anthropic Claude provider"},
        ],
    )
    app = create_app(config)

    @app.post("/providers/anthropic/complete")
    async def complete_anthropic(request: ChatRequest) -> dict[str, Any]:
        response = await anthropic.complete(request)
        return response.model_dump()

    return app


app = create_providers_app()
```

**Step 4: Run tests**

```bash
cd services/svc-providers && uv sync && uv run pytest tests/ -v
```

**Step 5: Commit**

```bash
git add services/svc-providers/ && git commit -m "feat(svc-providers): add provider service with Anthropic provider"
```

---

## Task 8: svc-providers — OpenAI + Azure Providers

**Files:**
- Create: `services/svc-providers/src/svc_providers/openai_provider.py`
- Create: `services/svc-providers/src/svc_providers/azure_openai_provider.py`
- Create: `services/svc-providers/tests/test_openai.py`
- Modify: `services/svc-providers/src/svc_providers/app.py`
- Modify: `services/svc-providers/pyproject.toml` (add `"openai>=1.50"`)
- Modify: `services/svc-providers/describe.yaml`

**Step 1: Write the failing tests**

Create `services/svc-providers/tests/test_openai.py`:

```python
"""Tests for OpenAIProvider and AzureOpenAIProvider — mock-based."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from svc_providers.openai_provider import OpenAIProvider


class TestOpenAIProvider:

    @pytest.fixture
    def provider(self) -> OpenAIProvider:
        return OpenAIProvider(config={"api_key": "test-key"})

    def test_provider_name(self, provider: OpenAIProvider) -> None:
        assert provider.name == "openai"

    @pytest.mark.asyncio
    async def test_complete_text_response(self, provider: OpenAIProvider) -> None:
        from amplifier_service_sdk.models import ChatRequest, Message

        mock_message = MagicMock()
        mock_message.content = "Hello from GPT"
        mock_message.tool_calls = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_choice.finish_reason = "stop"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        request = ChatRequest(
            messages=[Message(role="user", content="Hello")],
        )
        response = await provider.complete(request)

        assert response.content is not None
        assert response.usage is not None
```

**Step 2: Write implementation**

Port `services/amplifier-providers/src/amplifier_providers/providers/openai_provider.py` to `services/svc-providers/src/svc_providers/openai_provider.py` — same pattern as anthropic port.

Port `services/amplifier-providers/src/amplifier_providers/providers/azure_openai_provider.py` to `services/svc-providers/src/svc_providers/azure_openai_provider.py` — inherits from `OpenAIProvider`, overrides client initialization.

**Step 3: Update app.py**

Add OpenAI and Azure endpoints to `services/svc-providers/src/svc_providers/app.py`:

```python
from svc_providers.openai_provider import OpenAIProvider
from svc_providers.azure_openai_provider import AzureOpenAIProvider

# In create_providers_app():
openai_prov = OpenAIProvider()
azure_prov = AzureOpenAIProvider()

# Add to config.providers list:
{"name": "openai", "description": "OpenAI GPT provider"},
{"name": "azure-openai", "description": "Azure OpenAI provider"},

# Add routes:
@app.post("/providers/openai/complete")
async def complete_openai(request: ChatRequest) -> dict[str, Any]:
    response = await openai_prov.complete(request)
    return response.model_dump()

@app.post("/providers/azure-openai/complete")
async def complete_azure(request: ChatRequest) -> dict[str, Any]:
    response = await azure_prov.complete(request)
    return response.model_dump()
```

**Step 4: Run tests**

```bash
cd services/svc-providers && uv run pytest tests/ -v
```

**Step 5: Commit**

```bash
git add services/svc-providers/ && git commit -m "feat(svc-providers): add OpenAI and Azure OpenAI providers"
```

---

## Task 9: svc-providers — Remaining Providers (Gemini, Ollama, vLLM, GitHub Copilot)

**Files:**
- Create: `services/svc-providers/src/svc_providers/gemini_provider.py`
- Create: `services/svc-providers/src/svc_providers/ollama_provider.py`
- Create: `services/svc-providers/src/svc_providers/vllm_provider.py`
- Create: `services/svc-providers/src/svc_providers/github_copilot_provider.py`
- Create: `services/svc-providers/tests/test_gemini.py`
- Create: `services/svc-providers/tests/test_remaining.py`
- Modify: `services/svc-providers/src/svc_providers/app.py`
- Modify: `services/svc-providers/pyproject.toml` (add `"google-generativeai>=0.8"`, `"ollama>=0.3"`)
- Modify: `services/svc-providers/describe.yaml`

**Step 1: Write the failing tests**

Create `services/svc-providers/tests/test_remaining.py`:

```python
"""Tests for remaining providers — basic instantiation and config."""

from __future__ import annotations

import pytest

from svc_providers.gemini_provider import GeminiProvider
from svc_providers.ollama_provider import OllamaProvider
from svc_providers.vllm_provider import VllmProvider
from svc_providers.github_copilot_provider import GitHubCopilotProvider


class TestGeminiProvider:
    def test_name(self) -> None:
        p = GeminiProvider(config={"api_key": "test"})
        assert p.name == "gemini"

class TestOllamaProvider:
    def test_name(self) -> None:
        p = OllamaProvider()
        assert p.name == "ollama"

class TestVllmProvider:
    def test_name(self) -> None:
        p = VllmProvider(config={"api_key": "EMPTY"})
        assert p.name == "vllm"

class TestGitHubCopilotProvider:
    def test_name(self) -> None:
        p = GitHubCopilotProvider(config={"github_token": "test"})
        assert p.name == "github_copilot"
```

**Step 2: Write implementation**

Port each provider from `services/amplifier-providers/src/amplifier_providers/providers/`:
- `gemini_provider.py` → `services/svc-providers/src/svc_providers/gemini_provider.py`
- `ollama_provider.py` → `services/svc-providers/src/svc_providers/ollama_provider.py`
- `vllm_provider.py` → `services/svc-providers/src/svc_providers/vllm_provider.py` (inherits from `OpenAIProvider`)
- `github_copilot_provider.py` → `services/svc-providers/src/svc_providers/github_copilot_provider.py` (inherits from `OpenAIProvider`)

Same porting pattern: replace `amplifier_ipc.protocol` imports with SDK imports, remove `@provider` decorators, inherit from `BaseProvider`.

**Step 3: Update app.py with all routes**

Add all four new provider endpoints: `/providers/gemini/complete`, `/providers/ollama/complete`, `/providers/vllm/complete`, `/providers/github-copilot/complete`. Add them to the describe config too.

**Step 4: Run tests**

```bash
cd services/svc-providers && uv run pytest tests/ -v
```

**Step 5: Commit**

```bash
git add services/svc-providers/ && git commit -m "feat(svc-providers): add Gemini, Ollama, vLLM, and GitHub Copilot providers"
```

---

## Task 10: Generic Content Service Template

**Files:**
- Create: `services/svc-content-core/describe.yaml`
- Create: `services/svc-content-core/Dockerfile`

This task verifies the `amplifier-serve --config` pattern works for content-only services and creates the first content service as a template.

**Step 1: Test amplifier-serve --config works**

Run in the amplifier-service-sdk directory:
```bash
cd amplifier-service-sdk && uv run python -c "from amplifier_service_sdk.cli import load_config_from_yaml; print('CLI OK')"
```
Expected: prints "CLI OK".

**Step 2: Create the template Dockerfile**

Create `services/svc-content-core/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-content-core/describe.yaml /app/
COPY services/amplifier-core/src/amplifier_core/context/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
```

**Step 3: Create the template describe.yaml**

Create `services/svc-content-core/describe.yaml`:

```yaml
name: svc-content-core
version: '0.1.0'
content_dir: content
```

**Step 4: Verify locally**

Test the CLI can load the config:
```bash
cd services/svc-content-core && python -c "
from pathlib import Path
from amplifier_service_sdk.cli import load_config_from_yaml
config = load_config_from_yaml(Path('describe.yaml'))
print(f'Service: {config.name}, content_dir: {config.content_dir}')
"
```
Expected: prints service name and resolved content_dir.

**Step 5: Commit**

```bash
git add services/svc-content-core/ && git commit -m "feat(svc-content-core): add first content service using amplifier-serve template"
```

---

## Task 11: All 8 Content Services

**Files:**
- Create: `services/svc-content-amplifier/describe.yaml`
- Create: `services/svc-content-amplifier/Dockerfile`
- Create: `services/svc-content-browser-tester/describe.yaml`
- Create: `services/svc-content-browser-tester/Dockerfile`
- Create: `services/svc-content-design-intelligence/describe.yaml`
- Create: `services/svc-content-design-intelligence/Dockerfile`
- Create: `services/svc-content-filesystem/describe.yaml`
- Create: `services/svc-content-filesystem/Dockerfile`
- Create: `services/svc-content-recipes/describe.yaml`
- Create: `services/svc-content-recipes/Dockerfile`
- Create: `services/svc-content-superpowers/describe.yaml`
- Create: `services/svc-content-superpowers/Dockerfile`
- Create: `services/svc-content-system-design-intelligence/describe.yaml`
- Create: `services/svc-content-system-design-intelligence/Dockerfile`

**Step 1: Identify content directories for each service**

Check where each old service stores its content files. The pattern varies — some use `src/{name}/context/`, others may use `behaviors/` or other locations. You need to inspect each service directory:

- `services/amplifier-core/src/amplifier_core/context/` → svc-content-core (done in Task 10)
- `services/amplifier-amplifier/src/amplifier_amplifier/context/` → svc-content-amplifier
- `services/amplifier-browser-tester/src/amplifier_browser_tester/context/` → svc-content-browser-tester
- `services/amplifier-design-intelligence/src/amplifier_design_intelligence/context/` → svc-content-design-intelligence
- `services/amplifier-filesystem/src/amplifier_filesystem/context/` → svc-content-filesystem
- `services/amplifier-recipes/src/amplifier_recipes/context/` → svc-content-recipes
- `services/amplifier-superpowers/src/amplifier_superpowers/context/` → svc-content-superpowers
- `services/amplifier-system-design-intelligence/src/amplifier_system_design_intelligence/context/` → svc-content-system-design-intelligence

For each, inspect the directory to find the actual content location. If a service has no `context/` directory, check for other content directories or `.md`/`.yaml` files.

**Step 2: Create each content service**

For each service, create a `describe.yaml` and `Dockerfile` following the template from Task 10. Each `Dockerfile` COPYs from the old service's content directory:

```dockerfile
FROM amplifier-service-base

COPY services/svc-content-{name}/describe.yaml /app/
COPY services/amplifier-{name}/src/amplifier_{name}/context/ /app/content/

CMD ["amplifier-serve", "--config", "/app/describe.yaml"]
```

Each `describe.yaml`:
```yaml
name: svc-content-{name}
version: '0.1.0'
content_dir: content
```

**Step 3: Commit**

```bash
git add services/svc-content-*/ && git commit -m "feat(content-services): add all 8 content-only services using amplifier-serve template"
```

---

## Task 12: Docker Compose Update

**Files:**
- Modify: `docker-compose.yaml`

**Step 1: Read current docker-compose**

Read `docker-compose.yaml` to understand the existing pattern.

**Step 2: Add all new services**

Add the following service+sidecar pairs to `docker-compose.yaml`, following the exact same pattern as existing services:

**Tool services (with Dapr sidecars):**
- `svc-filesystem` + `svc-filesystem-dapr` — depends on `redis`, `svc-machine-dapr`
- `svc-search` + `svc-search-dapr` — depends on `redis`, `svc-machine-dapr`
- `svc-web` + `svc-web-dapr` — depends on `redis`
- `svc-skills` + `svc-skills-dapr` — depends on `redis`
- `svc-todo` + `svc-todo-dapr` — depends on `redis`
- `svc-modes` + `svc-modes-dapr` — depends on `redis`

**Provider service (with Dapr sidecar):**
- `svc-providers` + `svc-providers-dapr` — depends on `redis`, needs environment vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (optional, from host env)

**Content services (with Dapr sidecars):**
- `svc-content-core` + `svc-content-core-dapr`
- `svc-content-amplifier` + `svc-content-amplifier-dapr`
- `svc-content-browser-tester` + `svc-content-browser-tester-dapr`
- `svc-content-design-intelligence` + `svc-content-design-intelligence-dapr`
- `svc-content-filesystem` + `svc-content-filesystem-dapr`
- `svc-content-recipes` + `svc-content-recipes-dapr`
- `svc-content-superpowers` + `svc-content-superpowers-dapr`
- `svc-content-system-design-intelligence` + `svc-content-system-design-intelligence-dapr`

Each follows this template:

```yaml
  svc-filesystem:
    build:
      context: .
      dockerfile: services/svc-filesystem/Dockerfile
    environment:
      DAPR_HTTP_PORT: "3500"
    depends_on:
      - redis
      - svc-machine-dapr

  svc-filesystem-dapr:
    image: daprio/daprd:1.14.4
    command:
      - ./daprd
      - --app-id=svc-filesystem
      - --app-port=8000
      - --dapr-http-port=3500
      - --dapr-grpc-port=50001
      - --resources-path=/components
      - --config=/config/config.yaml
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr:/config
    network_mode: "service:svc-filesystem"
    depends_on:
      - svc-filesystem
```

**Step 3: Update session-service dependencies**

Update the session-service `depends_on` to include the new Dapr sidecars:

```yaml
  session-service:
    depends_on:
      - redis
      - svc-machine-dapr
      - svc-bash-dapr
      - svc-filesystem-dapr
      - svc-search-dapr
      - svc-web-dapr
      - svc-skills-dapr
      - svc-todo-dapr
      - svc-modes-dapr
      - svc-context-dapr
      - svc-mock-provider-dapr
      - svc-providers-dapr
      - svc-orchestrator-dapr
```

**Step 4: Commit**

```bash
git add docker-compose.yaml && git commit -m "feat(docker): add all Phase 3a services to docker-compose.yaml"
```

---

## Task 13: Update session-service for New Services

**Files:**
- Modify: `services/session-service/src/session_service/app.py`
- Modify: `services/session-service/src/session_service/discovery.py`
- Create: `services/session-service/tests/test_discovery_phase3a.py`

**Step 1: Write the failing test**

Create `services/session-service/tests/test_discovery_phase3a.py`:

```python
"""Tests for Phase 3a service discovery — verifying new services are discovered."""

from __future__ import annotations

from typing import Any

import pytest

from session_service.discovery import build_routing_table


class TestBuildRoutingTablePhase3a:
    """Verify routing table builds correctly with Phase 3a services."""

    def test_routes_filesystem_tools(self) -> None:
        """Filesystem tools are routed to svc-filesystem."""
        describe_results: dict[str, dict[str, Any]] = {
            "svc-filesystem": {
                "tools": [
                    {"name": "read_file", "description": "Read a file"},
                    {"name": "write_file", "description": "Write a file"},
                    {"name": "edit_file", "description": "Edit a file"},
                ],
            },
            "svc-search": {
                "tools": [
                    {"name": "grep", "description": "Search files"},
                    {"name": "glob", "description": "Glob files"},
                ],
            },
            "svc-providers": {
                "providers": [
                    {"name": "anthropic", "description": "Anthropic"},
                    {"name": "openai", "description": "OpenAI"},
                ],
            },
        }
        rt = build_routing_table(describe_results, "svc-context")

        assert rt["tools"]["read_file"] == "svc-filesystem"
        assert rt["tools"]["write_file"] == "svc-filesystem"
        assert rt["tools"]["grep"] == "svc-search"
        assert rt["providers"]["anthropic"] == "svc-providers"
        assert rt["providers"]["openai"] == "svc-providers"
        assert rt["context"] == "svc-context"
```

**Step 2: Run tests to verify routing table logic already works**

The existing `build_routing_table` function in `services/session-service/src/session_service/discovery.py` already handles arbitrary services generically — it iterates describe results and maps tool names to app-ids. No code changes should be needed for the routing table builder itself.

```bash
cd services/session-service && uv run pytest tests/test_discovery_phase3a.py -v
```
Expected: PASS (the routing table logic is already generic).

**Step 3: Update default services list**

If the session-service has a hardcoded list of services to discover, update it to include the new service app-ids. Check `services/session-service/src/session_service/app.py` — the `TurnRequest.services` field is a list passed by the caller. The session-service itself doesn't hardcode service names (the caller provides them in the `services` field of `TurnRequest`).

If there's a default services list, update it:

```python
# In TurnRequest or in the turn handler, if there's a default:
DEFAULT_SERVICES = [
    "svc-bash",
    "svc-filesystem",
    "svc-search",
    "svc-web",
    "svc-skills",
    "svc-todo",
    "svc-modes",
    "svc-mock-provider",
    "svc-providers",
]
```

If the `TurnRequest.services` list is empty (default), the turn handler should use the default list. Add this logic if not already present.

**Step 4: Commit**

```bash
git add services/session-service/ && git commit -m "feat(session-service): add Phase 3a discovery test and default services list"
```

---

## Task 14: Integration Test

**Files:**
- Create: `tests/integration/test_phase3a_integration.py`

**Step 1: Write the integration test**

Create `tests/integration/test_phase3a_integration.py`:

```python
"""Phase 3a integration test — in-process end-to-end with real tool services.

Tests the full stack:
1. Session service receives prompt
2. Discovery calls /describe on all services
3. Orchestrator dispatches tool calls to svc-filesystem, svc-search
4. Content services respond to /describe and /content/{path}
5. Full round-trip returns result

All services run in-process using TestClient — no Docker required.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

# Import all app factories
from svc_filesystem.app import create_filesystem_app
from svc_search.app import create_search_app
from svc_web.app import create_web_app
from svc_todo.app import create_todo_app
from svc_modes.app import create_modes_app


class TestPhase3aToolServices:
    """Verify each tool service works end-to-end."""

    def test_filesystem_describe(self) -> None:
        app = create_filesystem_app(machine_base_url="http://fake:8080")
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert tool_names == {"read_file", "write_file", "edit_file"}

    def test_search_describe(self) -> None:
        app = create_search_app(machine_base_url="http://fake:8080")
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert tool_names == {"grep", "glob"}

    def test_web_describe(self) -> None:
        app = create_web_app()
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert tool_names == {"web_search", "web_fetch"}

    def test_todo_describe(self) -> None:
        app = create_todo_app()
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert "todo" in tool_names

    def test_modes_describe(self) -> None:
        app = create_modes_app()
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        assert "mode" in tool_names

    def test_todo_create_and_list(self) -> None:
        """End-to-end: create todos via HTTP, then list them."""
        app = create_todo_app()
        client = TestClient(app)

        # Create
        response = client.post(
            "/tools/todo/execute",
            json={
                "name": "todo",
                "input": {
                    "action": "create",
                    "todos": [
                        {
                            "content": "Test task",
                            "activeForm": "Testing",
                            "status": "pending",
                        }
                    ],
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # List
        response = client.post(
            "/tools/todo/execute",
            json={"name": "todo", "input": {"action": "list"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["output"]["count"] == 1


class TestPhase3aProviderService:
    """Verify provider service /describe works."""

    def test_providers_describe(self) -> None:
        from svc_providers.app import create_providers_app

        app = create_providers_app()
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        provider_names = {p["name"] for p in data["providers"]}
        assert "anthropic" in provider_names
        assert "openai" in provider_names
```

**Step 2: Run the integration test**

```bash
PYTHONPATH=services/svc-filesystem/src:services/svc-search/src:services/svc-web/src:services/svc-todo/src:services/svc-modes/src:services/svc-skills/src:services/svc-providers/src:services/session-service/src:amplifier-service-sdk/src \
  python -m pytest tests/integration/test_phase3a_integration.py -v
```
Expected: All tests PASS.

**Step 3: Commit**

```bash
git add tests/integration/ && git commit -m "test(phase3a): add integration tests for all Phase 3a services"
```

---

## Summary

| Task | Service | Tests | Key Pattern |
|------|---------|-------|-------------|
| 1 | svc-filesystem | ~12 | Calls svc-machine /files/* |
| 2 | svc-search | ~8 | Calls svc-machine /files/grep, /files/glob |
| 3 | svc-web | ~8 | Self-contained (aiohttp, DuckDuckGo) |
| 4 | svc-skills | ~8 | Self-contained (YAML/MD discovery) |
| 5 | svc-todo | ~10 | In-process hooks (stubs) |
| 6 | svc-modes | ~10 | In-process hook (ModeHooks) |
| 7 | svc-providers (Anthropic) | ~5 | BaseProvider + Anthropic |
| 8 | svc-providers (+OpenAI/Azure) | ~3 | OpenAI + Azure providers |
| 9 | svc-providers (+remaining) | ~4 | Gemini, Ollama, vLLM, Copilot |
| 10 | Content template | ~1 | amplifier-serve --config |
| 11 | 8 content services | 0 | Stamp from template |
| 12 | Docker Compose | 0 | Add all services + sidecars |
| 13 | session-service update | ~3 | Discovery + default services |
| 14 | Integration test | ~8 | In-process end-to-end |

**Estimated total: ~80 new tests across 14 tasks.**
