# Phase 5: CLI Rewrite as HTTP Client to Session-Service — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Replace the in-process `amplifier-ipc` CLI — which spawns services as subprocesses and communicates via pipes — with a thin HTTP client (`amplifier-ipc-cli`) that talks to the session-service over HTTP/SSE, completing the microservices migration.

**Architecture:** The new CLI is a standalone Python package (`amplifier-ipc-cli/`) that is **not** a Docker container. It runs on the user's machine and connects to the session-service (running inside Docker Compose at `localhost:8080`). The session-service gains a `GET /sessions/{id}/turn/stream` SSE endpoint that streams orchestrator events in real time. The CLI reads workspace content from the local filesystem, sends it with each turn request, and renders SSE events using Rich. All slash commands (`/status`, `/tools`, `/modes`, etc.) become HTTP calls to new metadata endpoints on the session-service.

**Tech Stack:** Python 3.12+, httpx (with SSE streaming), click, Rich, prompt-toolkit, pytest with asyncio_mode="auto", uv

---

## Reference: Existing Patterns

Before implementing, understand these existing patterns by reading these files:

- **Session-service app:** `services/session-service/src/session_service/app.py` (TurnRequest/TurnResponse, create_session_app)
- **Session-service discovery:** `services/session-service/src/session_service/discovery.py` (discover_services, build_routing_table)
- **Session-service state:** `services/session-service/src/session_service/state.py` (save_transcript, load_transcript via Dapr)
- **Session-service content:** `services/session-service/src/session_service/content.py` (assemble_system_prompt)
- **Session-service tests:** `services/session-service/tests/test_app.py` (TestClient pattern)
- **SDK models:** `amplifier-service-sdk/src/amplifier_service_sdk/models.py` (StreamEvent, Message, RoutingTable, etc.)
- **Current CLI entry point:** `src/amplifier_ipc/cli/main.py` (click group with commands)
- **Current CLI run command:** `src/amplifier_ipc/cli/commands/run.py` (run command, _run_agent, agent resolution)
- **Current CLI REPL:** `src/amplifier_ipc/cli/repl.py` (interactive_repl, slash commands, @mentions, cancellation)
- **Current CLI streaming:** `src/amplifier_ipc/cli/streaming.py` (StreamingDisplay class)
- **Current CLI settings:** `src/amplifier_ipc/cli/settings.py` (AppSettings, multi-scope YAML)
- **Current CLI paths:** `src/amplifier_ipc/cli/paths.py` (project slug, session dirs)
- **Host events:** `src/amplifier_ipc/host/events.py` (HostEvent hierarchy — StreamTokenEvent, ToolCallEvent, etc.)
- **Docker Compose:** `docker-compose.yaml` (session-service exposed on port 8080)
- **Orchestrator app:** `services/svc-orchestrator/src/svc_orchestrator/app.py` (ExecuteRequest/ExecuteResponse)
- **Service pyproject.toml pattern:** `services/session-service/pyproject.toml` (hatchling, uv sources, pytest config)

---

## Task 1: SSE Streaming Endpoint on Session-Service

**Files:**
- Modify: `services/session-service/src/session_service/app.py`
- Create: `services/session-service/src/session_service/streaming.py`
- Create: `services/session-service/tests/test_streaming.py`
- Modify: `services/session-service/pyproject.toml`

**Step 1: Write the failing tests**

Create `services/session-service/tests/test_streaming.py`:

```python
"""Tests for the SSE streaming module."""

from __future__ import annotations

import json

import pytest

from session_service.streaming import format_sse_event, StreamEventType


class TestFormatSSEEvent:
    """Tests for format_sse_event helper."""

    def test_format_token_event(self) -> None:
        """format_sse_event produces valid SSE for a token event."""
        result = format_sse_event(StreamEventType.TOKEN, {"token": "hello"})
        assert result.startswith("event: token\n")
        assert "data: " in result
        assert result.endswith("\n\n")
        # Parse the data line
        data_line = [l for l in result.strip().split("\n") if l.startswith("data: ")][0]
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload["token"] == "hello"

    def test_format_tool_call_event(self) -> None:
        """format_sse_event produces valid SSE for a tool_call event."""
        result = format_sse_event(
            StreamEventType.TOOL_CALL,
            {"tool_name": "bash", "arguments": {"command": "ls"}},
        )
        assert result.startswith("event: tool_call\n")
        data_line = [l for l in result.strip().split("\n") if l.startswith("data: ")][0]
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload["tool_name"] == "bash"

    def test_format_complete_event(self) -> None:
        """format_sse_event produces valid SSE for a complete event."""
        result = format_sse_event(StreamEventType.COMPLETE, {"result": "done"})
        assert "event: complete\n" in result

    def test_format_error_event(self) -> None:
        """format_sse_event produces valid SSE for an error event."""
        result = format_sse_event(StreamEventType.ERROR, {"message": "oops"})
        assert "event: error\n" in result

    def test_all_event_types_defined(self) -> None:
        """StreamEventType has all expected event types."""
        expected = {
            "token", "thinking", "tool_call_start", "tool_call",
            "tool_result", "todo_update", "child_session_start",
            "child_session_end", "error", "complete",
            "content_block_start", "content_block_end",
        }
        actual = {e.value for e in StreamEventType}
        assert expected.issubset(actual)
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd services/session-service && uv run pytest tests/test_streaming.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'session_service.streaming'`

**Step 3: Write the streaming module**

Create `services/session-service/src/session_service/streaming.py`:

```python
"""SSE streaming utilities for session-service.

Provides helpers to format Server-Sent Events (SSE) from orchestrator events.
Each SSE event has an `event:` line naming the event type and a `data:` line
carrying a JSON payload.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any


class StreamEventType(str, Enum):
    """SSE event types emitted by the streaming turn endpoint."""

    TOKEN = "token"
    THINKING = "thinking"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TODO_UPDATE = "todo_update"
    CHILD_SESSION_START = "child_session_start"
    CHILD_SESSION_END = "child_session_end"
    CONTENT_BLOCK_START = "content_block_start"
    CONTENT_BLOCK_END = "content_block_end"
    ERROR = "error"
    COMPLETE = "complete"


def format_sse_event(event_type: StreamEventType, data: dict[str, Any]) -> str:
    """Format a single SSE event string.

    Args:
        event_type: The event type name.
        data: JSON-serialisable payload.

    Returns:
        A complete SSE event string with trailing double-newline.
    """
    json_data = json.dumps(data, separators=(",", ":"))
    return f"event: {event_type.value}\ndata: {json_data}\n\n"
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd services/session-service && uv run pytest tests/test_streaming.py -v
```
Expected: All tests PASS.

**Step 5: Add the SSE streaming endpoint to the session-service app**

Add `sse-starlette>=2.0` to `services/session-service/pyproject.toml` dependencies:

```toml
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.27",
    "pyyaml>=6.0",
    "sse-starlette>=2.0",
]
```

Also add `"sse-starlette>=2.0"` to the `[dependency-groups] dev` list.

In `services/session-service/src/session_service/app.py`, add the streaming turn endpoint inside `create_session_app()`, after the existing `/sessions/{session_id}/turn` endpoint:

```python
# Add these imports at the top of the file
import asyncio
from sse_starlette.sse import EventSourceResponse
from session_service.streaming import StreamEventType, format_sse_event

# Add this endpoint inside create_session_app(), after the existing turn endpoint:

    @app.post("/sessions/{session_id}/turn/stream")
    async def turn_stream(session_id: str, request: TurnRequest) -> EventSourceResponse:
        """Execute a conversation turn and stream events via SSE.

        Returns an SSE stream. Each event has an `event:` type and a `data:`
        JSON payload. The final event is always `complete` or `error`.
        """
        async def event_generator():
            try:
                # Create session if it doesn't exist
                if session_id not in _sessions:
                    _sessions[session_id] = {"turn_count": 0, "status": "active"}

                # Discover services and build routing table
                service_ids = request.services if request.services else DEFAULT_SERVICES
                routing_table_dict = await discover_services(service_ids, _dapr_url)

                # Assemble the system prompt
                system_prompt = assemble_system_prompt(
                    routing_table_dict, request.workspace_content, _dapr_url
                )

                # Load existing transcript
                transcript = await load_transcript(session_id, _dapr_url)
                transcript.append(Message(role="user", content=request.prompt))

                # Invoke orchestrator
                invoke_url = (
                    f"{_dapr_url}/v1.0/invoke/svc-orchestrator/method/orchestrator/execute"
                )
                payload = {
                    "system_prompt": system_prompt,
                    "messages": [m.model_dump() for m in transcript],
                    "config": {"provider": request.provider_name},
                    "routing_table": routing_table_dict,
                    "session_id": session_id,
                }
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        invoke_url, json=payload, timeout=120.0
                    )
                    response.raise_for_status()
                    orch_result = response.json()

                result_text = orch_result.get("result", "")
                result_messages = orch_result.get("messages", [])
                messages = [Message(**m) for m in result_messages]

                # Save transcript
                await save_transcript(session_id, messages, _dapr_url)
                _sessions[session_id]["turn_count"] += 1

                # Emit the complete event
                yield {
                    "event": StreamEventType.COMPLETE.value,
                    "data": json.dumps({"result": result_text}),
                }
            except Exception as exc:
                yield {
                    "event": StreamEventType.ERROR.value,
                    "data": json.dumps({"message": str(exc)}),
                }

        return EventSourceResponse(event_generator())
```

Add `import json` to the top-level imports of `app.py`.

**Step 6: Run full test suite**

Run:
```bash
cd services/session-service && uv sync && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 7: Commit**

```bash
git add services/session-service/ && git commit -m "feat(session-service): add SSE streaming endpoint and event type definitions"
```

---

## Task 2: CLI HTTP Client Module

**Files:**
- Create: `amplifier-ipc-cli/pyproject.toml`
- Create: `amplifier-ipc-cli/src/amplifier_ipc_cli/__init__.py`
- Create: `amplifier-ipc-cli/src/amplifier_ipc_cli/client.py`
- Create: `amplifier-ipc-cli/tests/__init__.py`
- Create: `amplifier-ipc-cli/tests/test_client.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-cli/tests/__init__.py` (empty).

Create `amplifier-ipc-cli/tests/test_client.py`:

```python
"""Tests for SessionClient — the HTTP client to session-service."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_ipc_cli.client import SessionClient, SSEEvent


class TestSessionClient:
    """Tests for SessionClient."""

    @pytest.fixture
    def client(self) -> SessionClient:
        return SessionClient(base_url="http://localhost:8080")

    def test_default_base_url(self) -> None:
        """Default base_url is http://localhost:8080."""
        c = SessionClient()
        assert c.base_url == "http://localhost:8080"

    def test_custom_base_url(self, client: SessionClient) -> None:
        """Custom base_url is stored correctly."""
        assert client.base_url == "http://localhost:8080"

    @pytest.mark.asyncio
    async def test_send_turn_calls_session_service(self, client: SessionClient) -> None:
        """send_turn() POSTs to /sessions/{id}/turn and returns the result."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "session_id": "test-123",
            "result": "Hello!",
            "messages": [],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("amplifier_ipc_cli.client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            result = await client.send_turn("test-123", "Hello", provider_name="mock")

        assert result["result"] == "Hello!"
        assert result["session_id"] == "test-123"

    @pytest.mark.asyncio
    async def test_get_session_info(self, client: SessionClient) -> None:
        """get_session_info() calls GET /sessions/{id}."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "session_id": "test-123",
            "status": "active",
            "turn_count": 3,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("amplifier_ipc_cli.client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            result = await client.get_session_info("test-123")

        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_healthcheck(self, client: SessionClient) -> None:
        """healthcheck() calls GET /healthz."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}
        mock_response.raise_for_status = MagicMock()

        with patch("amplifier_ipc_cli.client.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_instance

            result = await client.healthcheck()

        assert result is True


class TestSSEEvent:
    """Tests for SSEEvent dataclass."""

    def test_from_lines_parses_event_and_data(self) -> None:
        """SSEEvent.from_lines parses event type and JSON data."""
        event = SSEEvent.from_lines("event: token\ndata: {\"token\":\"hi\"}")
        assert event.event == "token"
        assert event.data == {"token": "hi"}

    def test_from_lines_data_only(self) -> None:
        """SSEEvent.from_lines with data-only defaults event to 'message'."""
        event = SSEEvent.from_lines("data: {\"x\":1}")
        assert event.event == "message"
        assert event.data == {"x": 1}

    def test_from_lines_empty_returns_none(self) -> None:
        """SSEEvent.from_lines returns None for empty input."""
        event = SSEEvent.from_lines("")
        assert event is None
```

**Step 2: Create the project scaffold**

Create `amplifier-ipc-cli/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-ipc-cli"
version = "0.1.0"
description = "Amplifier IPC CLI — thin HTTP client to the session-service"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.28",
    "click>=8.1.0",
    "rich>=13.0.0",
    "prompt-toolkit>=3.0.52",
    "pyyaml>=6.0",
]

[project.scripts]
amplifier = "amplifier_ipc_cli.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_ipc_cli"]

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
    "pyright>=1.1",
    "ruff>=0.4",
]
```

Create `amplifier-ipc-cli/src/amplifier_ipc_cli/__init__.py` (empty).

**Step 3: Write the client implementation**

Create `amplifier-ipc-cli/src/amplifier_ipc_cli/client.py`:

```python
"""HTTP client for the Amplifier session-service.

Provides SessionClient for sending turn requests (both synchronous and SSE
streaming) and querying session metadata.  Also provides SSEEvent for parsing
Server-Sent Events from the streaming endpoint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

_DEFAULT_BASE_URL = "http://localhost:8080"
_TIMEOUT = 120.0


@dataclass
class SSEEvent:
    """A parsed Server-Sent Event."""

    event: str
    data: dict[str, Any]

    @classmethod
    def from_lines(cls, raw: str) -> SSEEvent | None:
        """Parse an SSE event from raw text lines.

        Args:
            raw: The raw SSE text block (lines separated by newlines).

        Returns:
            An SSEEvent instance, or None if the input is empty.
        """
        raw = raw.strip()
        if not raw:
            return None

        event_type = "message"
        data_str = ""

        for line in raw.split("\n"):
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data_str = line.removeprefix("data: ").strip()

        if not data_str:
            return None

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            data = {"raw": data_str}

        return cls(event=event_type, data=data)


class SessionClient:
    """HTTP client for the session-service API.

    Attributes:
        base_url: Base URL of the session-service (default: http://localhost:8080).
    """

    def __init__(self, base_url: str = _DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    async def healthcheck(self) -> bool:
        """Check if the session-service is healthy.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/healthz", timeout=5.0
                )
                response.raise_for_status()
                return response.json().get("status") == "healthy"
        except Exception:
            return False

    async def send_turn(
        self,
        session_id: str,
        prompt: str,
        workspace_content: dict[str, str] | None = None,
        provider_name: str = "mock",
        services: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send a non-streaming turn request.

        Args:
            session_id: The session identifier.
            prompt: The user prompt text.
            workspace_content: Optional workspace file content to inject.
            provider_name: Provider to use (default: 'mock').
            services: Optional list of service app-ids to use.

        Returns:
            The turn response dict with 'session_id', 'result', 'messages'.
        """
        payload: dict[str, Any] = {
            "prompt": prompt,
            "provider_name": provider_name,
        }
        if workspace_content:
            payload["workspace_content"] = workspace_content
        if services:
            payload["services"] = services

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/sessions/{session_id}/turn",
                json=payload,
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()

    async def stream_turn(
        self,
        session_id: str,
        prompt: str,
        workspace_content: dict[str, str] | None = None,
        provider_name: str = "mock",
        services: list[str] | None = None,
    ) -> AsyncIterator[SSEEvent]:
        """Send a streaming turn request and yield SSE events.

        Args:
            session_id: The session identifier.
            prompt: The user prompt text.
            workspace_content: Optional workspace file content to inject.
            provider_name: Provider to use (default: 'mock').
            services: Optional list of service app-ids to use.

        Yields:
            SSEEvent instances parsed from the response stream.
        """
        payload: dict[str, Any] = {
            "prompt": prompt,
            "provider_name": provider_name,
        }
        if workspace_content:
            payload["workspace_content"] = workspace_content
        if services:
            payload["services"] = services

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/sessions/{session_id}/turn/stream",
                json=payload,
                timeout=httpx.Timeout(_TIMEOUT, connect=10.0),
            ) as response:
                response.raise_for_status()
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    # SSE events are separated by double newlines
                    while "\n\n" in buffer:
                        event_text, buffer = buffer.split("\n\n", 1)
                        sse_event = SSEEvent.from_lines(event_text)
                        if sse_event is not None:
                            yield sse_event

    async def get_session_info(self, session_id: str) -> dict[str, Any]:
        """Get session metadata.

        Args:
            session_id: The session identifier.

        Returns:
            Session info dict with 'session_id', 'status', 'turn_count'.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/sessions/{session_id}", timeout=10.0
            )
            response.raise_for_status()
            return response.json()
```

**Step 4: Install dependencies and run tests**

Run:
```bash
cd amplifier-ipc-cli && uv sync && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add amplifier-ipc-cli/ && git commit -m "feat(cli): add amplifier-ipc-cli package with SessionClient HTTP client"
```

---

## Task 3: Workspace Content Resolver

**Files:**
- Create: `amplifier-ipc-cli/src/amplifier_ipc_cli/workspace.py`
- Create: `amplifier-ipc-cli/tests/test_workspace.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-cli/tests/test_workspace.py`:

```python
"""Tests for workspace content resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_ipc_cli.workspace import resolve_workspace_content


class TestResolveWorkspaceContent:
    """Tests for resolve_workspace_content."""

    def test_reads_amplifier_dir_files(self, tmp_path: Path) -> None:
        """Reads .amplifier/ directory content files."""
        amp_dir = tmp_path / ".amplifier"
        amp_dir.mkdir()
        (amp_dir / "AGENTS.md").write_text("# Agents\nAgent definition here.")
        (amp_dir / "settings.yaml").write_text("provider: mock")

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/AGENTS.md" in result
        assert "Agent definition here" in result[".amplifier/AGENTS.md"]

    def test_skips_settings_yaml(self, tmp_path: Path) -> None:
        """Skips settings.yaml and settings.local.yaml from workspace content."""
        amp_dir = tmp_path / ".amplifier"
        amp_dir.mkdir()
        (amp_dir / "settings.yaml").write_text("provider: mock")
        (amp_dir / "settings.local.yaml").write_text("secret: x")
        (amp_dir / "AGENTS.md").write_text("# Agents")

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/settings.yaml" not in result
        assert ".amplifier/settings.local.yaml" not in result
        assert ".amplifier/AGENTS.md" in result

    def test_empty_when_no_amplifier_dir(self, tmp_path: Path) -> None:
        """Returns empty dict when .amplifier/ doesn't exist."""
        result = resolve_workspace_content(tmp_path)
        assert result == {}

    def test_skips_large_files(self, tmp_path: Path) -> None:
        """Skips files larger than 512KB."""
        amp_dir = tmp_path / ".amplifier"
        amp_dir.mkdir()
        (amp_dir / "huge.md").write_text("x" * (513 * 1024))
        (amp_dir / "small.md").write_text("small content")

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/huge.md" not in result
        assert ".amplifier/small.md" in result

    def test_skips_binary_files(self, tmp_path: Path) -> None:
        """Skips files that cannot be decoded as UTF-8."""
        amp_dir = tmp_path / ".amplifier"
        amp_dir.mkdir()
        (amp_dir / "binary.bin").write_bytes(b"\x80\x81\x82\x83")
        (amp_dir / "text.md").write_text("readable")

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/binary.bin" not in result
        assert ".amplifier/text.md" in result

    def test_reads_nested_directories(self, tmp_path: Path) -> None:
        """Reads files from nested subdirectories."""
        context_dir = tmp_path / ".amplifier" / "context"
        context_dir.mkdir(parents=True)
        (context_dir / "rules.md").write_text("# Rules")

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/context/rules.md" in result
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_workspace.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'amplifier_ipc_cli.workspace'`

**Step 3: Write the implementation**

Create `amplifier-ipc-cli/src/amplifier_ipc_cli/workspace.py`:

```python
"""Workspace content resolver.

Reads .amplifier/ directory files from the workspace root and returns them
as a dict suitable for sending as workspace_content in turn requests.

Excludes:
- settings.yaml and settings.local.yaml (contain user config, not context)
- Files larger than 512KB
- Binary files (non-UTF-8)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 512 * 1024  # 512KB
_EXCLUDED_FILENAMES = {"settings.yaml", "settings.local.yaml"}
_AMPLIFIER_DIR = ".amplifier"


def resolve_workspace_content(workspace_root: Path) -> dict[str, str]:
    """Resolve workspace content from the .amplifier/ directory.

    Walks the .amplifier/ directory recursively, reading all text files
    that are not excluded. Returns a dict mapping relative paths to file
    content.

    Args:
        workspace_root: The root directory of the workspace (typically cwd).

    Returns:
        Dict mapping relative file paths (e.g. ".amplifier/AGENTS.md")
        to their text content.
    """
    amplifier_dir = workspace_root / _AMPLIFIER_DIR
    if not amplifier_dir.is_dir():
        return {}

    content: dict[str, str] = {}

    for file_path in sorted(amplifier_dir.rglob("*")):
        if not file_path.is_file():
            continue

        if file_path.name in _EXCLUDED_FILENAMES:
            continue

        try:
            file_size = file_path.stat().st_size
        except OSError:
            continue

        if file_size > _MAX_FILE_SIZE:
            logger.debug("Skipping large file: %s (%d bytes)", file_path, file_size)
            continue

        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            logger.debug("Skipping unreadable file: %s", file_path)
            continue

        relative_path = str(file_path.relative_to(workspace_root))
        content[relative_path] = text

    return content
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_workspace.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add amplifier-ipc-cli/ && git commit -m "feat(cli): add workspace content resolver for .amplifier/ directory"
```

---

## Task 4: REPL Rewrite as HTTP Client

**Files:**
- Create: `amplifier-ipc-cli/src/amplifier_ipc_cli/repl.py`
- Create: `amplifier-ipc-cli/tests/test_repl.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-cli/tests/test_repl.py`:

```python
"""Tests for the HTTP-based REPL."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_ipc_cli.repl import (
    CancellationState,
    process_mentions,
    build_prompt_html,
)


class TestCancellationState:
    """Tests for CancellationState."""

    def test_initial_state(self) -> None:
        state = CancellationState()
        assert state.is_cancelled is False
        assert state.is_immediate is False

    def test_request_graceful(self) -> None:
        state = CancellationState()
        state.request_graceful()
        assert state.is_cancelled is True
        assert state.is_immediate is False

    def test_request_immediate(self) -> None:
        state = CancellationState()
        state.request_graceful()
        state.request_immediate()
        assert state.is_immediate is True

    def test_reset(self) -> None:
        state = CancellationState()
        state.request_graceful()
        state.request_immediate()
        state.reset()
        assert state.is_cancelled is False
        assert state.is_immediate is False


class TestProcessMentions:
    """Tests for @mention processing."""

    def test_no_mentions(self) -> None:
        """Input without @mentions is returned unchanged."""
        result = process_mentions("hello world", MagicMock())
        assert result == "hello world"

    def test_nonexistent_file_skipped(self) -> None:
        """@mention of a non-existent file is skipped."""
        console = MagicMock()
        result = process_mentions("check @/nonexistent/file.txt", console)
        # The @mention is stripped but no context block is added
        assert "<context_file" not in result

    def test_existing_file_injected(self, tmp_path) -> None:
        """@mention of an existing file is injected as context."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content here")

        console = MagicMock()
        result = process_mentions(f"check @{test_file}", console)
        assert "<context_file" in result
        assert "file content here" in result


class TestBuildPromptHtml:
    """Tests for build_prompt_html."""

    def test_no_mode(self) -> None:
        """No active mode shows green prompt."""
        html = build_prompt_html(None)
        assert "ansigreen" in str(html)

    def test_with_mode(self) -> None:
        """Active mode shows cyan prompt with mode name."""
        html = build_prompt_html("plan")
        assert "ansicyan" in str(html)
        assert "plan" in str(html)

    def test_html_escape(self) -> None:
        """Mode names with special chars are HTML-escaped."""
        html = build_prompt_html("<test>")
        assert "&lt;test&gt;" in str(html)
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_repl.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the REPL implementation**

Create `amplifier-ipc-cli/src/amplifier_ipc_cli/repl.py`:

```python
"""Interactive REPL for the Amplifier CLI — HTTP client to session-service.

This is a rewrite of src/amplifier_ipc/cli/repl.py. Instead of communicating
with in-process Host/orchestrator objects, it sends HTTP requests to the
session-service and renders SSE events.
"""

from __future__ import annotations

import asyncio
import re
import signal
import uuid
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.panel import Panel

from amplifier_ipc_cli.client import SessionClient, SSEEvent


# ---------------------------------------------------------------------------
# @mention processing
# ---------------------------------------------------------------------------

_MENTION_RE = re.compile(r"@([\w./~-]+)")


def process_mentions(user_input: str, console: Console) -> str:
    """Expand @path/to/file mentions in user_input.

    For each unique @path found, reads the file and prepends it as a
    <context_file> block before the user message. Unreadable paths are
    skipped with a printed warning.

    Args:
        user_input: Raw user input that may contain @path mentions.
        console: Rich console used to print warnings.

    Returns:
        Expanded string with <context_file> blocks prepended.
    """
    seen: dict[str, str] = {}

    for match in _MENTION_RE.finditer(user_input):
        raw_path = match.group(1)
        resolved = Path(raw_path).expanduser()
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved
        key = str(resolved)
        if key in seen:
            continue
        try:
            file_size = resolved.stat().st_size
            if file_size > 512 * 1024:
                console.print(
                    f"[yellow]Warning: @{raw_path} is too large "
                    f"({file_size} bytes > 512 KB limit)[/yellow]"
                )
                continue
            seen[key] = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            console.print(f"[yellow]Warning: could not read @{raw_path}[/yellow]")

    if not seen:
        return user_input

    stripped_msg = _MENTION_RE.sub("", user_input).strip()
    parts = [
        f'<context_file paths="{path}">\n{content}\n</context_file>'
        for path, content in seen.items()
    ]
    return "\n\n".join(parts) + "\n\n" + stripped_msg


# ---------------------------------------------------------------------------
# Cancellation state
# ---------------------------------------------------------------------------


class CancellationState:
    """Cooperative cancellation state for the REPL execution loop."""

    def __init__(self) -> None:
        self.is_cancelled: bool = False
        self.is_immediate: bool = False
        self.current_tool: str | None = None

    def request_graceful(self) -> None:
        self.is_cancelled = True

    def request_immediate(self) -> None:
        self.is_immediate = True

    def reset(self) -> None:
        self.is_cancelled = False
        self.is_immediate = False
        self.current_tool = None


# ---------------------------------------------------------------------------
# Prompt session factory
# ---------------------------------------------------------------------------


def _create_prompt_session(
    history_path: Path | None = None,
) -> PromptSession:  # type: ignore[type-arg]
    """Create a configured PromptSession with key bindings."""
    history = (
        FileHistory(str(history_path))
        if history_path is not None
        else InMemoryHistory()
    )

    bindings = KeyBindings()

    @bindings.add("c-j")
    def _insert_newline(event: Any) -> None:  # noqa: ANN401
        event.current_buffer.insert_text("\n")

    @bindings.add("enter")
    def _accept(event: Any) -> None:  # noqa: ANN401
        event.current_buffer.validate_and_handle()

    session: PromptSession = PromptSession(  # type: ignore[type-arg]
        history=history,
        multiline=True,
        key_bindings=bindings,
    )
    return session


def build_prompt_html(active_mode: str | None) -> HTML:
    """Return a prompt_toolkit HTML prompt reflecting the active mode.

    Args:
        active_mode: Name of the currently active mode, or None.

    Returns:
        Cyan [mode_name]> when a mode is active; green > otherwise.
    """
    if active_mode and isinstance(active_mode, str):
        safe = (
            str(active_mode)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return HTML(f"<ansicyan>[{safe}]&gt; </ansicyan>")
    return HTML("<ansigreen>&gt; </ansigreen>")


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = """[bold green]Amplifier Interactive REPL[/bold green]
Type your message and press [bold]Enter[/bold] to send.
Use [bold]Ctrl-J[/bold] for a newline within a message.
Type [bold]/help[/bold] for help, [bold]/exit[/bold] or [bold]/quit[/bold] to exit."""


# ---------------------------------------------------------------------------
# Main REPL entrypoint
# ---------------------------------------------------------------------------


async def interactive_repl(
    client: SessionClient,
    session_id: str | None = None,
    provider_name: str = "mock",
    workspace_content: dict[str, str] | None = None,
    console: Console | None = None,
    history_path: Path | None = None,
) -> None:
    """Run an interactive REPL loop using the session-service HTTP API.

    Args:
        client: SessionClient instance for HTTP communication.
        session_id: Session ID to use. If None, generates a new one.
        provider_name: Provider to use for turns.
        workspace_content: Pre-resolved workspace content dict.
        console: Optional Rich Console for output.
        history_path: Optional path for persistent REPL history.
    """
    if console is None:
        console = Console(stderr=True)

    if session_id is None:
        session_id = uuid.uuid4().hex[:16]

    console.print(Panel(BANNER, title="Amplifier REPL", border_style="green"))

    prompt_session = _create_prompt_session(history_path=history_path)

    # Import display and slash commands lazily to avoid circular imports
    from amplifier_ipc_cli.display import StreamingDisplay  # noqa: PLC0415
    from amplifier_ipc_cli.commands import dispatch_slash  # noqa: PLC0415

    active_mode: str | None = None
    _pending_prompt: str | None = None

    while True:
        if _pending_prompt is not None:
            user_input = _pending_prompt
            _pending_prompt = None
        else:
            try:
                user_input = await prompt_session.prompt_async(
                    build_prompt_html(active_mode),
                )
            except EOFError:
                console.print("\n[dim]Goodbye![/dim]")
                break
            except KeyboardInterrupt:
                console.print()
                console.print("[dim]Goodbye![/dim]")
                break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            console.print("[dim]Goodbye![/dim]")
            break

        # Handle slash commands
        if user_input.startswith("/"):
            result = await dispatch_slash(
                user_input, client, session_id, console
            )
            if result.should_exit:
                break
            if result.inline_prompt is not None:
                _pending_prompt = result.inline_prompt
            if result.new_mode is not None:
                active_mode = result.new_mode if result.new_mode != "" else None
            continue

        # @mention file injection
        user_input = process_mentions(user_input, console)

        # Execute turn via SSE streaming
        display = StreamingDisplay(console)
        cancellation = CancellationState()

        def _sigint_handler(signum: int, frame: Any) -> None:  # noqa: ANN401
            if cancellation.is_cancelled:
                cancellation.request_immediate()
                console.print("\n[bold red]Cancelling immediately...[/bold red]")
            else:
                cancellation.request_graceful()
                console.print(
                    "\n[yellow]Cancelling... (Ctrl+C again to force)[/yellow]"
                )

        original_handler = signal.signal(signal.SIGINT, _sigint_handler)

        try:
            async for sse_event in client.stream_turn(
                session_id=session_id,
                prompt=user_input,
                workspace_content=workspace_content,
                provider_name=provider_name,
            ):
                if cancellation.is_immediate:
                    break
                display.handle_sse_event(sse_event)
        except Exception as exc:  # noqa: BLE001
            console.print(f"\n[red]Error: {exc}[/red]")
        finally:
            signal.signal(signal.SIGINT, original_handler)

    # Exit message
    console.print(f"\n[dim]Session: {session_id}[/dim]")
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_repl.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add amplifier-ipc-cli/ && git commit -m "feat(cli): add HTTP-based interactive REPL with @mention support"
```

---

## Task 5: Streaming Display (SSE Event Renderer)

**Files:**
- Create: `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py`
- Create: `amplifier-ipc-cli/tests/test_display.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-cli/tests/test_display.py`:

```python
"""Tests for StreamingDisplay — renders SSE events to Rich console."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest
from rich.console import Console

from amplifier_ipc_cli.client import SSEEvent
from amplifier_ipc_cli.display import StreamingDisplay


def _make_console() -> tuple[Console, StringIO]:
    """Create a Console writing to a StringIO buffer."""
    buf = StringIO()
    console = Console(file=buf, no_color=True, width=80)
    return console, buf


class TestStreamingDisplay:
    """Tests for StreamingDisplay event handling."""

    def test_handle_token_event(self) -> None:
        """Token events print the token text."""
        console, buf = _make_console()
        display = StreamingDisplay(console)

        display.handle_sse_event(SSEEvent(event="token", data={"token": "hello"}))

        output = buf.getvalue()
        assert "hello" in output

    def test_handle_thinking_event(self) -> None:
        """Thinking events print thinking text."""
        console, buf = _make_console()
        display = StreamingDisplay(console)

        display.handle_sse_event(
            SSEEvent(event="thinking", data={"thinking": "hmm"})
        )

        output = buf.getvalue()
        assert "hmm" in output

    def test_handle_tool_call_event(self) -> None:
        """Tool call events print the tool name and arguments."""
        console, buf = _make_console()
        display = StreamingDisplay(console)

        display.handle_sse_event(
            SSEEvent(
                event="tool_call",
                data={"tool_name": "bash", "arguments": {"command": "ls"}},
            )
        )

        output = buf.getvalue()
        assert "bash" in output

    def test_handle_tool_result_success(self) -> None:
        """Tool result events with success show green indicator."""
        console, buf = _make_console()
        display = StreamingDisplay(console)

        display.handle_sse_event(
            SSEEvent(
                event="tool_result",
                data={"tool_name": "bash", "success": True, "output": "file.txt"},
            )
        )

        output = buf.getvalue()
        assert "bash" in output

    def test_handle_tool_result_failure(self) -> None:
        """Tool result events with failure show red indicator."""
        console, buf = _make_console()
        display = StreamingDisplay(console)

        display.handle_sse_event(
            SSEEvent(
                event="tool_result",
                data={"tool_name": "bash", "success": False, "output": "error msg"},
            )
        )

        output = buf.getvalue()
        assert "bash" in output

    def test_handle_complete_event(self) -> None:
        """Complete events store the result."""
        console, buf = _make_console()
        display = StreamingDisplay(console)

        display.handle_sse_event(
            SSEEvent(event="complete", data={"result": "final answer"})
        )

        assert display.response == "final answer"

    def test_handle_error_event(self) -> None:
        """Error events print the error message."""
        console, buf = _make_console()
        display = StreamingDisplay(console)

        display.handle_sse_event(
            SSEEvent(event="error", data={"message": "something broke"})
        )

        output = buf.getvalue()
        assert "something broke" in output

    def test_handle_todo_update(self) -> None:
        """Todo update events render the todo list."""
        console, buf = _make_console()
        display = StreamingDisplay(console)

        display.handle_sse_event(
            SSEEvent(
                event="todo_update",
                data={
                    "todos": [
                        {"content": "Task 1", "status": "completed"},
                        {"content": "Task 2", "status": "in_progress"},
                    ]
                },
            )
        )

        output = buf.getvalue()
        assert "Task 1" in output or "1/" in output  # Either individual or summary

    def test_unknown_event_ignored(self) -> None:
        """Unknown event types are silently ignored."""
        console, buf = _make_console()
        display = StreamingDisplay(console)

        # Should not raise
        display.handle_sse_event(
            SSEEvent(event="unknown_type", data={"foo": "bar"})
        )
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_display.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the display implementation**

Create `amplifier-ipc-cli/src/amplifier_ipc_cli/display.py`:

```python
"""Streaming display — renders SSE events from the session-service to a Rich console.

This is a rewrite of src/amplifier_ipc/cli/streaming.py. Instead of consuming
HostEvent Pydantic objects, it processes SSEEvent dicts received over HTTP.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from amplifier_ipc_cli.client import SSEEvent

_DEFAULT_TOOL_ARG_VALUE_LEN = 200
_DEFAULT_TOOL_ARGS_COUNT = 10
_DEFAULT_TOOL_RESULT_LINES = 10
_DEFAULT_TOOL_RESULT_LINE_LEN = 200


class StreamingDisplay:
    """Renders SSE streaming events to a Rich console.

    Args:
        console: Rich Console instance for output.
        show_thinking: Whether to render thinking text (default True).
    """

    def __init__(
        self,
        console: Console,
        show_thinking: bool = True,
    ) -> None:
        self._console = console
        self._show_thinking = show_thinking
        self._response: str | None = None

    @property
    def response(self) -> str | None:
        """The final response text from the most recent complete event."""
        return self._response

    def handle_sse_event(self, event: SSEEvent) -> None:
        """Dispatch an SSE event to the appropriate handler."""
        handler_name = f"_handle_{event.event}"
        handler = getattr(self, handler_name, None)
        if handler is not None:
            handler(event.data)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_token(self, data: dict[str, Any]) -> None:
        """Print token text."""
        token = data.get("token", "")
        self._console.print(token, end="", markup=False, highlight=False)

    def _handle_thinking(self, data: dict[str, Any]) -> None:
        """Print thinking text in dim style."""
        if self._show_thinking:
            thinking = data.get("thinking", "")
            self._console.print(thinking, end="", style="cyan dim", markup=False)

    def _handle_content_block_start(self, data: dict[str, Any]) -> None:
        """Print thinking block header."""
        if data.get("block_type") == "thinking" and self._show_thinking:
            border = "\u2554" + "\u2550" * 50 + "\u2557"
            self._console.print("\U0001f9e0 Thinking...", style="dim", markup=False)
            self._console.print(border, style="dim", markup=False)

    def _handle_content_block_end(self, data: dict[str, Any]) -> None:
        """Print thinking block footer."""
        if data.get("block_type") == "thinking" and self._show_thinking:
            border = "\u255a" + "\u2550" * 50 + "\u255d"
            self._console.print("\n" + border, style="dim", markup=False)

    def _handle_tool_call_start(self, data: dict[str, Any]) -> None:
        """Print tool call start indicator."""
        tool_name = data.get("tool_name", "")
        self._console.print(f"\n[dim]\U0001f527 {tool_name}[/dim]")

    def _handle_tool_call(self, data: dict[str, Any]) -> None:
        """Print tool call arguments."""
        tool_name = data.get("tool_name", "")
        arguments = data.get("arguments", {})

        self._console.print(f"\n\U0001f527 [bold]{tool_name}[/bold]")
        items = list(arguments.items())
        for key, value in items[:_DEFAULT_TOOL_ARGS_COUNT]:
            truncated = str(value)[:_DEFAULT_TOOL_ARG_VALUE_LEN]
            self._console.print(
                f"   [dim]{key}:[/dim] {truncated}",
                markup=True,
                highlight=False,
            )
        remaining = len(items) - _DEFAULT_TOOL_ARGS_COUNT
        if remaining > 0:
            self._console.print(f"   [dim]... ({remaining} more)[/dim]")

    def _handle_tool_result(self, data: dict[str, Any]) -> None:
        """Print tool result with success/failure icon."""
        tool_name = data.get("tool_name", "")
        success = data.get("success", True)
        output = data.get("output", "")

        if success:
            icon = "\u2705"
            style = "green"
        else:
            icon = "\u274c"
            style = "red"

        self._console.print(f"{icon} {tool_name}", style=style, markup=False)

        lines = output.split("\n")
        for line in lines[:_DEFAULT_TOOL_RESULT_LINES]:
            self._console.print(
                f"   {line[:_DEFAULT_TOOL_RESULT_LINE_LEN]}",
                style="dim",
                markup=False,
                highlight=False,
            )
        remaining = len(lines) - _DEFAULT_TOOL_RESULT_LINES
        if remaining > 0:
            self._console.print(
                f"   ... ({remaining} more lines)",
                style="dim",
                markup=False,
            )

    def _handle_todo_update(self, data: dict[str, Any]) -> None:
        """Render a todo list box."""
        todos = data.get("todos", [])
        if not todos:
            return

        symbols = {
            "completed": "\u2713",
            "in_progress": "\u25b6",
            "pending": "\u25cb",
        }
        total = len(todos)
        completed = sum(1 for t in todos if t.get("status") == "completed")
        box_width = 50

        top = "\u250c" + "\u2500" * box_width + "\u2510"
        bottom = "\u2514" + "\u2500" * box_width + "\u2518"
        self._console.print(top, markup=False)

        if total <= 7:
            for todo in todos:
                status = todo.get("status", "pending")
                symbol = symbols.get(status, " ")
                content = str(todo.get("content", ""))
                inner_width = box_width - 4
                if len(content) > inner_width:
                    content = content[: inner_width - 3] + "..."
                line = f"\u2502 {symbol} {content}"
                padding = box_width - len(f" {symbol} {content}")
                if padding > 0:
                    line += " " * padding
                line += "\u2502"
                self._console.print(line, markup=False)
        else:
            in_progress = sum(
                1 for t in todos if t.get("status") == "in_progress"
            )
            pending = total - completed - in_progress
            summary = (
                f"\u2502 {symbols['completed']} {completed} completed  "
                f"{symbols['in_progress']} {in_progress} in progress  "
                f"{symbols['pending']} {pending} pending"
            )
            padding = box_width - (len(summary) - 1)
            if padding > 0:
                summary += " " * padding
            summary += "\u2502"
            self._console.print(summary, markup=False)

        # Progress bar
        bar_width = 20
        filled = int(bar_width * completed / total) if total > 0 else 0
        empty = bar_width - filled
        bar = "\u2588" * filled + "\u2591" * empty
        progress_text = f"{completed}/{total}"
        progress_line = f"\u2502 {bar} {progress_text}"
        padding = box_width - len(f" {bar} {progress_text}")
        if padding > 0:
            progress_line += " " * padding
        progress_line += "\u2502"
        self._console.print(progress_line, markup=False)
        self._console.print(bottom, markup=False)

    def _handle_child_session_start(self, data: dict[str, Any]) -> None:
        """Print delegation header."""
        agent_name = data.get("agent_name", "")
        depth = data.get("depth", 1)
        indent = "    " * (depth - 1)
        self._console.print(
            f"{indent}\U0001f527 [bold cyan]delegate -> {agent_name}[/bold cyan]"
        )

    def _handle_child_session_end(self, data: dict[str, Any]) -> None:
        """Child session end — no output needed."""
        pass

    def _handle_error(self, data: dict[str, Any]) -> None:
        """Print error message."""
        message = data.get("message", "Unknown error")
        self._console.print(f"\u2717 {message}", style="red", markup=False)

    def _handle_complete(self, data: dict[str, Any]) -> None:
        """Store the final response."""
        self._response = data.get("result", "")
        self._console.print()
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_display.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add amplifier-ipc-cli/ && git commit -m "feat(cli): add SSE event streaming display renderer"
```

---

## Task 6: Slash Commands

**Files:**
- Create: `amplifier-ipc-cli/src/amplifier_ipc_cli/commands.py`
- Create: `amplifier-ipc-cli/tests/test_commands.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-cli/tests/test_commands.py`:

```python
"""Tests for slash command dispatcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from amplifier_ipc_cli.commands import dispatch_slash, SlashResult


class TestSlashResult:
    """Tests for SlashResult dataclass."""

    def test_defaults(self) -> None:
        result = SlashResult()
        assert result.should_exit is False
        assert result.inline_prompt is None
        assert result.new_mode is None


class TestDispatchSlash:
    """Tests for dispatch_slash."""

    @pytest.fixture
    def client(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def console(self) -> MagicMock:
        return MagicMock()

    @pytest.mark.asyncio
    async def test_exit(self, client, console) -> None:
        result = await dispatch_slash("/exit", client, "sess-1", console)
        assert result.should_exit is True

    @pytest.mark.asyncio
    async def test_quit(self, client, console) -> None:
        result = await dispatch_slash("/quit", client, "sess-1", console)
        assert result.should_exit is True

    @pytest.mark.asyncio
    async def test_help(self, client, console) -> None:
        result = await dispatch_slash("/help", client, "sess-1", console)
        assert result.should_exit is False
        console.print.assert_called()

    @pytest.mark.asyncio
    async def test_status(self, client, console) -> None:
        """Status calls client.get_session_info."""
        client.get_session_info = AsyncMock(
            return_value={"session_id": "s1", "status": "active", "turn_count": 3}
        )
        result = await dispatch_slash("/status", client, "s1", console)
        assert result.should_exit is False
        client.get_session_info.assert_awaited_once_with("s1")

    @pytest.mark.asyncio
    async def test_tools(self, client, console) -> None:
        """Tools calls client.get_tools."""
        client.get_tools = AsyncMock(return_value=[])
        result = await dispatch_slash("/tools", client, "s1", console)
        assert result.should_exit is False

    @pytest.mark.asyncio
    async def test_clear(self, client, console) -> None:
        """Clear calls client.clear_session."""
        client.clear_session = AsyncMock(return_value=True)
        result = await dispatch_slash("/clear", client, "s1", console)
        assert result.should_exit is False

    @pytest.mark.asyncio
    async def test_unknown_command(self, client, console) -> None:
        """Unknown commands print a warning."""
        result = await dispatch_slash("/foobar", client, "s1", console)
        assert result.should_exit is False
        # Verify the console received a warning
        console.print.assert_called()
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_commands.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the commands implementation**

Create `amplifier-ipc-cli/src/amplifier_ipc_cli/commands.py`:

```python
"""Slash command dispatcher for the Amplifier REPL.

Each slash command is dispatched to an async handler that communicates
with the session-service via the SessionClient HTTP API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from amplifier_ipc_cli.client import SessionClient


@dataclass
class SlashResult:
    """Result of a slash command dispatch.

    Attributes:
        should_exit: True if the REPL should exit.
        inline_prompt: If set, send this as the next prompt without reading input.
        new_mode: If set, change the active mode to this value ("" to clear).
    """

    should_exit: bool = False
    inline_prompt: str | None = None
    new_mode: str | None = None


_HELP_TEXT = """\
Available commands:
  /help                  Show this help message
  /exit  /quit           Exit the REPL
  /status                Show session info (turn count, status)
  /tools                 List available tools
  /clear                 Clear the conversation context
  /modes                 List available modes
  /mode [NAME] [on|off]  Set/clear active mode

Press Enter to send.  Use Ctrl-J for a newline within a message.
"""


async def dispatch_slash(
    raw: str,
    client: SessionClient,
    session_id: str,
    console: Console,
) -> SlashResult:
    """Dispatch a slash command to the appropriate handler.

    Args:
        raw: The full slash command string (e.g. "/status").
        client: SessionClient for HTTP communication.
        session_id: The current session ID.
        console: Rich console for output.

    Returns:
        SlashResult with instructions for the REPL loop.
    """
    parts = raw.split(None, 2)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    rest = parts[2] if len(parts) > 2 else ""

    if command in ("/exit", "/quit"):
        console.print("[dim]Goodbye![/dim]")
        return SlashResult(should_exit=True)

    if command == "/help":
        console.print(_HELP_TEXT)
        return SlashResult()

    if command == "/status":
        await _cmd_status(client, session_id, console)
        return SlashResult()

    if command == "/tools":
        await _cmd_tools(client, session_id, console)
        return SlashResult()

    if command == "/clear":
        await _cmd_clear(client, session_id, console)
        return SlashResult()

    if command == "/modes":
        await _cmd_modes(client, session_id, console)
        return SlashResult()

    if command == "/mode":
        return await _cmd_mode(client, session_id, console, args, rest)

    console.print(f"[yellow]Unknown command: {command}[/yellow]")
    return SlashResult()


async def _cmd_status(
    client: SessionClient, session_id: str, console: Console
) -> None:
    """Display session status panel."""
    try:
        info = await client.get_session_info(session_id)
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column()
        table.add_row("Session ID", info.get("session_id", session_id))
        table.add_row("Status", info.get("status", "unknown"))
        table.add_row("Turn Count", str(info.get("turn_count", 0)))
        console.print(Panel(table, title="Session Status", border_style="cyan"))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not get status: {exc}[/yellow]")


async def _cmd_tools(
    client: SessionClient, session_id: str, console: Console
) -> None:
    """List registered tools."""
    try:
        tools = await client.get_tools(session_id)
        if not tools:
            console.print("[dim]No tools available.[/dim]")
            return
        table = Table("Name", "Description", show_header=True, header_style="bold")
        for t in tools:
            desc = t.get("description", "")
            if len(desc) > 80:
                desc = desc[:77] + "\u2026"
            table.add_row(t.get("name", ""), desc)
        console.print(table)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not list tools: {exc}[/yellow]")


async def _cmd_clear(
    client: SessionClient, session_id: str, console: Console
) -> None:
    """Clear conversation context."""
    try:
        await client.clear_session(session_id)
        console.print("[dim]Conversation context cleared.[/dim]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not clear context: {exc}[/yellow]")


async def _cmd_modes(
    client: SessionClient, session_id: str, console: Console
) -> None:
    """List available modes."""
    try:
        modes = await client.get_modes(session_id)
        if not modes:
            console.print("[dim]No modes available.[/dim]")
            return
        table = Table("Mode", show_header=True, header_style="bold")
        for m in modes:
            table.add_row(m.get("name", ""))
        console.print(table)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Could not list modes: {exc}[/yellow]")


async def _cmd_mode(
    client: SessionClient,
    session_id: str,
    console: Console,
    args: str,
    rest: str,
) -> SlashResult:
    """Handle /mode [NAME] [on|off]."""
    if not args:
        console.print("[dim]No active mode.[/dim]")
        return SlashResult()

    mode_name = args.strip()
    flag = rest.strip().lower()

    if mode_name.lower() in ("off", "none", "clear"):
        console.print("[dim]Mode cleared.[/dim]")
        return SlashResult(new_mode="")

    if flag == "off":
        console.print("[dim]Mode cleared.[/dim]")
        return SlashResult(new_mode="")

    console.print(f"[cyan]Mode set:[/cyan] [bold]{mode_name}[/bold]")
    return SlashResult(new_mode=mode_name)
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_commands.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add amplifier-ipc-cli/ && git commit -m "feat(cli): add slash command dispatcher for REPL"
```

---

## Task 7: Session-Service Metadata Endpoints

**Files:**
- Modify: `services/session-service/src/session_service/app.py`
- Create: `services/session-service/tests/test_metadata.py`
- Modify: `amplifier-ipc-cli/src/amplifier_ipc_cli/client.py`

**Step 1: Write the failing tests**

Create `services/session-service/tests/test_metadata.py`:

```python
"""Tests for session-service metadata endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from session_service.app import create_session_app


class TestMetadataEndpoints:
    """Tests for metadata endpoints used by the CLI."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = create_session_app(dapr_url="http://localhost:3500")
        return TestClient(app)

    def test_get_tools_returns_empty_before_turn(self, client: TestClient) -> None:
        """GET /sessions/{id}/tools returns empty list for new session."""
        response = client.get("/sessions/new-session/tools")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert isinstance(data["tools"], list)

    def test_get_modes_returns_empty(self, client: TestClient) -> None:
        """GET /sessions/{id}/modes returns empty list."""
        response = client.get("/sessions/new-session/modes")
        assert response.status_code == 200
        data = response.json()
        assert "modes" in data
        assert isinstance(data["modes"], list)

    def test_clear_session_returns_ok(self, client: TestClient) -> None:
        """POST /sessions/{id}/clear returns success."""
        response = client.post("/sessions/new-session/clear")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cleared"
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd services/session-service && uv run pytest tests/test_metadata.py -v
```
Expected: FAIL with 404s.

**Step 3: Add metadata endpoints to session-service**

In `services/session-service/src/session_service/app.py`, add these endpoints inside `create_session_app()`:

```python
    @app.get("/sessions/{session_id}/tools")
    async def session_tools(session_id: str) -> dict[str, Any]:
        """Return the list of tools available in the session's routing table.

        If the session has been through at least one turn, returns the tools
        from the most recent discovery. Otherwise returns an empty list.
        """
        session = _sessions.get(session_id)
        tools: list[dict[str, Any]] = []
        if session and "routing_table" in session:
            tools = session["routing_table"].get("_tool_specs", [])
        return {"tools": tools}

    @app.get("/sessions/{session_id}/modes")
    async def session_modes(session_id: str) -> dict[str, Any]:
        """Return the list of available modes for the session.

        Currently returns an empty list — will be populated when the modes
        service integrates with the session-service metadata.
        """
        return {"modes": []}

    @app.post("/sessions/{session_id}/clear")
    async def clear_session(session_id: str) -> dict[str, Any]:
        """Clear the session's conversation context.

        Resets the turn count and removes the session from in-memory state.
        """
        if session_id in _sessions:
            _sessions[session_id] = {"turn_count": 0, "status": "active"}
        return {"status": "cleared"}
```

Also update the `turn` endpoint to store the routing_table in `_sessions` after discovery:

After the `routing_table_dict = await discover_services(...)` line in the `turn` endpoint, add:

```python
            _sessions[session_id]["routing_table"] = routing_table_dict
```

**Step 4: Add client methods for metadata**

In `amplifier-ipc-cli/src/amplifier_ipc_cli/client.py`, add these methods to the `SessionClient` class:

```python
    async def get_tools(self, session_id: str) -> list[dict[str, Any]]:
        """Get tools available in the session.

        Args:
            session_id: The session identifier.

        Returns:
            List of tool dicts with 'name' and 'description'.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/sessions/{session_id}/tools", timeout=10.0
            )
            response.raise_for_status()
            return response.json().get("tools", [])

    async def get_modes(self, session_id: str) -> list[dict[str, Any]]:
        """Get available modes for the session.

        Args:
            session_id: The session identifier.

        Returns:
            List of mode dicts with 'name'.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/sessions/{session_id}/modes", timeout=10.0
            )
            response.raise_for_status()
            return response.json().get("modes", [])

    async def clear_session(self, session_id: str) -> bool:
        """Clear the session's conversation context.

        Args:
            session_id: The session identifier.

        Returns:
            True if cleared successfully.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/sessions/{session_id}/clear", timeout=10.0
            )
            response.raise_for_status()
            return response.json().get("status") == "cleared"
```

**Step 5: Run tests**

Run:
```bash
cd services/session-service && uv run pytest tests/test_metadata.py -v
cd amplifier-ipc-cli && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 6: Commit**

```bash
git add services/session-service/ amplifier-ipc-cli/ && git commit -m "feat(session-service,cli): add metadata endpoints for tools, modes, clear"
```

---

## Task 8: Single-Turn Mode (Non-Interactive)

**Files:**
- Create: `amplifier-ipc-cli/src/amplifier_ipc_cli/main.py`
- Create: `amplifier-ipc-cli/tests/test_main.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-cli/tests/test_main.py`:

```python
"""Tests for the CLI entry point and run command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from amplifier_ipc_cli.main import cli


class TestCLI:
    """Tests for the Click CLI group."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_help(self, runner: CliRunner) -> None:
        """--help exits 0 and shows usage."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Amplifier" in result.output

    def test_version(self, runner: CliRunner) -> None:
        """version command prints version."""
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_run_help(self, runner: CliRunner) -> None:
        """run --help shows usage."""
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "MESSAGE" in result.output or "message" in result.output.lower()

    def test_run_with_message_requires_service(self, runner: CliRunner) -> None:
        """run with MESSAGE but no running service prints connection error."""
        result = runner.invoke(
            cli, ["run", "--url", "http://localhost:99999", "Hello"]
        )
        # Should fail gracefully with connection error
        assert result.exit_code != 0 or "Error" in result.output or "error" in result.output.lower()
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_main.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the main module**

Create `amplifier-ipc-cli/src/amplifier_ipc_cli/main.py`:

```python
"""Amplifier CLI entry point — thin HTTP client to session-service.

Replaces the in-process amplifier-ipc CLI with HTTP calls to the
session-service running inside Docker Compose.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from amplifier_ipc_cli.client import SessionClient
from amplifier_ipc_cli.workspace import resolve_workspace_content

_DEFAULT_URL = "http://localhost:8080"


@click.group()
def cli() -> None:
    """Amplifier CLI — interact with the Amplifier session-service."""


@cli.command()
def version() -> None:
    """Print the CLI version."""
    click.echo("amplifier-ipc-cli 0.1.0")


@cli.command()
@click.option(
    "--url",
    default=_DEFAULT_URL,
    help=f"Session-service URL (default: {_DEFAULT_URL}).",
    envvar="AMPLIFIER_URL",
)
@click.option("--session", "-s", default=None, help="Session ID to resume.")
@click.option(
    "--provider",
    "-p",
    default="mock",
    help="Provider to use (default: mock).",
)
@click.option(
    "--workspace",
    "-w",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Workspace root directory (default: cwd).",
)
@click.option(
    "--output-format",
    "-o",
    default="text",
    type=click.Choice(["text", "json"], case_sensitive=False),
    help="Output format (default: text).",
)
@click.argument("message", required=False)
def run(
    url: str,
    session: str | None,
    provider: str,
    workspace: str | None,
    output_format: str,
    message: str | None,
) -> None:
    """Run a session. If MESSAGE is given, execute single-turn and exit.
    Otherwise enter interactive REPL.

    \\b
    Examples:
      amplifier run "What is 2+2?"
      amplifier run --provider anthropic "Hello"
      echo "Hello" | amplifier run -o json
    """
    asyncio.run(
        _run_impl(url, session, provider, workspace, output_format, message)
    )


async def _run_impl(
    url: str,
    session: str | None,
    provider: str,
    workspace: str | None,
    output_format: str,
    message: str | None,
) -> None:
    """Async implementation of the run command."""
    is_json = output_format == "json"
    is_pipe = not sys.stdin.isatty()

    # Read from stdin if piped and no message provided
    if is_pipe and message is None:
        piped = sys.stdin.read().strip()
        if piped:
            message = piped
        else:
            if is_json:
                _emit_json_error("Empty stdin and no MESSAGE provided.")
            else:
                click.echo("Error: empty stdin and no MESSAGE provided.", err=True)
            raise SystemExit(1)

    client = SessionClient(base_url=url)
    session_id = session or uuid.uuid4().hex[:16]
    workspace_root = Path(workspace) if workspace else Path.cwd()
    workspace_content = resolve_workspace_content(workspace_root)

    console = Console(stderr=True) if is_json else Console()

    if message is not None:
        # Single-turn mode
        from amplifier_ipc_cli.display import StreamingDisplay  # noqa: PLC0415

        display = StreamingDisplay(console)

        try:
            async for sse_event in client.stream_turn(
                session_id=session_id,
                prompt=message,
                workspace_content=workspace_content,
                provider_name=provider,
            ):
                if not is_json:
                    display.handle_sse_event(sse_event)
                else:
                    # In JSON mode, just accumulate the result
                    if sse_event.event == "complete":
                        display._response = sse_event.data.get("result", "")
        except Exception as exc:
            if is_json:
                _emit_json_error(str(exc), session_id)
            else:
                click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1)

        if is_json:
            result: dict[str, Any] = {
                "status": "success",
                "response": display.response or "",
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            sys.stdout.write(json.dumps(result) + "\n")
            sys.stdout.flush()
    else:
        # Interactive REPL mode
        if is_pipe:
            click.echo("Error: cannot enter REPL with piped stdin.", err=True)
            raise SystemExit(1)

        # Check health first
        healthy = await client.healthcheck()
        if not healthy:
            console.print(
                f"[red]Cannot connect to session-service at {url}[/red]"
            )
            console.print(
                "[dim]Start the services with: docker compose up -d[/dim]"
            )
            raise SystemExit(1)

        from amplifier_ipc_cli.repl import interactive_repl  # noqa: PLC0415

        await interactive_repl(
            client=client,
            session_id=session_id,
            provider_name=provider,
            workspace_content=workspace_content,
            console=console,
        )


def _emit_json_error(
    message: str, session_id: str | None = None
) -> None:
    """Write a JSON error payload to stdout."""
    payload: dict[str, Any] = {
        "status": "error",
        "error": message,
        "session_id": session_id or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    """Entry point for the amplifier CLI."""
    cli()
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_main.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add amplifier-ipc-cli/ && git commit -m "feat(cli): add main entry point with single-turn mode and REPL dispatch"
```

---

## Task 9: CLI Settings Integration

**Files:**
- Create: `amplifier-ipc-cli/src/amplifier_ipc_cli/settings.py`
- Create: `amplifier-ipc-cli/tests/test_settings.py`

**Step 1: Write the failing tests**

Create `amplifier-ipc-cli/tests/test_settings.py`:

```python
"""Tests for CLI settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_ipc_cli.settings import CLISettings


class TestCLISettings:
    """Tests for CLISettings."""

    def test_default_url(self) -> None:
        """Default URL is http://localhost:8080."""
        settings = CLISettings()
        assert settings.url == "http://localhost:8080"

    def test_default_provider(self) -> None:
        """Default provider is 'mock'."""
        settings = CLISettings()
        assert settings.provider == "mock"

    def test_from_yaml(self, tmp_path: Path) -> None:
        """Settings can be loaded from a YAML file."""
        config_file = tmp_path / "settings.yaml"
        config_file.write_text(
            "url: http://my-server:9090\nprovider: anthropic\n"
        )
        settings = CLISettings.from_yaml(config_file)
        assert settings.url == "http://my-server:9090"
        assert settings.provider == "anthropic"

    def test_from_yaml_missing_file(self, tmp_path: Path) -> None:
        """Missing YAML file returns defaults."""
        settings = CLISettings.from_yaml(tmp_path / "missing.yaml")
        assert settings.url == "http://localhost:8080"

    def test_from_yaml_empty_file(self, tmp_path: Path) -> None:
        """Empty YAML file returns defaults."""
        config_file = tmp_path / "settings.yaml"
        config_file.write_text("")
        settings = CLISettings.from_yaml(config_file)
        assert settings.url == "http://localhost:8080"

    def test_get_history_path(self) -> None:
        """get_history_path returns a path under .amplifier/."""
        settings = CLISettings()
        path = settings.get_history_path()
        assert ".amplifier" in str(path)
        assert "repl_history" in str(path)
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_settings.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the settings module**

Create `amplifier-ipc-cli/src/amplifier_ipc_cli/settings.py`:

```python
"""CLI settings for amplifier-ipc-cli.

Reads configuration from ~/.amplifier/settings.yaml and
.amplifier/settings.yaml in the project directory, mirroring the
multi-scope settings pattern from the original CLI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:8080"
_DEFAULT_PROVIDER = "mock"


@dataclass
class CLISettings:
    """Settings for the Amplifier CLI.

    Attributes:
        url: Base URL of the session-service.
        provider: Default provider name.
    """

    url: str = _DEFAULT_URL
    provider: str = _DEFAULT_PROVIDER

    @classmethod
    def from_yaml(cls, path: Path) -> CLISettings:
        """Load settings from a YAML file.

        Args:
            path: Path to the YAML settings file.

        Returns:
            CLISettings populated from the file, with defaults for missing keys.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return cls()

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            return cls()

        if not isinstance(data, dict):
            return cls()

        return cls(
            url=data.get("url", _DEFAULT_URL),
            provider=data.get("provider", _DEFAULT_PROVIDER),
        )

    @classmethod
    def load_merged(cls) -> CLISettings:
        """Load and merge settings from global and project scopes.

        Reads from:
        1. ~/.amplifier/settings.yaml (global)
        2. .amplifier/settings.yaml (project)

        Project settings override global settings.

        Returns:
            Merged CLISettings.
        """
        global_path = Path.home() / ".amplifier" / "settings.yaml"
        project_path = Path.cwd() / ".amplifier" / "settings.yaml"

        global_settings = cls.from_yaml(global_path)
        project_settings = cls.from_yaml(project_path)

        # Project overrides global (non-default values take priority)
        url = (
            project_settings.url
            if project_settings.url != _DEFAULT_URL
            else global_settings.url
        )
        provider = (
            project_settings.provider
            if project_settings.provider != _DEFAULT_PROVIDER
            else global_settings.provider
        )

        return cls(url=url, provider=provider)

    def get_history_path(self) -> Path:
        """Return the REPL history file path.

        Returns:
            Path to the history file under ~/.amplifier/projects/<slug>/repl_history.
        """
        cwd = Path.cwd()
        home = Path.home()

        if cwd == home:
            slug = "global"
        else:
            try:
                rel = cwd.relative_to(home)
                slug = "~--" + str(rel).replace("/", "--")
            except ValueError:
                slug = cwd.name

        return home / ".amplifier" / "projects" / slug / "repl_history"
```

**Step 4: Run tests to verify they pass**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/test_settings.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add amplifier-ipc-cli/ && git commit -m "feat(cli): add CLI settings with YAML loading and history path"
```

---

## Task 10: Docker Compose Verification

**Files:**
- Modify: `docker-compose.yaml` (verify session-service port 8080 is exposed)

**Step 1: Verify the session-service is already exposed on port 8080**

Read `docker-compose.yaml` and confirm the session-service has `ports: ["8080:8000"]`. This is already present (see the reference patterns above). No changes needed.

**Step 2: Verify the CLI can reach the session-service**

Run:
```bash
# From the repo root, start only the session-service and its dependencies
docker compose up -d redis session-service session-service-dapr

# Wait for startup
sleep 5

# Test health endpoint from outside Docker
curl -s http://localhost:8080/healthz | python3 -m json.tool
```
Expected output:
```json
{
    "status": "healthy",
    "service_name": "session-service",
    "version": "0.1.0"
}
```

**Step 3: Test the CLI healthcheck against Docker**

Run:
```bash
cd amplifier-ipc-cli && uv sync && uv run python -c "
import asyncio
from amplifier_ipc_cli.client import SessionClient
async def check():
    c = SessionClient('http://localhost:8080')
    print('healthy:', await c.healthcheck())
asyncio.run(check())
"
```
Expected: `healthy: True`

**Step 4: Stop the Docker services**

Run:
```bash
docker compose down
```

**Step 5: Commit**

```bash
git add docker-compose.yaml && git commit -m "chore: verify session-service port 8080 exposed for CLI access" --allow-empty
```

---

## Task 11: End-to-End Integration Test

**Files:**
- Create: `amplifier-ipc-cli/tests/test_e2e.py`

**Step 1: Write the e2e test**

Create `amplifier-ipc-cli/tests/test_e2e.py`:

```python
"""End-to-end integration test for the CLI against session-service.

These tests require Docker Compose services to be running:
  docker compose up -d

Mark as 'slow' so they can be skipped in fast CI runs:
  pytest -m "not slow"
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

import pytest

from amplifier_ipc_cli.client import SessionClient


@pytest.fixture
def client() -> SessionClient:
    return SessionClient(base_url="http://localhost:8080")


def _service_is_running() -> bool:
    """Check if the session-service is reachable."""
    try:
        result = subprocess.run(
            ["curl", "-sf", "http://localhost:8080/healthz"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _service_is_running(),
    reason="Session-service not running (start with 'docker compose up -d')",
)


@pytest.mark.slow
class TestE2ESessionClient:
    """End-to-end tests for SessionClient against real services."""

    @pytest.mark.asyncio
    async def test_healthcheck(self, client: SessionClient) -> None:
        """Client can reach the session-service /healthz endpoint."""
        assert await client.healthcheck() is True

    @pytest.mark.asyncio
    async def test_send_turn(self, client: SessionClient) -> None:
        """Client can send a turn and get a response."""
        result = await client.send_turn(
            session_id="e2e-test-session",
            prompt="Hello, world!",
            provider_name="mock",
        )
        assert "session_id" in result
        assert "result" in result

    @pytest.mark.asyncio
    async def test_get_session_info(self, client: SessionClient) -> None:
        """Client can retrieve session info after a turn."""
        # Send a turn first
        await client.send_turn(
            session_id="e2e-info-session",
            prompt="Test prompt",
            provider_name="mock",
        )
        info = await client.get_session_info("e2e-info-session")
        assert info["status"] == "active"
        assert info["turn_count"] >= 1

    @pytest.mark.asyncio
    async def test_stream_turn(self, client: SessionClient) -> None:
        """Client can stream a turn via SSE and receives a complete event."""
        events: list[dict[str, Any]] = []
        async for sse_event in client.stream_turn(
            session_id="e2e-stream-session",
            prompt="Hello!",
            provider_name="mock",
        ):
            events.append({"event": sse_event.event, "data": sse_event.data})

        # Should have at least one event and end with complete or error
        assert len(events) > 0
        last_event = events[-1]
        assert last_event["event"] in ("complete", "error")

    @pytest.mark.asyncio
    async def test_clear_session(self, client: SessionClient) -> None:
        """Client can clear a session."""
        result = await client.clear_session("e2e-clear-session")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_tools_after_turn(self, client: SessionClient) -> None:
        """Client can list tools after a turn populates the routing table."""
        await client.send_turn(
            session_id="e2e-tools-session",
            prompt="List tools",
            provider_name="mock",
        )
        tools = await client.get_tools("e2e-tools-session")
        # Should have at least some tools from the default services
        assert isinstance(tools, list)


@pytest.mark.slow
class TestE2ECLICommand:
    """End-to-end tests for the CLI Click commands."""

    def test_cli_version(self) -> None:
        """CLI version command works."""
        result = subprocess.run(
            ["uv", "run", "amplifier", "version"],
            capture_output=True,
            text=True,
            cwd="amplifier-ipc-cli",
            timeout=10,
        )
        assert result.returncode == 0
        assert "0.1.0" in result.stdout

    def test_cli_single_turn_json(self) -> None:
        """CLI single-turn with --output-format json returns valid JSON."""
        result = subprocess.run(
            [
                "uv", "run", "amplifier", "run",
                "--url", "http://localhost:8080",
                "--provider", "mock",
                "-o", "json",
                "Hello",
            ],
            capture_output=True,
            text=True,
            cwd="amplifier-ipc-cli",
            timeout=30,
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout.strip())
            assert payload["status"] == "success"
            assert "response" in payload
```

**Step 2: Run unit tests (e2e tests will be skipped without Docker)**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/ -v -m "not slow"
```
Expected: All unit tests PASS; e2e tests SKIPPED.

**Step 3: Run full e2e tests with Docker (if services are running)**

Run:
```bash
# Start services first
cd /data/labs/amplifier-ipc && docker compose up -d
sleep 10

# Run e2e tests
cd amplifier-ipc-cli && uv run pytest tests/test_e2e.py -v -m slow
```
Expected: All e2e tests PASS.

**Step 4: Run the full CLI test suite one final time**

Run:
```bash
cd amplifier-ipc-cli && uv run pytest tests/ -v
```
Expected: All non-slow tests PASS.

**Step 5: Commit**

```bash
git add amplifier-ipc-cli/ && git commit -m "test(cli): add end-to-end integration tests for CLI against session-service"
```
