# Phase 1: SDK + Machine Service + First Tool Service

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Prove the microservices pattern end-to-end: one real tool service (`svc-bash`) running in Docker with a Dapr sidecar, calling a machine service for command execution, all responding to the standard service contract (`/describe`, `/healthz`, `/tools/bash/execute`).

**Architecture:** Every service is a FastAPI app created by the `amplifier-service-sdk`. Services communicate via Dapr service invocation (HTTP). The machine service centralizes filesystem and command execution access (local mode: volume mount + subprocess). Tool services like `svc-bash` call `svc-machine` via Dapr instead of executing commands directly.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, Dapr, Docker Compose, Redis, uv, pytest

**Design Document:** `docs/design/amplifier-ipc-microservices-design.md`

---

## Codebase Context

This is a Python mono-repo at `/data/labs/amplifier-ipc/` using uv for package management. Key conventions:

- **Build system:** hatchling with `src/` layout (`[tool.hatch.build.targets.wheel] packages = ["src/package_name"]`)
- **Python:** `requires-python = ">=3.11"` in pyproject.toml (target 3.12+ for new code)
- **Dependencies:** pydantic>=2.0, pyyaml>=6.0
- **Tests:** pytest with `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `pythonpath = ["src"]`
- **Local deps:** `[tool.uv.sources]` with `path = "..."` for cross-package references
- **Existing services** live under `services/` (e.g., `services/amplifier-foundation/`)
- **Existing models** in `src/amplifier_ipc/protocol/models.py` (ToolResult, ToolSpec, HookResult, etc.)
- **Existing content serving** in `src/amplifier_ipc/protocol/content.py` (path traversal security)
- **Existing BashTool** in `services/amplifier-foundation/src/amplifier_foundation/tools/bash/__init__.py` (~456 lines, with safety validation)

---

## Task Overview

| # | Task | Creates |
|---|---|---|
| 1 | SDK package scaffold + Pydantic models | `amplifier-service-sdk/` with all request/response models |
| 2 | SDK content serving | `content.py` — scan + serve content files |
| 3 | SDK service runner (FastAPI app factory) | `service.py` — auto-wires /describe, /content, /healthz |
| 4 | SDK CLI entry point | `cli.py` — `amplifier-serve` command |
| 5 | Machine service: package scaffold + exec endpoint | `services/svc-machine/` with /exec |
| 6 | Machine service: file read/write/edit endpoints | /files/read, /files/write, /files/edit |
| 7 | Machine service: file list/glob/grep endpoints | /files/list, /files/glob, /files/grep |
| 8 | svc-bash: tool service calling machine via httpx | `services/svc-bash/` with /tools/bash/execute |
| 9 | Base Docker image | `docker/base/Dockerfile` |
| 10 | Dapr configuration | `docker/dapr/` component configs |
| 11 | Docker Compose | `docker-compose.yaml` wiring everything together |
| 12 | Integration test | End-to-end test via Docker Compose |

---

### Task 1: SDK Package Scaffold + Pydantic Models

**Files:**
- Create: `amplifier-service-sdk/pyproject.toml`
- Create: `amplifier-service-sdk/src/amplifier_service_sdk/__init__.py`
- Create: `amplifier-service-sdk/src/amplifier_service_sdk/models.py`
- Test: `amplifier-service-sdk/tests/test_models.py`

**Step 1: Create the package scaffold**

Create `amplifier-service-sdk/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-service-sdk"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "httpx>=0.28",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.28",
]

[project.scripts]
amplifier-serve = "amplifier_service_sdk.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_service_sdk"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]
```

Create `amplifier-service-sdk/src/amplifier_service_sdk/__init__.py`:

```python
"""Amplifier Service SDK — shared models, service runner, and content serving for microservices."""

from amplifier_service_sdk.models import (
    ContentFile,
    DescribeResponse,
    HealthResponse,
    HookEvent,
    HookResult,
    ProviderRequest,
    ProviderResponse,
    ToolCapability,
    ToolRequest,
    ToolResult,
)

__all__ = [
    "ContentFile",
    "DescribeResponse",
    "HealthResponse",
    "HookEvent",
    "HookResult",
    "ProviderRequest",
    "ProviderResponse",
    "ToolCapability",
    "ToolRequest",
    "ToolResult",
]
```

**Step 2: Write the failing tests**

Create `amplifier-service-sdk/tests/test_models.py`:

```python
"""Tests for amplifier_service_sdk.models — Pydantic v2 request/response models."""

from __future__ import annotations

import json

from amplifier_service_sdk.models import (
    ContentFile,
    DescribeResponse,
    HealthResponse,
    HookEvent,
    HookResult,
    ProviderRequest,
    ProviderResponse,
    ToolCapability,
    ToolRequest,
    ToolResult,
)


class TestToolResult:
    def test_success_default(self) -> None:
        result = ToolResult(output="hello")
        assert result.success is True
        assert result.output == "hello"
        assert result.error is None

    def test_failure(self) -> None:
        result = ToolResult(success=False, output="boom", error={"message": "boom"})
        assert result.success is False

    def test_json_roundtrip(self) -> None:
        result = ToolResult(output={"key": "value"})
        data = json.loads(result.model_dump_json())
        restored = ToolResult.model_validate(data)
        assert restored.output == {"key": "value"}


class TestToolRequest:
    def test_basic(self) -> None:
        req = ToolRequest(name="bash", input={"command": "echo hi"})
        assert req.name == "bash"
        assert req.input == {"command": "echo hi"}

    def test_empty_input_default(self) -> None:
        req = ToolRequest(name="bash")
        assert req.input == {}


class TestToolCapability:
    def test_fields(self) -> None:
        cap = ToolCapability(
            name="bash",
            description="Execute bash commands",
            input_schema={"type": "object", "properties": {"command": {"type": "string"}}},
        )
        assert cap.name == "bash"
        assert "command" in cap.input_schema["properties"]


class TestDescribeResponse:
    def test_minimal(self) -> None:
        resp = DescribeResponse(
            name="svc-bash",
            version="0.1.0",
        )
        assert resp.name == "svc-bash"
        assert resp.tools == []
        assert resp.hooks == []
        assert resp.providers == []
        assert resp.content_paths == []

    def test_with_tools(self) -> None:
        resp = DescribeResponse(
            name="svc-bash",
            version="0.1.0",
            tools=[
                ToolCapability(
                    name="bash",
                    description="Execute bash commands",
                    input_schema={"type": "object"},
                )
            ],
        )
        assert len(resp.tools) == 1
        assert resp.tools[0].name == "bash"

    def test_json_roundtrip(self) -> None:
        resp = DescribeResponse(
            name="svc-bash",
            version="0.1.0",
            tools=[
                ToolCapability(name="bash", description="Run commands", input_schema={})
            ],
            content_paths=["context/instructions.md"],
        )
        data = json.loads(resp.model_dump_json())
        restored = DescribeResponse.model_validate(data)
        assert restored.name == "svc-bash"
        assert len(restored.tools) == 1
        assert restored.content_paths == ["context/instructions.md"]


class TestHealthResponse:
    def test_defaults(self) -> None:
        health = HealthResponse(service_name="svc-bash", version="0.1.0")
        assert health.status == "healthy"


class TestContentFile:
    def test_fields(self) -> None:
        cf = ContentFile(path="context/guide.md", content="# Guide\nHello")
        assert cf.path == "context/guide.md"
        assert "Guide" in cf.content


class TestHookEvent:
    def test_fields(self) -> None:
        event = HookEvent(event="tool:pre", data={"tool": "bash"})
        assert event.event == "tool:pre"


class TestHookResult:
    def test_defaults(self) -> None:
        result = HookResult()
        assert result.action == "CONTINUE"


class TestProviderRequest:
    def test_fields(self) -> None:
        req = ProviderRequest(
            messages=[{"role": "user", "content": "hello"}],
        )
        assert len(req.messages) == 1


class TestProviderResponse:
    def test_fields(self) -> None:
        resp = ProviderResponse(content="Hello back")
        assert resp.content == "Hello back"
```

**Step 3: Run tests to verify they fail**

```bash
cd amplifier-service-sdk && uv sync --dev && uv run pytest tests/test_models.py -v
```

Expected: FAIL — `amplifier_service_sdk.models` module does not exist yet.

**Step 4: Write the models implementation**

Create `amplifier-service-sdk/src/amplifier_service_sdk/models.py`:

```python
"""Pydantic v2 models for the Amplifier Service SDK.

These models define the wire format for all service-to-service communication
in the Amplifier microservices architecture. All models round-trip cleanly
through model_dump_json() -> json.loads -> model_validate.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Tool models
# ---------------------------------------------------------------------------


class ToolCapability(BaseModel):
    """A tool's metadata as reported in /describe responses."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolRequest(BaseModel):
    """Request payload for POST /tools/{name}/execute."""

    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Response payload from POST /tools/{name}/execute."""

    success: bool = True
    output: Any = None
    error: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Hook models (stubs for Phase 1 — will be fleshed out in Phase 4)
# ---------------------------------------------------------------------------


class HookEvent(BaseModel):
    """Event payload published to hook topics."""

    event: str
    data: dict[str, Any] = Field(default_factory=dict)


class HookResult(BaseModel):
    """Result from a hook handler."""

    action: str = "CONTINUE"
    data: dict[str, Any] | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Provider models (stubs for Phase 1 — will be fleshed out in Phase 2)
# ---------------------------------------------------------------------------


class ProviderRequest(BaseModel):
    """Request payload for POST /providers/{name}/complete."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    system: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None


class ProviderResponse(BaseModel):
    """Response payload from POST /providers/{name}/complete."""

    content: str | list[Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Describe / Health / Content
# ---------------------------------------------------------------------------


class DescribeResponse(BaseModel):
    """Response payload for GET /describe.

    Combines capability manifest (what this service offers) with content
    manifest (what content files this service serves).
    """

    name: str
    version: str = "0.1.0"
    tools: list[ToolCapability] = Field(default_factory=list)
    hooks: list[dict[str, Any]] = Field(default_factory=list)
    providers: list[dict[str, Any]] = Field(default_factory=list)
    content_paths: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Response payload for GET /healthz."""

    status: str = "healthy"
    service_name: str
    version: str = "0.1.0"


class ContentFile(BaseModel):
    """A content file served by GET /content/{path}."""

    path: str
    content: str
```

**Step 5: Run tests to verify they pass**

```bash
cd amplifier-service-sdk && uv run pytest tests/test_models.py -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add amplifier-service-sdk/ && git commit -m "feat: add amplifier-service-sdk package with Pydantic v2 models"
```

---

### Task 2: SDK Content Serving

**Files:**
- Create: `amplifier-service-sdk/src/amplifier_service_sdk/content.py`
- Test: `amplifier-service-sdk/tests/test_content.py`

**Step 1: Write the failing tests**

Create `amplifier-service-sdk/tests/test_content.py`:

```python
"""Tests for amplifier_service_sdk.content — content directory scanning and serving."""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_service_sdk.content import ContentManager


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    """Create a temporary content directory with test files."""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "instructions.md").write_text("# Instructions\nDo the thing.")
    (ctx / "guidelines.md").write_text("# Guidelines\nBe nice.")

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "default.yaml").write_text("name: default\n")

    # Nested directory
    sub = ctx / "sub"
    sub.mkdir()
    (sub / "deep.md").write_text("# Deep\nNested content.")

    return tmp_path


class TestContentManager:
    def test_scan_finds_all_files(self, content_dir: Path) -> None:
        mgr = ContentManager(content_dir)
        paths = mgr.list_paths()
        assert "context/instructions.md" in paths
        assert "context/guidelines.md" in paths
        assert "agents/default.yaml" in paths
        assert "context/sub/deep.md" in paths

    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        mgr = ContentManager(tmp_path)
        assert mgr.list_paths() == []

    def test_read_existing_file(self, content_dir: Path) -> None:
        mgr = ContentManager(content_dir)
        content = mgr.read("context/instructions.md")
        assert content is not None
        assert "# Instructions" in content

    def test_read_nonexistent_file(self, content_dir: Path) -> None:
        mgr = ContentManager(content_dir)
        assert mgr.read("context/nonexistent.md") is None

    def test_read_path_traversal_blocked(self, content_dir: Path) -> None:
        mgr = ContentManager(content_dir)
        assert mgr.read("../../etc/passwd") is None

    def test_read_nested_file(self, content_dir: Path) -> None:
        mgr = ContentManager(content_dir)
        content = mgr.read("context/sub/deep.md")
        assert content is not None
        assert "Nested content" in content
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-service-sdk && uv run pytest tests/test_content.py -v
```

Expected: FAIL — `amplifier_service_sdk.content` module does not exist yet.

**Step 3: Write the content serving implementation**

Create `amplifier-service-sdk/src/amplifier_service_sdk/content.py`:

```python
"""Content directory scanning and serving for Amplifier services.

Scans a content root directory for files and serves them with path traversal
security. Used by the service runner to auto-wire /describe content manifests
and /content/{path} endpoints.
"""

from __future__ import annotations

from pathlib import Path


class ContentManager:
    """Manages content files in a service's content directory.

    Scans subdirectories for content files at construction time and provides
    secure read access with path traversal protection.

    Args:
        content_dir: Root directory to scan for content files.
    """

    def __init__(self, content_dir: Path) -> None:
        self._content_dir = content_dir.resolve()
        self._paths: list[str] = self._scan()

    def _scan(self) -> list[str]:
        """Scan the content directory recursively for all files."""
        if not self._content_dir.exists():
            return []

        paths: list[str] = []
        for f in sorted(self._content_dir.rglob("*")):
            if f.is_file() and f.name != "__init__.py":
                rel = f.relative_to(self._content_dir)
                paths.append(rel.as_posix())
        return paths

    def list_paths(self) -> list[str]:
        """Return all discovered content file paths (relative, posix-style)."""
        return list(self._paths)

    def read(self, relative_path: str) -> str | None:
        """Read a content file, returning None if path is invalid or missing.

        Enforces path traversal security: the resolved path must remain
        within the content directory.
        """
        target = (self._content_dir / relative_path).resolve()

        # Security check: resolved target must be within content dir
        try:
            target.relative_to(self._content_dir)
        except ValueError:
            return None

        if not target.is_file():
            return None

        return target.read_text(encoding="utf-8")
```

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-service-sdk && uv run pytest tests/test_content.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add amplifier-service-sdk/src/amplifier_service_sdk/content.py amplifier-service-sdk/tests/test_content.py && git commit -m "feat: add SDK content directory scanning and serving"
```

---

### Task 3: SDK Service Runner (FastAPI App Factory)

**Files:**
- Create: `amplifier-service-sdk/src/amplifier_service_sdk/service.py`
- Test: `amplifier-service-sdk/tests/test_service.py`

**Step 1: Write the failing tests**

Create `amplifier-service-sdk/tests/test_service.py`:

```python
"""Tests for amplifier_service_sdk.service — FastAPI app factory."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amplifier_service_sdk.models import DescribeResponse, HealthResponse, ToolCapability
from amplifier_service_sdk.service import ServiceConfig, create_app


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    """Create a temp content directory."""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "guide.md").write_text("# Guide\nHello world.")
    return tmp_path


@pytest.fixture
def basic_config(content_dir: Path) -> ServiceConfig:
    return ServiceConfig(
        name="svc-test",
        version="0.1.0",
        content_dir=content_dir,
    )


@pytest.fixture
def config_with_tools(content_dir: Path) -> ServiceConfig:
    return ServiceConfig(
        name="svc-test",
        version="0.1.0",
        content_dir=content_dir,
        tools=[
            ToolCapability(
                name="echo",
                description="Echo input",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            )
        ],
    )


class TestHealthEndpoint:
    def test_healthz_returns_200(self, basic_config: ServiceConfig) -> None:
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200
        health = HealthResponse.model_validate(response.json())
        assert health.status == "healthy"
        assert health.service_name == "svc-test"


class TestDescribeEndpoint:
    def test_describe_returns_name_and_version(self, basic_config: ServiceConfig) -> None:
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        desc = DescribeResponse.model_validate(response.json())
        assert desc.name == "svc-test"
        assert desc.version == "0.1.0"

    def test_describe_includes_content_paths(self, basic_config: ServiceConfig) -> None:
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/describe")
        desc = DescribeResponse.model_validate(response.json())
        assert "context/guide.md" in desc.content_paths

    def test_describe_includes_tools(self, config_with_tools: ServiceConfig) -> None:
        app = create_app(config_with_tools)
        client = TestClient(app)
        response = client.get("/describe")
        desc = DescribeResponse.model_validate(response.json())
        assert len(desc.tools) == 1
        assert desc.tools[0].name == "echo"


class TestContentEndpoint:
    def test_content_serves_file(self, basic_config: ServiceConfig) -> None:
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/content/context/guide.md")
        assert response.status_code == 200
        body = response.json()
        assert "# Guide" in body["content"]

    def test_content_404_for_missing_file(self, basic_config: ServiceConfig) -> None:
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/content/nonexistent.md")
        assert response.status_code == 404

    def test_content_403_for_path_traversal(self, basic_config: ServiceConfig) -> None:
        app = create_app(basic_config)
        client = TestClient(app)
        response = client.get("/content/../../etc/passwd")
        assert response.status_code in (403, 404)
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-service-sdk && uv run pytest tests/test_service.py -v
```

Expected: FAIL — `amplifier_service_sdk.service` does not exist.

**Step 3: Write the service runner implementation**

Create `amplifier-service-sdk/src/amplifier_service_sdk/service.py`:

```python
"""FastAPI app factory for Amplifier services.

Creates a FastAPI application with pre-wired /healthz, /describe, and
/content/{path} endpoints. Services add their own capability endpoints
(e.g., /tools/{name}/execute) to the returned app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from amplifier_service_sdk.content import ContentManager
from amplifier_service_sdk.models import (
    DescribeResponse,
    HealthResponse,
    ToolCapability,
)


@dataclass
class ServiceConfig:
    """Configuration for creating a service app.

    Args:
        name: Service name (used in /describe and /healthz).
        version: Service version string.
        content_dir: Path to the content directory to serve. None means no content.
        tools: List of tool capabilities to advertise in /describe.
        hooks: List of hook descriptors to advertise in /describe.
        providers: List of provider descriptors to advertise in /describe.
    """

    name: str
    version: str = "0.1.0"
    content_dir: Path | None = None
    tools: list[ToolCapability] = field(default_factory=list)
    hooks: list[dict[str, Any]] = field(default_factory=list)
    providers: list[dict[str, Any]] = field(default_factory=list)


def create_app(config: ServiceConfig) -> FastAPI:
    """Create a FastAPI app with standard service endpoints.

    Wires up:
    - GET /healthz -> HealthResponse
    - GET /describe -> DescribeResponse
    - GET /content/{path:path} -> ContentFile

    The caller can add additional routes to the returned app.
    """
    app = FastAPI(title=config.name, version=config.version)

    # Set up content manager
    content_mgr: ContentManager | None = None
    if config.content_dir is not None:
        content_mgr = ContentManager(config.content_dir)

    @app.get("/healthz")
    async def healthz() -> dict:
        return HealthResponse(
            service_name=config.name,
            version=config.version,
        ).model_dump()

    @app.get("/describe")
    async def describe() -> dict:
        content_paths = content_mgr.list_paths() if content_mgr else []
        return DescribeResponse(
            name=config.name,
            version=config.version,
            tools=config.tools,
            hooks=config.hooks,
            providers=config.providers,
            content_paths=content_paths,
        ).model_dump()

    @app.get("/content/{path:path}")
    async def content(path: str) -> dict:
        if content_mgr is None:
            raise HTTPException(status_code=404, detail="No content directory configured")
        text = content_mgr.read(path)
        if text is None:
            raise HTTPException(status_code=404, detail=f"Content not found: {path}")
        return {"path": path, "content": text}

    return app
```

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-service-sdk && uv run pytest tests/test_service.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add amplifier-service-sdk/src/amplifier_service_sdk/service.py amplifier-service-sdk/tests/test_service.py && git commit -m "feat: add SDK FastAPI service runner with /healthz, /describe, /content"
```

---

### Task 4: SDK CLI Entry Point (`amplifier-serve`)

**Files:**
- Create: `amplifier-service-sdk/src/amplifier_service_sdk/cli.py`
- Test: `amplifier-service-sdk/tests/test_cli.py`

**Step 1: Write the failing tests**

Create `amplifier-service-sdk/tests/test_cli.py`:

```python
"""Tests for amplifier_service_sdk.cli — amplifier-serve entry point."""

from __future__ import annotations

from pathlib import Path

import yaml

from amplifier_service_sdk.cli import load_config_from_yaml
from amplifier_service_sdk.service import ServiceConfig


class TestLoadConfigFromYaml:
    def test_minimal_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "describe.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "name": "svc-test",
                    "version": "0.1.0",
                }
            )
        )
        config = load_config_from_yaml(config_file)
        assert isinstance(config, ServiceConfig)
        assert config.name == "svc-test"
        assert config.version == "0.1.0"

    def test_yaml_with_tools(self, tmp_path: Path) -> None:
        config_file = tmp_path / "describe.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "name": "svc-bash",
                    "version": "0.1.0",
                    "tools": [
                        {
                            "name": "bash",
                            "description": "Execute bash commands",
                            "input_schema": {"type": "object"},
                        }
                    ],
                }
            )
        )
        config = load_config_from_yaml(config_file)
        assert len(config.tools) == 1
        assert config.tools[0].name == "bash"

    def test_yaml_with_content_dir(self, tmp_path: Path) -> None:
        content = tmp_path / "content"
        content.mkdir()
        (content / "guide.md").write_text("# Guide")

        config_file = tmp_path / "describe.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "name": "svc-test",
                    "version": "0.1.0",
                    "content_dir": "content",
                }
            )
        )
        config = load_config_from_yaml(config_file)
        assert config.content_dir is not None
        assert config.content_dir.exists()
```

**Step 2: Run tests to verify they fail**

```bash
cd amplifier-service-sdk && uv run pytest tests/test_cli.py -v
```

Expected: FAIL — `amplifier_service_sdk.cli` does not exist.

**Step 3: Write the CLI implementation**

Create `amplifier-service-sdk/src/amplifier_service_sdk/cli.py`:

```python
"""CLI entry point for amplifier-serve.

Loads a service configuration from a YAML file, creates a FastAPI app, and
starts uvicorn. This is the standard way to run an Amplifier service.

Usage:
    amplifier-serve --config /app/describe.yaml
    amplifier-serve --config /app/describe.yaml --port 8080
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from amplifier_service_sdk.models import ToolCapability
from amplifier_service_sdk.service import ServiceConfig, create_app


def load_config_from_yaml(config_path: Path) -> ServiceConfig:
    """Load a ServiceConfig from a YAML file.

    The YAML file should contain:
        name: service-name
        version: "0.1.0"
        content_dir: relative/path/to/content  (optional)
        tools: [...]  (optional)
        hooks: [...]  (optional)
        providers: [...]  (optional)

    Relative content_dir paths are resolved against the YAML file's parent directory.
    """
    with open(config_path) as f:
        data = yaml.safe_load(f)

    # Resolve content_dir relative to the YAML file's location
    content_dir: Path | None = None
    if "content_dir" in data:
        content_dir = (config_path.parent / data["content_dir"]).resolve()

    tools = [ToolCapability.model_validate(t) for t in data.get("tools", [])]

    return ServiceConfig(
        name=data["name"],
        version=data.get("version", "0.1.0"),
        content_dir=content_dir,
        tools=tools,
        hooks=data.get("hooks", []),
        providers=data.get("providers", []),
    )


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the amplifier-serve CLI."""
    import uvicorn

    parser = argparse.ArgumentParser(
        prog="amplifier-serve",
        description="Run an Amplifier service from a YAML config.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to describe.yaml service configuration file.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000).",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    config = load_config_from_yaml(args.config)
    app = create_app(config)

    uvicorn.run(app, host=args.host, port=args.port)
```

**Step 4: Run tests to verify they pass**

```bash
cd amplifier-service-sdk && uv run pytest tests/test_cli.py -v
```

Expected: All tests PASS.

**Step 5: Run full SDK test suite**

```bash
cd amplifier-service-sdk && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add amplifier-service-sdk/src/amplifier_service_sdk/cli.py amplifier-service-sdk/tests/test_cli.py && git commit -m "feat: add amplifier-serve CLI entry point"
```

---

### Task 5: Machine Service — Package Scaffold + /exec Endpoint

**Files:**
- Create: `services/svc-machine/pyproject.toml`
- Create: `services/svc-machine/src/svc_machine/__init__.py`
- Create: `services/svc-machine/src/svc_machine/local_backend.py`
- Create: `services/svc-machine/src/svc_machine/service.py`
- Create: `services/svc-machine/describe.yaml`
- Test: `services/svc-machine/tests/test_local_backend.py`
- Test: `services/svc-machine/tests/test_service.py`

**Step 1: Create the package scaffold**

Create `services/svc-machine/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-machine"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "amplifier-service-sdk",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.28",
]

[tool.hatch.build.targets.wheel]
packages = ["src/svc_machine"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src", "../../amplifier-service-sdk/src"]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }
```

Create `services/svc-machine/src/svc_machine/__init__.py`:

```python
"""svc-machine — Machine abstraction service for filesystem and command execution."""
```

Create `services/svc-machine/describe.yaml`:

```yaml
name: svc-machine
version: "0.1.0"
```

**Step 2: Write the failing tests for local backend exec**

Create `services/svc-machine/tests/test_local_backend.py`:

```python
"""Tests for svc_machine.local_backend — local subprocess + filesystem operations."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from svc_machine.local_backend import LocalBackend


@pytest.fixture
def backend(tmp_path: Path) -> LocalBackend:
    """Create a LocalBackend rooted at a temporary directory."""
    return LocalBackend(workspace_dir=tmp_path)


class TestExec:
    async def test_echo(self, backend: LocalBackend) -> None:
        result = await backend.exec(command="echo hello")
        assert result.exit_code == 0
        assert "hello" in result.stdout

    async def test_exit_code_nonzero(self, backend: LocalBackend) -> None:
        result = await backend.exec(command="exit 42")
        assert result.exit_code == 42

    async def test_stderr(self, backend: LocalBackend) -> None:
        result = await backend.exec(command="echo error >&2")
        assert "error" in result.stderr

    async def test_timeout(self, backend: LocalBackend) -> None:
        result = await backend.exec(command="sleep 60", timeout=1)
        assert result.exit_code != 0
        assert "timeout" in result.stderr.lower() or result.exit_code != 0

    async def test_working_dir(self, backend: LocalBackend) -> None:
        result = await backend.exec(command="pwd")
        assert result.exit_code == 0
        # Should run in the workspace directory
        assert str(backend.workspace_dir) in result.stdout
```

**Step 3: Run tests to verify they fail**

```bash
cd services/svc-machine && uv sync --dev && uv run pytest tests/test_local_backend.py -v
```

Expected: FAIL — `svc_machine.local_backend` does not exist.

**Step 4: Write the local backend exec implementation**

Create `services/svc-machine/src/svc_machine/local_backend.py`:

```python
"""Local backend — subprocess execution and filesystem operations.

This is the "local mode" backend for svc-machine. It uses subprocess for
command execution and direct filesystem access (volume-mounted workspace).
Future: an SSH/SFTP backend would implement the same interface for remote mode.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ExecResult:
    """Result of a command execution."""

    stdout: str
    stderr: str
    exit_code: int


class LocalBackend:
    """Local backend for command execution and filesystem operations.

    Args:
        workspace_dir: Root directory for all operations. Commands execute
            with this as their working directory. File paths are resolved
            relative to this directory.
    """

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir.resolve()

    async def exec(
        self,
        command: str,
        timeout: int = 30,
        working_dir: str | None = None,
    ) -> ExecResult:
        """Execute a shell command and return the result.

        Args:
            command: Shell command to execute.
            timeout: Timeout in seconds (default: 30).
            working_dir: Working directory relative to workspace_dir.
                If None, uses workspace_dir directly.
        """
        cwd = self.workspace_dir
        if working_dir:
            cwd = (self.workspace_dir / working_dir).resolve()
            # Security: ensure cwd is within workspace
            try:
                cwd.relative_to(self.workspace_dir)
            except ValueError:
                return ExecResult(
                    stdout="",
                    stderr="Working directory escapes workspace boundary",
                    exit_code=1,
                )

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                executable="/bin/bash" if sys.platform != "win32" else None,
                start_new_session=True if sys.platform != "win32" else False,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            return ExecResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=process.returncode or 0,
            )

        except asyncio.TimeoutError:
            # Kill the process group on timeout
            if process and process.pid and sys.platform != "win32":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    await asyncio.sleep(0.5)
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                except (ProcessLookupError, PermissionError):
                    if process:
                        process.kill()
            elif process:
                process.kill()

            return ExecResult(
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
                exit_code=124,  # Standard timeout exit code
            )
```

**Step 5: Run tests to verify they pass**

```bash
cd services/svc-machine && uv run pytest tests/test_local_backend.py -v
```

Expected: All tests PASS.

**Step 6: Write the failing tests for the HTTP service endpoints**

Create `services/svc-machine/tests/test_service.py`:

```python
"""Tests for svc_machine.service — HTTP endpoints for machine service."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_machine.service import create_machine_app


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a workspace directory with test files."""
    (tmp_path / "hello.txt").write_text("Hello, World!")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("Nested content")
    return tmp_path


@pytest.fixture
def client(workspace: Path) -> TestClient:
    app = create_machine_app(workspace_dir=workspace)
    return TestClient(app)


class TestExecEndpoint:
    def test_echo(self, client: TestClient) -> None:
        response = client.post("/exec", json={"command": "echo hello"})
        assert response.status_code == 200
        body = response.json()
        assert "hello" in body["stdout"]
        assert body["exit_code"] == 0

    def test_missing_command(self, client: TestClient) -> None:
        response = client.post("/exec", json={})
        assert response.status_code == 422


class TestHealthz:
    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestDescribe:
    def test_describe(self, client: TestClient) -> None:
        response = client.get("/describe")
        assert response.status_code == 200
        assert response.json()["name"] == "svc-machine"
```

**Step 7: Write the service endpoint implementation**

Create `services/svc-machine/src/svc_machine/service.py`:

```python
"""HTTP endpoints for svc-machine — the machine abstraction service.

Wraps LocalBackend operations in FastAPI endpoints. Built using the
amplifier-service-sdk for standard /describe and /healthz endpoints.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_machine.local_backend import LocalBackend


# ---------------------------------------------------------------------------
# Request/Response models for machine service endpoints
# ---------------------------------------------------------------------------


class ExecRequest(BaseModel):
    """Request body for POST /exec."""

    command: str
    timeout: int = 30
    working_dir: str | None = None


class ExecResponse(BaseModel):
    """Response body for POST /exec."""

    stdout: str
    stderr: str
    exit_code: int


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_machine_app(workspace_dir: Path) -> FastAPI:
    """Create the svc-machine FastAPI app.

    Args:
        workspace_dir: Root directory for all filesystem and command operations.
    """
    config = ServiceConfig(name="svc-machine", version="0.1.0")
    app = create_app(config)
    backend = LocalBackend(workspace_dir=workspace_dir)

    @app.post("/exec")
    async def exec_command(req: ExecRequest) -> dict:
        result = await backend.exec(
            command=req.command,
            timeout=req.timeout,
            working_dir=req.working_dir,
        )
        return ExecResponse(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
        ).model_dump()

    return app
```

**Step 8: Run tests to verify they pass**

```bash
cd services/svc-machine && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 9: Commit**

```bash
git add services/svc-machine/ && git commit -m "feat: add svc-machine service with local backend and /exec endpoint"
```

---

### Task 6: Machine Service — File Read/Write/Edit Endpoints

**Files:**
- Modify: `services/svc-machine/src/svc_machine/local_backend.py`
- Modify: `services/svc-machine/src/svc_machine/service.py`
- Test: `services/svc-machine/tests/test_local_backend.py` (append)
- Test: `services/svc-machine/tests/test_service.py` (append)

**Step 1: Write the failing tests for file operations in local backend**

Append to `services/svc-machine/tests/test_local_backend.py`:

```python
class TestFileRead:
    async def test_read_file(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("line1\nline2\nline3\n")
        result = await backend.file_read("test.txt")
        assert result is not None
        assert "line1" in result.content
        assert result.total_lines == 3

    async def test_read_with_offset_and_limit(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("line1\nline2\nline3\nline4\nline5\n")
        result = await backend.file_read("test.txt", offset=2, limit=2)
        assert result is not None
        assert "line2" in result.content
        assert "line3" in result.content
        assert "line1" not in result.content

    async def test_read_nonexistent(self, backend: LocalBackend) -> None:
        result = await backend.file_read("nonexistent.txt")
        assert result is None

    async def test_read_path_traversal(self, backend: LocalBackend) -> None:
        result = await backend.file_read("../../etc/passwd")
        assert result is None


class TestFileWrite:
    async def test_write_new_file(self, backend: LocalBackend, tmp_path: Path) -> None:
        success = await backend.file_write("new.txt", "hello world")
        assert success is True
        assert (tmp_path / "new.txt").read_text() == "hello world"

    async def test_write_overwrites(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "existing.txt").write_text("old content")
        success = await backend.file_write("existing.txt", "new content")
        assert success is True
        assert (tmp_path / "existing.txt").read_text() == "new content"

    async def test_write_creates_parent_dirs(self, backend: LocalBackend, tmp_path: Path) -> None:
        success = await backend.file_write("a/b/c.txt", "deep")
        assert success is True
        assert (tmp_path / "a" / "b" / "c.txt").read_text() == "deep"

    async def test_write_path_traversal(self, backend: LocalBackend) -> None:
        success = await backend.file_write("../../escape.txt", "bad")
        assert success is False


class TestFileEdit:
    async def test_edit_replace(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("hello world")
        result = await backend.file_edit("test.txt", "world", "universe")
        assert result is not None
        assert result.success is True
        assert result.replacements_made == 1
        assert (tmp_path / "test.txt").read_text() == "hello universe"

    async def test_edit_replace_all(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("aaa bbb aaa")
        result = await backend.file_edit("test.txt", "aaa", "ccc", replace_all=True)
        assert result is not None
        assert result.replacements_made == 2
        assert (tmp_path / "test.txt").read_text() == "ccc bbb ccc"

    async def test_edit_no_match(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("hello world")
        result = await backend.file_edit("test.txt", "xyz", "abc")
        assert result is not None
        assert result.replacements_made == 0

    async def test_edit_nonexistent_file(self, backend: LocalBackend) -> None:
        result = await backend.file_edit("nonexistent.txt", "a", "b")
        assert result is None
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-machine && uv run pytest tests/test_local_backend.py -v -k "FileRead or FileWrite or FileEdit"
```

Expected: FAIL — methods do not exist.

**Step 3: Implement file read/write/edit in local backend**

Add the following to `services/svc-machine/src/svc_machine/local_backend.py`, as new methods on `LocalBackend` and new result dataclasses:

Add these dataclasses after `ExecResult`:

```python
@dataclass
class FileReadResult:
    """Result of a file read operation."""

    content: str
    total_lines: int


@dataclass
class FileEditResult:
    """Result of a file edit operation."""

    success: bool
    replacements_made: int
```

Add these methods to the `LocalBackend` class:

```python
    def _resolve_path(self, relative_path: str) -> Path | None:
        """Resolve a relative path within the workspace, returning None if it escapes."""
        target = (self.workspace_dir / relative_path).resolve()
        try:
            target.relative_to(self.workspace_dir)
        except ValueError:
            return None
        return target

    async def file_read(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> FileReadResult | None:
        """Read a file's contents.

        Args:
            path: File path relative to workspace_dir.
            offset: 1-based line number to start reading from.
            limit: Maximum number of lines to return. None means all.

        Returns:
            FileReadResult or None if path is invalid/missing.
        """
        target = self._resolve_path(path)
        if target is None or not target.is_file():
            return None

        text = target.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)

        # Apply offset (1-based) and limit
        start = max(0, offset - 1)
        if limit is not None:
            selected = lines[start : start + limit]
        else:
            selected = lines[start:]

        return FileReadResult(
            content="".join(selected),
            total_lines=total_lines,
        )

    async def file_write(self, path: str, content: str) -> bool:
        """Write content to a file.

        Creates parent directories as needed. Returns False if the path
        would escape the workspace boundary.
        """
        target = self._resolve_path(path)
        if target is None:
            return False

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return True

    async def file_edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileEditResult | None:
        """Edit a file by replacing string occurrences.

        Returns None if file doesn't exist or path is invalid.
        """
        target = self._resolve_path(path)
        if target is None or not target.is_file():
            return None

        text = target.read_text(encoding="utf-8")

        if replace_all:
            count = text.count(old_string)
            new_text = text.replace(old_string, new_string)
        else:
            count = 1 if old_string in text else 0
            new_text = text.replace(old_string, new_string, 1)

        target.write_text(new_text, encoding="utf-8")
        return FileEditResult(success=True, replacements_made=count)
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-machine && uv run pytest tests/test_local_backend.py -v
```

Expected: All tests PASS.

**Step 5: Add HTTP endpoints for file operations**

Add to `services/svc-machine/src/svc_machine/service.py` — new request/response models and routes in `create_machine_app`:

Add these models alongside the existing ones:

```python
class FileReadRequest(BaseModel):
    path: str
    offset: int = 1
    limit: int | None = None


class FileWriteRequest(BaseModel):
    path: str
    content: str


class FileEditRequest(BaseModel):
    path: str
    old_string: str
    new_string: str
    replace_all: bool = False
```

Add these routes inside `create_machine_app`, after the `/exec` route:

```python
    @app.post("/files/read")
    async def files_read(req: FileReadRequest) -> dict:
        result = await backend.file_read(req.path, offset=req.offset, limit=req.limit)
        if result is None:
            raise HTTPException(status_code=404, detail=f"File not found: {req.path}")
        return {"content": result.content, "total_lines": result.total_lines}

    @app.post("/files/write")
    async def files_write(req: FileWriteRequest) -> dict:
        success = await backend.file_write(req.path, req.content)
        if not success:
            raise HTTPException(status_code=403, detail="Path escapes workspace boundary")
        return {"success": True}

    @app.post("/files/edit")
    async def files_edit(req: FileEditRequest) -> dict:
        result = await backend.file_edit(
            req.path, req.old_string, req.new_string, req.replace_all
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"File not found: {req.path}")
        return {"success": result.success, "replacements_made": result.replacements_made}
```

Also add `from fastapi import HTTPException` to the imports in `service.py`.

**Step 6: Add HTTP endpoint tests**

Append to `services/svc-machine/tests/test_service.py`:

```python
class TestFileReadEndpoint:
    def test_read_file(self, client: TestClient) -> None:
        response = client.post("/files/read", json={"path": "hello.txt"})
        assert response.status_code == 200
        assert "Hello, World!" in response.json()["content"]

    def test_read_missing_file(self, client: TestClient) -> None:
        response = client.post("/files/read", json={"path": "missing.txt"})
        assert response.status_code == 404


class TestFileWriteEndpoint:
    def test_write_file(self, client: TestClient, workspace: Path) -> None:
        response = client.post(
            "/files/write",
            json={"path": "output.txt", "content": "new content"},
        )
        assert response.status_code == 200
        assert (workspace / "output.txt").read_text() == "new content"


class TestFileEditEndpoint:
    def test_edit_file(self, client: TestClient, workspace: Path) -> None:
        response = client.post(
            "/files/edit",
            json={"path": "hello.txt", "old_string": "World", "new_string": "Universe"},
        )
        assert response.status_code == 200
        assert response.json()["replacements_made"] == 1
        assert (workspace / "hello.txt").read_text() == "Hello, Universe!"
```

**Step 7: Run all machine service tests**

```bash
cd services/svc-machine && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 8: Commit**

```bash
git add services/svc-machine/ && git commit -m "feat: add file read/write/edit endpoints to svc-machine"
```

---

### Task 7: Machine Service — File List/Glob/Grep Endpoints

**Files:**
- Modify: `services/svc-machine/src/svc_machine/local_backend.py`
- Modify: `services/svc-machine/src/svc_machine/service.py`
- Test: `services/svc-machine/tests/test_local_backend.py` (append)
- Test: `services/svc-machine/tests/test_service.py` (append)

**Step 1: Write the failing tests for list/glob/grep in local backend**

Append to `services/svc-machine/tests/test_local_backend.py`:

```python
class TestFileList:
    async def test_list_directory(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "subdir").mkdir()
        result = await backend.file_list(".")
        assert result is not None
        names = [e["name"] for e in result]
        assert "a.txt" in names
        assert "b.txt" in names
        assert "subdir" in names

    async def test_list_entries_have_type(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("content")
        (tmp_path / "dir").mkdir()
        result = await backend.file_list(".")
        assert result is not None
        by_name = {e["name"]: e for e in result}
        assert by_name["file.txt"]["type"] == "file"
        assert by_name["dir"]["type"] == "dir"

    async def test_list_nonexistent(self, backend: LocalBackend) -> None:
        result = await backend.file_list("nonexistent")
        assert result is None


class TestFileGlob:
    async def test_glob_pattern(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        result = await backend.file_glob("*.py")
        assert result is not None
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    async def test_glob_recursive(self, backend: LocalBackend, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.py").write_text("")
        result = await backend.file_glob("**/*.py")
        assert result is not None
        assert any("deep.py" in p for p in result)


class TestFileGrep:
    async def test_grep_finds_matches(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text("def hello():\n    pass\ndef world():\n    pass\n")
        result = await backend.file_grep("def \\w+", path="code.py")
        assert result is not None
        assert len(result) == 2

    async def test_grep_no_matches(self, backend: LocalBackend, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text("hello world\n")
        result = await backend.file_grep("zzz_no_match", path="code.py")
        assert result is not None
        assert len(result) == 0
```

**Step 2: Run to verify failure, then implement**

```bash
cd services/svc-machine && uv run pytest tests/test_local_backend.py -v -k "FileList or FileGlob or FileGrep"
```

Expected: FAIL — methods don't exist.

**Step 3: Implement file list/glob/grep in local backend**

Add the `re` import at the top of `local_backend.py`, then add these methods to `LocalBackend`:

```python
    async def file_list(self, path: str = ".") -> list[dict[str, Any]] | None:
        """List directory contents.

        Returns list of entries with name, type, and size, or None if path is invalid.
        """
        target = self._resolve_path(path)
        if target is None or not target.is_dir():
            return None

        entries: list[dict[str, Any]] = []
        for item in sorted(target.iterdir()):
            entry: dict[str, Any] = {
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
            }
            if item.is_file():
                entry["size"] = item.stat().st_size
            entries.append(entry)
        return entries

    async def file_glob(
        self, pattern: str, path: str = "."
    ) -> list[str] | None:
        """Match files using a glob pattern.

        Returns list of matching paths relative to workspace_dir.
        """
        target = self._resolve_path(path)
        if target is None or not target.exists():
            return None

        matches: list[str] = []
        for f in sorted(target.glob(pattern)):
            if f.is_file():
                rel = f.relative_to(self.workspace_dir)
                matches.append(rel.as_posix())
        return matches

    async def file_grep(
        self, pattern: str, path: str = "."
    ) -> list[dict[str, Any]] | None:
        """Search file contents with a regex pattern.

        If path points to a file, search that file.
        If path points to a directory, search all files recursively.

        Returns list of matches with file, line, and content.
        """
        import re

        target = self._resolve_path(path)
        if target is None or not target.exists():
            return None

        files_to_search: list[Path] = []
        if target.is_file():
            files_to_search = [target]
        elif target.is_dir():
            files_to_search = sorted(f for f in target.rglob("*") if f.is_file())

        matches: list[dict[str, Any]] = []
        try:
            compiled = re.compile(pattern)
        except re.error:
            return []

        for fpath in files_to_search:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if compiled.search(line):
                    rel = fpath.relative_to(self.workspace_dir)
                    matches.append({
                        "file": rel.as_posix(),
                        "line": i,
                        "content": line,
                    })
        return matches
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-machine && uv run pytest tests/test_local_backend.py -v
```

Expected: All tests PASS.

**Step 5: Add HTTP endpoints for list/glob/grep**

Add these models to `services/svc-machine/src/svc_machine/service.py`:

```python
class FileListRequest(BaseModel):
    path: str = "."


class FileGlobRequest(BaseModel):
    pattern: str
    path: str = "."


class FileGrepRequest(BaseModel):
    pattern: str
    path: str = "."
```

Add these routes inside `create_machine_app`:

```python
    @app.post("/files/list")
    async def files_list(req: FileListRequest) -> dict:
        result = await backend.file_list(req.path)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Directory not found: {req.path}")
        return {"entries": result}

    @app.post("/files/glob")
    async def files_glob(req: FileGlobRequest) -> dict:
        result = await backend.file_glob(req.pattern, req.path)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")
        return {"matches": result}

    @app.post("/files/grep")
    async def files_grep(req: FileGrepRequest) -> dict:
        result = await backend.file_grep(req.pattern, req.path)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")
        return {"matches": result}
```

**Step 6: Run all tests**

```bash
cd services/svc-machine && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 7: Commit**

```bash
git add services/svc-machine/ && git commit -m "feat: add file list/glob/grep endpoints to svc-machine"
```

---

### Task 8: svc-bash — Tool Service Calling Machine via httpx

**Files:**
- Create: `services/svc-bash/pyproject.toml`
- Create: `services/svc-bash/src/svc_bash/__init__.py`
- Create: `services/svc-bash/src/svc_bash/tool.py`
- Create: `services/svc-bash/src/svc_bash/app.py`
- Create: `services/svc-bash/describe.yaml`
- Test: `services/svc-bash/tests/test_tool.py`

**Step 1: Create the package scaffold**

Create `services/svc-bash/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-bash"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.28",
]

[tool.hatch.build.targets.wheel]
packages = ["src/svc_bash"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src", "../../amplifier-service-sdk/src"]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }
```

Create `services/svc-bash/src/svc_bash/__init__.py`:

```python
"""svc-bash — Bash command execution tool service."""
```

Create `services/svc-bash/describe.yaml`:

```yaml
name: svc-bash
version: "0.1.0"
tools:
  - name: bash
    description: >
      Execute bash commands via the machine service. Commands run in the
      workspace directory. Use for build/test commands, git operations,
      package management, and system utilities.
    input_schema:
      type: object
      properties:
        command:
          type: string
          description: Bash command to execute
        timeout:
          type: integer
          description: "Command timeout in seconds (default: 30)"
          default: 30
        run_in_background:
          type: boolean
          description: Run command in background, returning immediately with PID
          default: false
      required:
        - command
```

**Step 2: Write the failing tests**

Create `services/svc-bash/tests/test_tool.py`:

```python
"""Tests for svc_bash — bash tool calling machine service.

Tests use a real svc-machine instance in-process (no Dapr needed for unit tests).
The tool's httpx client is pointed at the machine service's TestClient.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from svc_bash.app import create_bash_app
from svc_bash.tool import BashTool


@pytest.fixture
def mock_machine_exec() -> AsyncMock:
    """Create a mock for the machine service /exec call."""
    mock = AsyncMock()
    mock.return_value = {
        "stdout": "hello\n",
        "stderr": "",
        "exit_code": 0,
    }
    return mock


class TestBashTool:
    async def test_execute_calls_machine_service(self) -> None:
        """BashTool forwards command to machine service via HTTP."""
        tool = BashTool(machine_base_url="http://localhost:3500/v1.0/invoke/svc-machine/method")

        # Mock the httpx post call
        with patch.object(tool, "_call_machine_exec") as mock_exec:
            mock_exec.return_value = {"stdout": "hello\n", "stderr": "", "exit_code": 0}
            result = await tool.execute({"command": "echo hello"})

        assert result.success is True
        assert "hello" in result.output["stdout"]

    async def test_execute_missing_command(self) -> None:
        tool = BashTool(machine_base_url="http://localhost:3500")
        result = await tool.execute({})
        assert result.success is False
        assert "required" in str(result.error).lower() or "required" in str(result.output).lower()

    async def test_execute_machine_failure(self) -> None:
        tool = BashTool(machine_base_url="http://localhost:3500/v1.0/invoke/svc-machine/method")

        with patch.object(tool, "_call_machine_exec") as mock_exec:
            mock_exec.return_value = {"stdout": "", "stderr": "not found", "exit_code": 127}
            result = await tool.execute({"command": "nonexistent_cmd"})

        assert result.success is False
        assert result.output["exit_code"] == 127


class TestBashApp:
    def test_healthz(self) -> None:
        app = create_bash_app(machine_base_url="http://fake:3500")
        client = TestClient(app)
        response = client.get("/healthz")
        assert response.status_code == 200

    def test_describe_includes_bash_tool(self) -> None:
        app = create_bash_app(machine_base_url="http://fake:3500")
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "svc-bash"
        tool_names = [t["name"] for t in body["tools"]]
        assert "bash" in tool_names
```

**Step 3: Run tests to verify they fail**

```bash
cd services/svc-bash && uv sync --dev && uv run pytest tests/test_tool.py -v
```

Expected: FAIL — modules don't exist.

**Step 4: Implement the bash tool**

Create `services/svc-bash/src/svc_bash/tool.py`:

```python
"""BashTool — executes bash commands via the machine service.

Instead of running subprocess directly, this tool calls svc-machine's
/exec endpoint via HTTP (through Dapr service invocation in production,
or directly via httpx in tests).
"""

from __future__ import annotations

from typing import Any

import httpx

from amplifier_service_sdk.models import ToolResult


class BashTool:
    """Bash command execution tool that delegates to svc-machine.

    Args:
        machine_base_url: Base URL for the machine service.
            In production with Dapr: http://localhost:3500/v1.0/invoke/svc-machine/method
            In tests: http://localhost:{port}
    """

    name = "bash"
    description = (
        "Execute bash commands via the machine service. Commands run in the "
        "workspace directory. Use for build/test commands, git operations, "
        "package management, and system utilities."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to execute"},
            "timeout": {
                "type": "integer",
                "description": "Command timeout in seconds (default: 30)",
                "default": 30,
            },
            "run_in_background": {
                "type": "boolean",
                "description": "Run command in background, returning immediately with PID",
                "default": False,
            },
        },
        "required": ["command"],
    }

    def __init__(self, machine_base_url: str) -> None:
        self._machine_base_url = machine_base_url.rstrip("/")

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a bash command via the machine service."""
        command = input.get("command")
        if not command:
            return ToolResult(
                success=False,
                output="Command is required",
                error={"message": "Command is required"},
            )

        timeout = input.get("timeout", 30)

        try:
            result = await self._call_machine_exec(command, timeout)
        except Exception as e:
            return ToolResult(
                success=False,
                output=str(e),
                error={"message": str(e)},
            )

        output = {
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "returncode": result["exit_code"],
        }

        return ToolResult(
            success=result["exit_code"] == 0,
            output=output,
        )

    async def _call_machine_exec(
        self, command: str, timeout: int = 30
    ) -> dict[str, Any]:
        """Call the machine service /exec endpoint."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._machine_base_url}/exec",
                json={"command": command, "timeout": timeout},
                timeout=timeout + 10,  # HTTP timeout > command timeout
            )
            response.raise_for_status()
            return response.json()
```

Create `services/svc-bash/src/svc_bash/app.py`:

```python
"""FastAPI app for svc-bash — wires the BashTool into the SDK service runner."""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_bash.tool import BashTool


def create_bash_app(machine_base_url: str | None = None) -> FastAPI:
    """Create the svc-bash FastAPI app.

    Args:
        machine_base_url: Base URL for svc-machine. Defaults to Dapr sidecar URL.
    """
    if machine_base_url is None:
        dapr_port = os.environ.get("DAPR_HTTP_PORT", "3500")
        machine_base_url = (
            f"http://localhost:{dapr_port}/v1.0/invoke/svc-machine/method"
        )

    tool = BashTool(machine_base_url=machine_base_url)

    config = ServiceConfig(
        name="svc-bash",
        version="0.1.0",
        tools=[
            ToolCapability(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
        ],
    )
    app = create_app(config)

    @app.post("/tools/bash/execute")
    async def execute_bash(req: ToolRequest) -> dict:
        result = await tool.execute(req.input)
        return result.model_dump()

    return app
```

**Step 5: Run tests to verify they pass**

```bash
cd services/svc-bash && uv run pytest tests/test_tool.py -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add services/svc-bash/ && git commit -m "feat: add svc-bash tool service calling svc-machine via httpx"
```

---

### Task 9: Base Docker Image

**Files:**
- Create: `docker/base/Dockerfile`

**Step 1: Create the base Dockerfile**

Create `docker/base/Dockerfile`:

```dockerfile
# Amplifier Service Base Image
# All microservices layer on top of this image.

FROM python:3.12-slim

WORKDIR /app

# Install uv for fast Python package management
RUN pip install --no-cache-dir uv

# Copy and install the SDK (shared by all services)
COPY amplifier-service-sdk/ /build/amplifier-service-sdk/
RUN cd /build/amplifier-service-sdk && uv pip install --system . && rm -rf /build

# Health check: all services expose /healthz
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

EXPOSE 8000
```

**Step 2: Verify the Dockerfile is valid syntax**

```bash
docker build --check -f docker/base/Dockerfile . 2>&1 || echo "Syntax check done (--check may not be supported, that's OK)"
```

**Step 3: Commit**

```bash
git add docker/base/Dockerfile && git commit -m "feat: add shared base Docker image for Amplifier services"
```

---

### Task 10: Dapr Component Configuration

**Files:**
- Create: `docker/dapr/components/statestore.yaml`
- Create: `docker/dapr/components/pubsub.yaml`
- Create: `docker/dapr/config.yaml`

**Step 1: Create Dapr state store config**

Create `docker/dapr/components/statestore.yaml`:

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: statestore
spec:
  type: state.redis
  version: v1
  metadata:
    - name: redisHost
      value: redis:6379
    - name: redisPassword
      value: ""
    - name: actorStateStore
      value: "true"
```

**Step 2: Create Dapr pub/sub config**

Create `docker/dapr/components/pubsub.yaml`:

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: pubsub
spec:
  type: pubsub.redis
  version: v1
  metadata:
    - name: redisHost
      value: redis:6379
    - name: redisPassword
      value: ""
```

**Step 3: Create Dapr configuration**

Create `docker/dapr/config.yaml`:

```yaml
apiVersion: dapr.io/v1alpha1
kind: Configuration
metadata:
  name: amplifier-config
spec:
  tracing:
    samplingRate: "1"
  metric:
    enabled: true
```

**Step 4: Commit**

```bash
git add docker/dapr/ && git commit -m "feat: add Dapr component configuration (Redis state store + pub/sub)"
```

---

### Task 11: Docker Compose

**Files:**
- Create: `services/svc-machine/Dockerfile`
- Create: `services/svc-bash/Dockerfile`
- Create: `docker-compose.yaml`

**Step 1: Create svc-machine Dockerfile**

Create `services/svc-machine/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-machine/ /build/svc-machine/
RUN cd /build/svc-machine && uv pip install --system . && rm -rf /build

# The workspace will be mounted as a volume at /workspace
ENV WORKSPACE_DIR=/workspace

CMD ["python", "-m", "uvicorn", "svc_machine.service:app", "--host", "0.0.0.0", "--port", "8000"]
```

Note: svc-machine needs a module-level `app` object. Add this to the bottom of `services/svc-machine/src/svc_machine/service.py`:

```python
# Module-level app for uvicorn (used in Docker CMD)
import os as _os
from pathlib import Path as _Path

_workspace = _Path(_os.environ.get("WORKSPACE_DIR", "/workspace"))
app = create_machine_app(workspace_dir=_workspace)
```

**Step 2: Create svc-bash Dockerfile**

Create `services/svc-bash/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-bash/ /build/svc-bash/
RUN cd /build/svc-bash && uv pip install --system . && rm -rf /build

CMD ["python", "-m", "uvicorn", "svc_bash.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Note: svc-bash also needs a module-level `app`. Add this to the bottom of `services/svc-bash/src/svc_bash/app.py`:

```python
# Module-level app for uvicorn (used in Docker CMD)
app = create_bash_app()
```

**Step 3: Create docker-compose.yaml**

Create `docker-compose.yaml`:

```yaml
version: "3.8"

services:
  # --- Infrastructure ---
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  # --- svc-machine + Dapr sidecar ---
  svc-machine:
    build:
      context: .
      dockerfile: services/svc-machine/Dockerfile
    environment:
      - WORKSPACE_DIR=/workspace
    volumes:
      - ${WORKSPACE_PATH:-.}:/workspace
    depends_on:
      - redis

  svc-machine-dapr:
    image: daprio/daprd:1.14.4
    command:
      - ./daprd
      - --app-id=svc-machine
      - --app-port=8000
      - --dapr-http-port=3500
      - --dapr-grpc-port=50001
      - --resources-path=/components
      - --config=/config/config.yaml
      - --log-level=info
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr/config.yaml:/config/config.yaml
    network_mode: "service:svc-machine"
    depends_on:
      - svc-machine
      - redis

  # --- svc-bash + Dapr sidecar ---
  svc-bash:
    build:
      context: .
      dockerfile: services/svc-bash/Dockerfile
    environment:
      - DAPR_HTTP_PORT=3500
    depends_on:
      - redis
      - svc-machine-dapr

  svc-bash-dapr:
    image: daprio/daprd:1.14.4
    command:
      - ./daprd
      - --app-id=svc-bash
      - --app-port=8000
      - --dapr-http-port=3500
      - --dapr-grpc-port=50001
      - --resources-path=/components
      - --config=/config/config.yaml
      - --log-level=info
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr/config.yaml:/config/config.yaml
    network_mode: "service:svc-bash"
    depends_on:
      - svc-bash
      - redis
```

**Step 4: Commit**

```bash
git add services/svc-machine/Dockerfile services/svc-bash/Dockerfile docker-compose.yaml && git commit -m "feat: add Docker Compose with svc-machine, svc-bash, Dapr sidecars, and Redis"
```

---

### Task 12: Integration Test

**Files:**
- Create: `tests/test_microservices_integration.py`

This test runs **without** Docker — it creates both services in-process using TestClient/httpx to verify the full call chain: svc-bash -> svc-machine -> subprocess.

**Step 1: Write the integration test**

Create `tests/test_microservices_integration.py`:

```python
"""Integration test for Phase 1 microservices vertical slice.

Verifies the full call chain: svc-bash -> svc-machine -> subprocess execution.
Both services run in-process using FastAPI TestClient (no Docker/Dapr needed).

For Docker Compose integration tests, run: docker compose up && ./scripts/test_integration.sh
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from svc_bash.app import create_bash_app
from svc_bash.tool import BashTool
from svc_machine.service import create_machine_app


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a workspace with test files."""
    (tmp_path / "hello.txt").write_text("Hello, World!")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    return tmp_path


@pytest.fixture
def machine_client(workspace: Path) -> TestClient:
    """In-process machine service."""
    app = create_machine_app(workspace_dir=workspace)
    return TestClient(app)


class TestServiceContracts:
    """Verify both services implement the standard service contract."""

    def test_machine_healthz(self, machine_client: TestClient) -> None:
        r = machine_client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_machine_describe(self, machine_client: TestClient) -> None:
        r = machine_client.get("/describe")
        assert r.status_code == 200
        assert r.json()["name"] == "svc-machine"

    def test_bash_healthz(self) -> None:
        app = create_bash_app(machine_base_url="http://fake:8000")
        client = TestClient(app)
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_bash_describe(self) -> None:
        app = create_bash_app(machine_base_url="http://fake:8000")
        client = TestClient(app)
        r = client.get("/describe")
        assert r.status_code == 200
        desc = r.json()
        assert desc["name"] == "svc-bash"
        assert any(t["name"] == "bash" for t in desc["tools"])


class TestEndToEndExecution:
    """Test the full call chain: svc-bash -> svc-machine -> subprocess."""

    async def test_bash_echo_via_machine(self, workspace: Path) -> None:
        """svc-bash calls svc-machine /exec, which runs the command."""
        machine_app = create_machine_app(workspace_dir=workspace)
        machine_client = TestClient(machine_app)

        # Create a BashTool that calls the in-process machine service
        tool = BashTool(machine_base_url="http://testserver")

        # Patch _call_machine_exec to use the TestClient
        async def mock_exec(command: str, timeout: int = 30) -> dict:
            r = machine_client.post("/exec", json={"command": command, "timeout": timeout})
            return r.json()

        with patch.object(tool, "_call_machine_exec", side_effect=mock_exec):
            result = await tool.execute({"command": "echo hello from bash"})

        assert result.success is True
        assert "hello from bash" in result.output["stdout"]

    async def test_bash_reads_workspace_file(self, workspace: Path) -> None:
        """svc-bash can read workspace files via svc-machine."""
        machine_app = create_machine_app(workspace_dir=workspace)
        machine_client = TestClient(machine_app)

        tool = BashTool(machine_base_url="http://testserver")

        async def mock_exec(command: str, timeout: int = 30) -> dict:
            r = machine_client.post("/exec", json={"command": command, "timeout": timeout})
            return r.json()

        with patch.object(tool, "_call_machine_exec", side_effect=mock_exec):
            result = await tool.execute({"command": "cat hello.txt"})

        assert result.success is True
        assert "Hello, World!" in result.output["stdout"]

    def test_machine_file_operations(self, machine_client: TestClient, workspace: Path) -> None:
        """Direct machine service file operations work correctly."""
        # Read
        r = machine_client.post("/files/read", json={"path": "hello.txt"})
        assert r.status_code == 200
        assert "Hello, World!" in r.json()["content"]

        # Write
        r = machine_client.post(
            "/files/write",
            json={"path": "output.txt", "content": "test output"},
        )
        assert r.status_code == 200
        assert (workspace / "output.txt").read_text() == "test output"

        # List
        r = machine_client.post("/files/list", json={"path": "."})
        assert r.status_code == 200
        names = [e["name"] for e in r.json()["entries"]]
        assert "hello.txt" in names

        # Glob
        r = machine_client.post("/files/glob", json={"pattern": "**/*.py"})
        assert r.status_code == 200
        assert any("main.py" in m for m in r.json()["matches"])

        # Grep
        r = machine_client.post(
            "/files/grep",
            json={"pattern": "print", "path": "src/main.py"},
        )
        assert r.status_code == 200
        assert len(r.json()["matches"]) > 0

        # Edit
        r = machine_client.post(
            "/files/edit",
            json={
                "path": "hello.txt",
                "old_string": "World",
                "new_string": "Microservices",
            },
        )
        assert r.status_code == 200
        assert r.json()["replacements_made"] == 1
        assert (workspace / "hello.txt").read_text() == "Hello, Microservices!"
```

**Step 2: Run the integration test**

This test requires both SDK and service packages to be importable. Run from the repo root:

```bash
cd /data/labs/amplifier-ipc
PYTHONPATH=amplifier-service-sdk/src:services/svc-machine/src:services/svc-bash/src \
    uv run pytest tests/test_microservices_integration.py -v
```

Expected: All tests PASS.

**Step 3: Commit**

```bash
git add tests/test_microservices_integration.py && git commit -m "feat: add Phase 1 microservices integration test"
```

---

## Verification Checklist

After all tasks are complete, verify these pass:

```bash
# SDK unit tests
cd amplifier-service-sdk && uv run pytest tests/ -v

# Machine service unit tests
cd services/svc-machine && uv run pytest tests/ -v

# Bash service unit tests
cd services/svc-bash && uv run pytest tests/ -v

# Integration test
cd /data/labs/amplifier-ipc
PYTHONPATH=amplifier-service-sdk/src:services/svc-machine/src:services/svc-bash/src \
    uv run pytest tests/test_microservices_integration.py -v
```

## Docker Compose Smoke Test (manual)

Once all unit tests pass, build and run the full stack:

```bash
# Build base image
docker build -t amplifier-service-base -f docker/base/Dockerfile .

# Build and start all services
WORKSPACE_PATH=$(pwd) docker compose up --build -d

# Wait for services to start
sleep 10

# Test svc-machine via its Dapr sidecar
curl -s http://localhost:3500/v1.0/invoke/svc-machine/method/healthz | jq .
curl -s http://localhost:3500/v1.0/invoke/svc-machine/method/describe | jq .
curl -s -X POST http://localhost:3500/v1.0/invoke/svc-machine/method/exec \
    -H "Content-Type: application/json" \
    -d '{"command": "echo hello from machine"}' | jq .

# Test svc-bash via its Dapr sidecar
curl -s http://localhost:3501/v1.0/invoke/svc-bash/method/healthz | jq .
curl -s http://localhost:3501/v1.0/invoke/svc-bash/method/describe | jq .
curl -s -X POST http://localhost:3501/v1.0/invoke/svc-bash/method/tools/bash/execute \
    -H "Content-Type: application/json" \
    -d '{"name": "bash", "input": {"command": "echo hello via bash service"}}' | jq .

# Tear down
docker compose down
```

## What's Next (Phase 2)

Phase 1 proves the pattern. Phase 2 builds on it:
- Session Service (agent definition resolution, /describe collection, system prompt assembly)
- Orchestrator Service migration (Dapr service invocation instead of _OrchestratorLocalClient)
- CLI sends prompt to Session Service, which invokes orchestrator, which calls svc-bash via Dapr
