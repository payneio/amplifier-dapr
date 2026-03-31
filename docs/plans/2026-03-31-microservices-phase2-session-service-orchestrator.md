# Phase 2: Session Service + Orchestrator Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Build the core session flow so a prompt can traverse the full Dapr microservices stack end-to-end: CLI prompt → Session Service → Orchestrator → Mock Provider → Tool dispatch → Context Manager → response.

**Architecture:** The Session Service is a thin gateway that receives prompts, resolves agent definitions, discovers services via `/describe`, builds a routing table, assembles system prompts, and invokes the Orchestrator. The Orchestrator drives the agent loop by making forward Dapr service invocation calls to providers, tools, hooks, and the context manager using the routing table. The Context Manager is a separate composable service (`svc-context`). A mock provider enables integration testing without API keys.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, Dapr (service invocation + state store + pub/sub), Docker Compose, Redis, uv, pytest, httpx

**Design Document:** `docs/design/amplifier-ipc-microservices-design.md`

---

## Codebase Context

This is a Python mono-repo at `/data/labs/amplifier-ipc/` using uv for package management. Phase 1 is complete and committed.

### Key conventions (from Phase 1):

- **Build system:** hatchling with `src/` layout (`[tool.hatch.build.targets.wheel] packages = ["src/package_name"]`)
- **Python:** `requires-python = ">=3.11"` in pyproject.toml
- **Dependencies:** pydantic>=2.0, fastapi>=0.115, httpx>=0.28, uvicorn[standard]>=0.34
- **Tests:** pytest with `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `pythonpath = ["src"]`
- **Dev deps:** Inside `[dependency-groups]` dev section (not `[project.optional-dependencies]`)
- **Local deps:** `[tool.uv.sources]` with `path = "..."` for cross-package references
- **Service pattern:** FastAPI app created via `create_app(ServiceConfig(...))` from the SDK, which auto-wires `/healthz`, `/describe`, `/content/{path}`
- **Tool endpoint pattern:** `@app.post("/tools/{name}/execute")` receives `ToolRequest`, returns `ToolResult.model_dump()`
- **Module-level app:** Each service has `app = create_xxx_app()` at module level for uvicorn
- **Dockerfile pattern:** `FROM amplifier-service-base`, copy service dir, `uv pip install --system .`, CMD uvicorn
- **Docker Compose pattern:** service + sidecar pairs with `network_mode: "service:{svc}"`, Dapr sidecar on port 3500
- **Dapr URL pattern:** `http://localhost:{DAPR_HTTP_PORT}/v1.0/invoke/{app-id}/method/{endpoint}`
- **All `__init__.py` files must exist** in test directories and src directories
- **Test classes** use `class TestXxx:` grouping with `pytest.fixture` for setup
- **pyright** config: `pythonVersion = "3.11"`, `extraPaths = ["src"]`, `venvPath = "."`, `venv = ".venv"`

### Existing Phase 1 files:

```
amplifier-service-sdk/
  pyproject.toml
  src/amplifier_service_sdk/
    __init__.py         # Re-exports all model classes
    models.py           # ToolCapability, ToolRequest, ToolResult, HookEvent, HookResult,
                        # ProviderRequest, ProviderResponse, DescribeResponse,
                        # HealthResponse, ContentFile
    service.py          # ServiceConfig, create_app() -- auto-wires /healthz, /describe, /content
    content.py          # ContentManager -- scans + serves content files
    cli.py              # amplifier-serve CLI
  tests/
    test_models.py, test_service.py, test_content.py, test_cli.py

services/svc-machine/   # Machine abstraction service (exec + file ops)
services/svc-bash/      # Bash tool service calling svc-machine via Dapr SI

docker/
  base/Dockerfile                # amplifier-service-base image
  dapr/components/
    statestore.yaml              # Redis state store (name: statestore)
    pubsub.yaml                  # Redis pub/sub (name: pubsub)
  dapr/config.yaml               # Dapr config

docker-compose.yaml              # redis + svc-machine + svc-bash + Dapr sidecars
```

### Reference source (existing IPC -- read-only, port from):

- `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` -- The 802-line agent loop to port
- `services/amplifier-foundation/src/amplifier_foundation/context_managers/simple.py` -- The 1056-line context manager to port
- `src/amplifier_ipc/protocol/models.py` -- Message, ToolCall, ChatRequest, ChatResponse, HookAction, HookResult, Usage models
- `src/amplifier_ipc/host/host.py` -- Session lifecycle to extract from
- `src/amplifier_ipc/host/service_index.py` -- Routing table building pattern
- `src/amplifier_ipc/host/content.py` -- Content assembly pattern
- `src/amplifier_ipc/host/persistence.py` -- Session persistence pattern
- `definitions/foundation-agent.yaml` -- Agent definition format

---

## Task Overview

This plan is split into **Phase 2a** (Tasks 1-10) and **Phase 2b** (Tasks 11-16) to keep each execution segment manageable.

### Phase 2a: SDK Models + Core Services

| # | Task | Creates/Modifies |
|---|---|---|
| 1 | Extend SDK models | `amplifier-service-sdk/src/amplifier_service_sdk/models.py` |
| 2 | svc-context: package scaffold | `services/svc-context/` package + ContextManager class |
| 3 | svc-context: FastAPI app + endpoints | `services/svc-context/src/svc_context/app.py` |
| 4 | svc-mock-provider: package scaffold + provider | `services/svc-mock-provider/` package |
| 5 | svc-mock-provider: FastAPI app | `services/svc-mock-provider/src/svc_mock_provider/app.py` |
| 6 | Orchestrator: Dapr client wrapper | `services/svc-orchestrator/src/svc_orchestrator/dapr_client.py` |
| 7 | Orchestrator: package scaffold + app | `services/svc-orchestrator/` package |
| 8 | Orchestrator: core agent loop | `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py` |
| 9 | Orchestrator: tool dispatch | Tool execution within orchestrator loop |
| 10 | Orchestrator: provider dispatch with retry | Provider call with exponential backoff |

### Phase 2b: Session Service + Integration

| # | Task | Creates/Modifies |
|---|---|---|
| 11 | Session Service: package scaffold + app | `services/session-service/` package |
| 12 | Session Service: discovery module | `services/session-service/src/session_service/discovery.py` |
| 13 | Session Service: content assembly | `services/session-service/src/session_service/content.py` |
| 14 | Session Service: state management | `services/session-service/src/session_service/state.py` |
| 15 | Docker Compose update | `docker-compose.yaml` with all new services |
| 16 | Integration test | End-to-end test proving full stack flow |

---

## Phase 2a: SDK Models + Core Services

### Task 1: Extend SDK Models

**Files:**
- Modify: `amplifier-service-sdk/src/amplifier_service_sdk/models.py`
- Modify: `amplifier-service-sdk/src/amplifier_service_sdk/__init__.py`
- Modify: `amplifier-service-sdk/tests/test_models.py`

**Step 1: Write the failing tests**

Add the following test classes to `amplifier-service-sdk/tests/test_models.py`:

```python
# --- Add these imports at the top alongside existing ones ---
from amplifier_service_sdk import (
    # ... existing imports stay ...
    ChatRequest,
    ChatResponse,
    HookAction,
    Message,
    RoutingTable,
    StreamEvent,
    TokenUsage,
    ToolCall,
)


class TestMessage:
    def test_basic_user_message(self):
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_calls is None
        assert msg.tool_call_id is None
        assert msg.name is None
        assert msg.metadata is None

    def test_assistant_with_tool_calls(self):
        tc = ToolCall(id="tc_1", name="bash", arguments={"command": "ls"})
        msg = Message(role="assistant", content="", tool_calls=[tc])
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "bash"

    def test_tool_result_message(self):
        msg = Message(role="tool", content="output", tool_call_id="tc_1", name="bash")
        assert msg.role == "tool"
        assert msg.tool_call_id == "tc_1"
        assert msg.name == "bash"

    def test_metadata(self):
        msg = Message(role="user", content="hi", metadata={"timestamp": "2024-01-01"})
        assert msg.metadata["timestamp"] == "2024-01-01"

    def test_json_roundtrip(self):
        tc = ToolCall(id="tc_1", name="bash", arguments={"command": "ls"})
        original = Message(role="assistant", content="text", tool_calls=[tc])
        dumped = json.loads(original.model_dump_json())
        recovered = Message.model_validate(dumped)
        assert recovered.role == "assistant"
        assert recovered.tool_calls[0].name == "bash"


class TestToolCall:
    def test_basic(self):
        tc = ToolCall(id="tc_1", name="bash", arguments={"command": "ls"})
        assert tc.id == "tc_1"
        assert tc.name == "bash"
        assert tc.arguments == {"command": "ls"}

    def test_empty_arguments_default(self):
        tc = ToolCall(id="tc_1", name="bash")
        assert tc.arguments == {}


class TestTokenUsage:
    def test_basic(self):
        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    def test_defaults(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0


class TestChatRequest:
    def test_basic(self):
        msg = Message(role="user", content="Hello")
        req = ChatRequest(messages=[msg])
        assert len(req.messages) == 1
        assert req.tools is None
        assert req.system is None

    def test_with_tools_and_system(self):
        msg = Message(role="user", content="Hello")
        tool = ToolCapability(name="bash", description="Run shell commands")
        req = ChatRequest(
            messages=[msg],
            tools=[tool],
            system="You are helpful",
            max_output_tokens=4096,
            reasoning_effort="high",
        )
        assert req.tools[0].name == "bash"
        assert req.system == "You are helpful"
        assert req.max_output_tokens == 4096
        assert req.reasoning_effort == "high"


class TestChatResponse:
    def test_text_response(self):
        resp = ChatResponse(
            content="Hello there",
            stop_reason="end_turn",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )
        assert resp.content == "Hello there"
        assert resp.stop_reason == "end_turn"
        assert resp.usage.input_tokens == 10

    def test_tool_call_response(self):
        tc = ToolCall(id="tc_1", name="bash", arguments={"command": "ls"})
        resp = ChatResponse(content="", tool_calls=[tc], stop_reason="tool_use")
        assert len(resp.tool_calls) == 1
        assert resp.stop_reason == "tool_use"

    def test_no_tool_calls_default(self):
        resp = ChatResponse(content="hi")
        assert resp.tool_calls is None


class TestHookAction:
    def test_enum_values(self):
        assert HookAction.CONTINUE == "CONTINUE"
        assert HookAction.DENY == "DENY"
        assert HookAction.MODIFY == "MODIFY"
        assert HookAction.INJECT_CONTEXT == "INJECT_CONTEXT"


class TestRoutingTable:
    def test_basic(self):
        rt = RoutingTable(
            tools={"bash": "svc-bash", "grep": "svc-machine"},
            providers={"mock": "svc-mock-provider"},
            hooks={},
            context="svc-context",
        )
        assert rt.tools["bash"] == "svc-bash"
        assert rt.providers["mock"] == "svc-mock-provider"
        assert rt.context == "svc-context"

    def test_defaults(self):
        rt = RoutingTable(context="svc-context")
        assert rt.tools == {}
        assert rt.providers == {}
        assert rt.hooks == {}

    def test_json_roundtrip(self):
        rt = RoutingTable(
            tools={"bash": "svc-bash"},
            providers={"mock": "svc-mock-provider"},
            hooks={"tool:pre": ["svc-hooks"]},
            context="svc-context",
        )
        dumped = json.loads(rt.model_dump_json())
        recovered = RoutingTable.model_validate(dumped)
        assert recovered.tools["bash"] == "svc-bash"
        assert recovered.hooks["tool:pre"] == ["svc-hooks"]


class TestStreamEvent:
    def test_basic(self):
        evt = StreamEvent(
            session_id="sess_123",
            event_type="stream.token",
            data={"text": "hello"},
        )
        assert evt.session_id == "sess_123"
        assert evt.event_type == "stream.token"
        assert evt.data["text"] == "hello"
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/amplifier-service-sdk && uv run pytest tests/test_models.py -v -x 2>&1 | head -40
```

Expected: FAIL with `ImportError` -- `Message`, `ToolCall`, `ChatRequest`, etc. don't exist yet.

**Step 3: Implement the new models**

Add the following models to `amplifier-service-sdk/src/amplifier_service_sdk/models.py`, after the existing `ContentFile` class at the bottom of the file:

```python
# ---------------------------------------------------------------------------
# Phase 2 models -- orchestrator / session communication
# ---------------------------------------------------------------------------


class HookAction(str, Enum):
    """Actions a hook can take in response to an event."""

    CONTINUE = "CONTINUE"
    DENY = "DENY"
    MODIFY = "MODIFY"
    INJECT_CONTEXT = "INJECT_CONTEXT"


class ToolCall(BaseModel):
    """A tool call from an LLM response."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    """Token usage from a provider response."""

    input_tokens: int = 0
    output_tokens: int = 0


class Message(BaseModel):
    """A chat message (user, assistant, tool, or system)."""

    role: str
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None


class ChatRequest(BaseModel):
    """Request payload for a chat completion."""

    messages: list[Message]
    tools: list[ToolCapability] | None = None
    system: str | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    temperature: float | None = None


class ChatResponse(BaseModel):
    """Response from a chat completion."""

    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    usage: TokenUsage | None = None
    stop_reason: str | None = None


class RoutingTable(BaseModel):
    """Maps component names to Dapr app-ids for service invocation."""

    tools: dict[str, str] = Field(default_factory=dict)
    providers: dict[str, str] = Field(default_factory=dict)
    hooks: dict[str, list[str]] = Field(default_factory=dict)
    context: str


class StreamEvent(BaseModel):
    """An event published to pub/sub for streaming to the CLI."""

    session_id: str
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)
```

Also add the `Enum` import at the top of `models.py`:

```python
from enum import Enum
```

**Step 4: Update `__init__.py` exports**

Add the new model names to `amplifier-service-sdk/src/amplifier_service_sdk/__init__.py`:

```python
"""Amplifier Service SDK -- Python package for building Amplifier-compatible microservices."""

from amplifier_service_sdk.models import (
    ChatRequest,
    ChatResponse,
    ContentFile,
    DescribeResponse,
    HealthResponse,
    HookAction,
    HookEvent,
    HookResult,
    Message,
    ProviderRequest,
    ProviderResponse,
    RoutingTable,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolCapability,
    ToolRequest,
    ToolResult,
)

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ContentFile",
    "DescribeResponse",
    "HealthResponse",
    "HookAction",
    "HookEvent",
    "HookResult",
    "Message",
    "ProviderRequest",
    "ProviderResponse",
    "RoutingTable",
    "StreamEvent",
    "TokenUsage",
    "ToolCall",
    "ToolCapability",
    "ToolRequest",
    "ToolResult",
]
```

**Step 5: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/amplifier-service-sdk && uv run pytest tests/test_models.py -v
```

Expected: ALL PASS

**Step 6: Verify existing SDK tests still pass**

```bash
cd /data/labs/amplifier-ipc/amplifier-service-sdk && uv run pytest tests/ -v
```

Expected: ALL PASS (no regressions)

**Step 7: Commit**

```bash
cd /data/labs/amplifier-ipc && git add amplifier-service-sdk/ && git commit -m "feat(sdk): add Phase 2 models -- Message, ChatRequest, ChatResponse, RoutingTable, StreamEvent"
```

---

### Task 2: svc-context -- Package Scaffold + Context Manager

**Files:**
- Create: `services/svc-context/pyproject.toml`
- Create: `services/svc-context/describe.yaml`
- Create: `services/svc-context/src/svc_context/__init__.py`
- Create: `services/svc-context/src/svc_context/context_manager.py`
- Create: `services/svc-context/tests/__init__.py`
- Create: `services/svc-context/tests/test_context_manager.py`

**Step 1: Create package scaffold**

Create `services/svc-context/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-context"
version = "0.1.0"
description = "Amplifier context manager service -- manages conversation messages with compaction"
requires-python = ">=3.11"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/svc_context"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]
venvPath = "."
venv = ".venv"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Create `services/svc-context/describe.yaml`:

```yaml
name: svc-context
version: '0.1.0'
```

Create `services/svc-context/src/svc_context/__init__.py`:

```python
"""Amplifier context manager service."""
```

Create `services/svc-context/tests/__init__.py`:

```python
```

**Step 2: Write the failing tests**

Create `services/svc-context/tests/test_context_manager.py`:

```python
"""Tests for the SimpleContextManager."""

from __future__ import annotations

import pytest

from amplifier_service_sdk import Message
from svc_context.context_manager import SimpleContextManager


class TestSimpleContextManager:
    @pytest.fixture
    def ctx(self) -> SimpleContextManager:
        """Create a fresh context manager."""
        return SimpleContextManager()

    @pytest.mark.asyncio
    async def test_add_and_get_messages(self, ctx: SimpleContextManager) -> None:
        """Adding messages then getting them returns them in order."""
        await ctx.add_message(Message(role="system", content="You are helpful"))
        await ctx.add_message(Message(role="user", content="Hello"))
        messages = await ctx.get_messages()
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[1].role == "user"

    @pytest.mark.asyncio
    async def test_clear(self, ctx: SimpleContextManager) -> None:
        """Clearing removes all messages."""
        await ctx.add_message(Message(role="user", content="Hello"))
        await ctx.clear()
        messages = await ctx.get_messages()
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_set_messages_bulk(self, ctx: SimpleContextManager) -> None:
        """set_messages replaces the message list."""
        await ctx.add_message(Message(role="user", content="old"))
        new_msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="new"),
        ]
        await ctx.set_messages(new_msgs)
        messages = await ctx.get_messages()
        assert len(messages) == 2
        assert messages[1].content == "new"

    @pytest.mark.asyncio
    async def test_timestamps_added(self, ctx: SimpleContextManager) -> None:
        """Messages get timestamp metadata when added."""
        await ctx.add_message(Message(role="user", content="Hello"))
        messages = await ctx.get_messages()
        assert messages[0].metadata is not None
        assert "timestamp" in messages[0].metadata

    @pytest.mark.asyncio
    async def test_existing_metadata_preserved(self, ctx: SimpleContextManager) -> None:
        """Existing metadata keys are preserved when timestamp is added."""
        await ctx.add_message(
            Message(role="user", content="Hello", metadata={"source": "test"})
        )
        messages = await ctx.get_messages()
        assert messages[0].metadata["source"] == "test"
        assert "timestamp" in messages[0].metadata

    @pytest.mark.asyncio
    async def test_compaction_under_budget_is_noop(
        self, ctx: SimpleContextManager
    ) -> None:
        """When messages are under budget, get_messages returns all of them."""
        ctx.max_tokens = 200_000
        await ctx.add_message(Message(role="system", content="sys"))
        await ctx.add_message(Message(role="user", content="short message"))
        messages = await ctx.get_messages()
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_compaction_triggers_when_over_threshold(
        self, ctx: SimpleContextManager
    ) -> None:
        """When token estimate exceeds threshold, compaction reduces message count."""
        ctx.max_tokens = 100  # Very small budget
        ctx.compact_threshold = 0.5
        ctx.target_usage = 0.3
        # Add enough messages to exceed the budget
        await ctx.add_message(Message(role="system", content="system"))
        await ctx.add_message(Message(role="user", content="u1"))
        await ctx.add_message(
            Message(role="assistant", content="a1", tool_calls=None)
        )
        # Add tool messages with large content to trigger compaction
        for i in range(10):
            await ctx.add_message(
                Message(role="user", content=f"question {i}" * 20)
            )
            await ctx.add_message(
                Message(role="assistant", content=f"answer {i}" * 20)
            )
        compacted = await ctx.get_messages()
        # Compacted view should have fewer messages than original
        assert len(compacted) < len(ctx.messages)

    @pytest.mark.asyncio
    async def test_get_messages_does_not_modify_original(
        self, ctx: SimpleContextManager
    ) -> None:
        """Ephemeral compaction does not modify the source messages list."""
        ctx.max_tokens = 50
        ctx.compact_threshold = 0.5
        ctx.target_usage = 0.3
        for i in range(10):
            await ctx.add_message(
                Message(role="user", content=f"message {i}" * 20)
            )
            await ctx.add_message(
                Message(role="assistant", content=f"reply {i}" * 20)
            )
        original_count = len(ctx.messages)
        _ = await ctx.get_messages()
        # Original messages list is untouched
        assert len(ctx.messages) == original_count
```

**Step 3: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/svc-context && uv sync && uv run pytest tests/test_context_manager.py -v -x 2>&1 | head -30
```

Expected: FAIL with `ModuleNotFoundError: No module named 'svc_context.context_manager'`

**Step 4: Implement the context manager**

Create `services/svc-context/src/svc_context/context_manager.py`:

```python
"""SimpleContextManager -- in-memory context manager with ephemeral compaction.

Ported from amplifier_foundation.context_managers.simple. Key principle:
self.messages is the source of truth and is NEVER modified by compaction.
Compaction only returns a compacted VIEW for the current LLM request.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from amplifier_service_sdk import Message

logger = logging.getLogger(__name__)


class SimpleContextManager:
    """In-memory context manager with ephemeral progressive compaction.

    Compaction Strategy (Progressive):
    - Level 1: Truncate oldest 25% of tool results
    - Level 2: Truncate next 25% of tool results (now 50%)
    - Level 3: Remove oldest messages (use configured protected_recent)
    - Level 4+: Progressively more aggressive truncation and removal

    System messages are NEVER compacted.
    """

    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.max_tokens: int = 200_000
        self.compact_threshold: float = 0.85
        self.target_usage: float = 0.60
        self.protected_recent: float = 0.30
        self.protected_tool_results: int = 5
        self.truncate_chars: int = 8000

    async def add_message(self, message: Message) -> None:
        """Add a message to the context.

        Automatically adds a timestamp to metadata if not present.
        """
        existing_meta = message.metadata or {}
        if "timestamp" not in existing_meta:
            message = message.model_copy(
                update={
                    "metadata": {
                        **existing_meta,
                        "timestamp": datetime.now(UTC).isoformat(
                            timespec="milliseconds"
                        ),
                    },
                }
            )
        self.messages.append(message)

    async def get_messages(
        self, context_window: int | None = None, max_output_tokens: int | None = None
    ) -> list[Message]:
        """Get messages ready for an LLM request.

        Applies ephemeral compaction if needed -- returns a NEW list without
        modifying self.messages.
        """
        budget = self._calculate_budget(context_window, max_output_tokens)
        working_messages = list(self.messages)
        token_count = self._estimate_tokens(working_messages)

        if self._should_compact(token_count, budget):
            return self._compact_ephemeral(budget, working_messages)

        return working_messages

    async def set_messages(self, messages: list[Message]) -> None:
        """Set messages from a saved transcript (for session resume)."""
        self.messages = list(messages)
        logger.info("Restored %d messages to context", len(messages))

    async def clear(self) -> None:
        """Clear all messages."""
        self.messages = []
        logger.info("Context cleared")

    def _should_compact(self, token_count: int, budget: int) -> bool:
        """Check if compaction is needed."""
        if budget <= 0:
            return False
        usage = token_count / budget
        return usage >= self.compact_threshold

    def _compact_ephemeral(
        self, budget: int, source_messages: list[Message]
    ) -> list[Message]:
        """Compact messages ephemerally using progressive strategy.

        Returns a NEW list -- source_messages are NEVER modified.
        System messages are NEVER compacted.
        """
        target_tokens = int(budget * self.target_usage)

        # Extract system messages -- they are NEVER compacted
        system_messages = [m.model_copy() for m in source_messages if m.role == "system"]
        non_system = [m for m in source_messages if m.role != "system"]

        working = [m.model_copy() for m in non_system]
        current_tokens = self._estimate_tokens(source_messages)

        # Tool result indices for wave-based truncation
        tool_indices = [i for i, m in enumerate(working) if m.role == "tool"]
        total_tools = len(tool_indices)
        protected_set = set(tool_indices[-self.protected_tool_results :])

        wave1_end = int(total_tools * 0.25)
        wave2_end = int(total_tools * 0.50)

        # Level 1: Truncate oldest 25% of tool results
        self._truncate_tool_wave(
            working, tool_indices[:wave1_end], protected_set
        )
        current_tokens = self._estimate_tokens(system_messages + working)
        if current_tokens <= target_tokens:
            return system_messages + working

        # Level 2: Truncate next 25%
        self._truncate_tool_wave(
            working, tool_indices[wave1_end:wave2_end], protected_set
        )
        current_tokens = self._estimate_tokens(system_messages + working)
        if current_tokens <= target_tokens:
            return system_messages + working

        # Level 3: Remove oldest messages (protect recent %)
        protected_count = max(2, int(len(working) * self.protected_recent))
        if len(working) > protected_count:
            working = working[-protected_count:]
        current_tokens = self._estimate_tokens(system_messages + working)
        if current_tokens <= target_tokens:
            return system_messages + working

        # Level 4: Truncate remaining tool results
        remaining_tools = [i for i, m in enumerate(working) if m.role == "tool"]
        protected_remaining = set(remaining_tools[-self.protected_tool_results :])
        self._truncate_tool_wave(working, remaining_tools, protected_remaining)
        current_tokens = self._estimate_tokens(system_messages + working)
        if current_tokens <= target_tokens:
            return system_messages + working

        # Level 5: Keep only last few messages
        if len(working) > 4:
            working = working[-4:]

        return system_messages + working

    def _truncate_tool_wave(
        self,
        messages: list[Message],
        indices: list[int],
        protected: set[int],
    ) -> None:
        """Truncate tool result messages at given indices (in place)."""
        for idx in indices:
            if idx in protected or idx >= len(messages):
                continue
            msg = messages[idx]
            content = msg.content or ""
            if isinstance(content, str) and len(content) > self.truncate_chars:
                original_tokens = len(content) // 4
                messages[idx] = msg.model_copy(
                    update={
                        "content": (
                            f"[truncated: ~{original_tokens:,} tokens] "
                            f"{content[: self.truncate_chars]}..."
                        )
                    }
                )

    def _calculate_budget(
        self,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> int:
        """Calculate effective token budget."""
        safety_margin = 4096
        if context_window and max_output_tokens:
            reserved = int(max_output_tokens * 0.25)
            return context_window - reserved - safety_margin
        return self.max_tokens

    def _estimate_tokens(self, messages: list[Message]) -> int:
        """Rough token estimation (chars / 4)."""
        return sum(len(str(m)) // 4 for m in messages)
```

**Step 5: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/svc-context && uv run pytest tests/test_context_manager.py -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/svc-context/ && git commit -m "feat(svc-context): add context manager service with ephemeral compaction"
```

---

### Task 3: svc-context -- FastAPI App + Endpoints

**Files:**
- Create: `services/svc-context/src/svc_context/app.py`
- Create: `services/svc-context/Dockerfile`
- Create: `services/svc-context/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-context/tests/test_app.py`:

```python
"""Tests for the svc-context FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_context.app import create_context_app


class TestModuleLevelApp:
    def test_module_exposes_app(self) -> None:
        from svc_context import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)


class TestContextApp:
    @pytest.fixture
    def client(self) -> TestClient:
        app = create_context_app()
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe(self, client: TestClient) -> None:
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-context"

    def test_add_and_get_messages(self, client: TestClient) -> None:
        # Add a message
        resp = client.post(
            "/context/messages",
            json={"role": "user", "content": "Hello"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Get messages back
        resp = client.get("/context/messages")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"

    def test_clear_messages(self, client: TestClient) -> None:
        client.post("/context/messages", json={"role": "user", "content": "Hi"})
        resp = client.post("/context/clear")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        resp = client.get("/context/messages")
        assert len(resp.json()["messages"]) == 0

    def test_bulk_set_messages(self, client: TestClient) -> None:
        client.post("/context/messages", json={"role": "user", "content": "old"})

        resp = client.put(
            "/context/messages/bulk",
            json={
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "new"},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        resp = client.get("/context/messages")
        messages = resp.json()["messages"]
        assert len(messages) == 2
        assert messages[1]["content"] == "new"

    def test_get_messages_with_query_params(self, client: TestClient) -> None:
        client.post(
            "/context/messages", json={"role": "user", "content": "Hello"}
        )
        resp = client.get(
            "/context/messages",
            params={"context_window": 200000, "max_output_tokens": 8192},
        )
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 1
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/svc-context && uv run pytest tests/test_app.py -v -x 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError: No module named 'svc_context.app'`

**Step 3: Implement the app**

Create `services/svc-context/src/svc_context/app.py`:

```python
"""FastAPI app for svc-context -- the context manager service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from amplifier_service_sdk.models import Message
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_context.context_manager import SimpleContextManager


class BulkMessagesRequest(BaseModel):
    """Request body for PUT /context/messages/bulk."""

    messages: list[Message]


def create_context_app() -> FastAPI:
    """Create the svc-context FastAPI application."""
    config = ServiceConfig(name="svc-context")
    app = create_app(config)

    # One context manager instance per app (stateful for session duration)
    ctx = SimpleContextManager()

    @app.post("/context/messages")
    async def add_message(message: Message) -> dict[str, Any]:
        """Add a message to the context."""
        await ctx.add_message(message)
        return {"success": True}

    @app.get("/context/messages")
    async def get_messages(
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Get messages, with optional compaction based on token budget."""
        messages = await ctx.get_messages(
            context_window=context_window,
            max_output_tokens=max_output_tokens,
        )
        return {"messages": [m.model_dump() for m in messages]}

    @app.put("/context/messages/bulk")
    async def set_messages_bulk(request: BulkMessagesRequest) -> dict[str, Any]:
        """Set/restore messages (for session resume)."""
        await ctx.set_messages(request.messages)
        return {"success": True}

    @app.post("/context/clear")
    async def clear_messages() -> dict[str, Any]:
        """Clear all messages."""
        await ctx.clear()
        return {"success": True}

    return app


app = create_context_app()
```

Create `services/svc-context/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-context/ /build/svc-context/
RUN cd /build/svc-context && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_context.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 4: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/svc-context && uv run pytest tests/ -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/svc-context/ && git commit -m "feat(svc-context): add FastAPI app with /context/* endpoints + Dockerfile"
```

---

### Task 4: svc-mock-provider -- Package Scaffold + Provider

**Files:**
- Create: `services/svc-mock-provider/pyproject.toml`
- Create: `services/svc-mock-provider/describe.yaml`
- Create: `services/svc-mock-provider/src/svc_mock_provider/__init__.py`
- Create: `services/svc-mock-provider/src/svc_mock_provider/provider.py`
- Create: `services/svc-mock-provider/tests/__init__.py`
- Create: `services/svc-mock-provider/tests/test_provider.py`

**Step 1: Create package scaffold**

Create `services/svc-mock-provider/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-mock-provider"
version = "0.1.0"
description = "Amplifier mock LLM provider service -- canned responses for testing"
requires-python = ">=3.11"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/svc_mock_provider"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]
venvPath = "."
venv = ".venv"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Create `services/svc-mock-provider/describe.yaml`:

```yaml
name: svc-mock-provider
version: '0.1.0'
providers:
  - name: mock
    description: Mock LLM provider for testing
```

Create `services/svc-mock-provider/src/svc_mock_provider/__init__.py`:

```python
"""Amplifier mock LLM provider service."""
```

Create `services/svc-mock-provider/tests/__init__.py`:

```python
```

**Step 2: Write the failing tests**

Create `services/svc-mock-provider/tests/test_provider.py`:

```python
"""Tests for MockProvider."""

from __future__ import annotations

import pytest

from amplifier_service_sdk import ChatRequest, ChatResponse, Message, ToolCall, ToolCapability
from svc_mock_provider.provider import MockProvider


class TestMockProvider:
    @pytest.fixture
    def provider(self) -> MockProvider:
        return MockProvider()

    @pytest.mark.asyncio
    async def test_text_response(self, provider: MockProvider) -> None:
        """Provider returns text when no tools are mentioned."""
        request = ChatRequest(
            messages=[Message(role="user", content="Hello world")]
        )
        response = await provider.complete(request)
        assert isinstance(response, ChatResponse)
        assert response.content is not None
        assert "Hello world" in response.content
        assert response.tool_calls is None
        assert response.usage is not None
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0

    @pytest.mark.asyncio
    async def test_tool_call_response(self, provider: MockProvider) -> None:
        """Provider returns a tool_call when the message mentions a tool name."""
        bash_tool = ToolCapability(
            name="bash",
            description="Execute shell commands",
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        )
        request = ChatRequest(
            messages=[Message(role="user", content="use bash to list files")],
            tools=[bash_tool],
        )
        response = await provider.complete(request)
        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "bash"
        assert response.stop_reason == "tool_use"

    @pytest.mark.asyncio
    async def test_no_tool_call_when_no_tools(self, provider: MockProvider) -> None:
        """Provider returns text even if message mentions a tool name but no tools are provided."""
        request = ChatRequest(
            messages=[Message(role="user", content="use bash to list files")],
            tools=None,
        )
        response = await provider.complete(request)
        assert response.tool_calls is None

    @pytest.mark.asyncio
    async def test_text_after_tool_result(self, provider: MockProvider) -> None:
        """After a tool result, provider returns text (not another tool call)."""
        request = ChatRequest(
            messages=[
                Message(role="user", content="use bash to list files"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="tc_1", name="bash", arguments={"command": "ls"})],
                ),
                Message(role="tool", content="file1.txt\nfile2.txt", tool_call_id="tc_1", name="bash"),
            ],
        )
        response = await provider.complete(request)
        assert response.tool_calls is None
        assert response.content is not None
        assert response.stop_reason == "end_turn"
```

**Step 3: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/svc-mock-provider && uv sync && uv run pytest tests/test_provider.py -v -x 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError: No module named 'svc_mock_provider.provider'`

**Step 4: Implement the provider**

Create `services/svc-mock-provider/src/svc_mock_provider/provider.py`:

```python
"""MockProvider -- returns canned responses for testing."""

from __future__ import annotations

import uuid
from typing import Any

from amplifier_service_sdk import (
    ChatRequest,
    ChatResponse,
    TokenUsage,
    ToolCall,
)


class MockProvider:
    """Mock LLM provider that returns deterministic responses.

    Behavior:
    - If the last message is a tool result, return text summarizing it (end_turn).
    - If the last user message mentions a tool name from the tools list,
      return a tool_call for that tool.
    - Otherwise, return a canned text response.
    """

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Process a chat request and return a mock response."""
        last_message = request.messages[-1] if request.messages else None
        if last_message is None:
            return self._text_response("Empty request")

        # If the last message is a tool result, return text (end the loop)
        if last_message.role == "tool":
            tool_output = last_message.content or ""
            return self._text_response(
                f"The tool returned: {str(tool_output)[:200]}"
            )

        # Check if the last user/assistant message mentions a tool name
        if request.tools and last_message.role == "user":
            content_str = str(last_message.content or "").lower()
            for tool in request.tools:
                if tool.name.lower() in content_str:
                    return self._tool_call_response(tool.name, tool.input_schema)

        # Default: return text
        content_str = str(last_message.content or "")
        return self._text_response(f"Mock response to: {content_str[:200]}")

    def _text_response(self, text: str) -> ChatResponse:
        return ChatResponse(
            content=text,
            tool_calls=None,
            usage=TokenUsage(input_tokens=50, output_tokens=len(text) // 4 + 1),
            stop_reason="end_turn",
        )

    def _tool_call_response(
        self, tool_name: str, input_schema: dict[str, Any]
    ) -> ChatResponse:
        """Generate a tool call with sensible default arguments."""
        arguments: dict[str, Any] = {}
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])
        for prop_name in required:
            prop_info = properties.get(prop_name, {})
            prop_type = prop_info.get("type", "string")
            if prop_type == "string":
                arguments[prop_name] = f"mock_{prop_name}_value"
            elif prop_type == "integer":
                arguments[prop_name] = 1
            elif prop_type == "boolean":
                arguments[prop_name] = False
            else:
                arguments[prop_name] = f"mock_{prop_name}"

        tool_call = ToolCall(
            id=f"tc_{uuid.uuid4().hex[:8]}",
            name=tool_name,
            arguments=arguments,
        )
        return ChatResponse(
            content="",
            tool_calls=[tool_call],
            usage=TokenUsage(input_tokens=50, output_tokens=30),
            stop_reason="tool_use",
        )
```

**Step 5: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/svc-mock-provider && uv run pytest tests/test_provider.py -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/svc-mock-provider/ && git commit -m "feat(svc-mock-provider): add mock LLM provider with deterministic responses"
```

---

### Task 5: svc-mock-provider -- FastAPI App

**Files:**
- Create: `services/svc-mock-provider/src/svc_mock_provider/app.py`
- Create: `services/svc-mock-provider/Dockerfile`
- Create: `services/svc-mock-provider/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-mock-provider/tests/test_app.py`:

```python
"""Tests for the svc-mock-provider FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_mock_provider.app import create_mock_provider_app


class TestModuleLevelApp:
    def test_module_exposes_app(self) -> None:
        from svc_mock_provider import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)


class TestMockProviderApp:
    @pytest.fixture
    def client(self) -> TestClient:
        app = create_mock_provider_app()
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_lists_provider(self, client: TestClient) -> None:
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-mock-provider"
        provider_names = [p["name"] for p in data["providers"]]
        assert "mock" in provider_names

    def test_complete_returns_text(self, client: TestClient) -> None:
        response = client.post(
            "/providers/mock/complete",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["content"] is not None
        assert data["stop_reason"] == "end_turn"
        assert data["usage"]["input_tokens"] > 0

    def test_complete_returns_tool_call(self, client: TestClient) -> None:
        response = client.post(
            "/providers/mock/complete",
            json={
                "messages": [{"role": "user", "content": "use bash to run ls"}],
                "tools": [
                    {
                        "name": "bash",
                        "description": "Run commands",
                        "input_schema": {
                            "type": "object",
                            "properties": {"command": {"type": "string"}},
                            "required": ["command"],
                        },
                    }
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tool_calls"] is not None
        assert data["tool_calls"][0]["name"] == "bash"
        assert data["stop_reason"] == "tool_use"
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/svc-mock-provider && uv run pytest tests/test_app.py -v -x 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError: No module named 'svc_mock_provider.app'`

**Step 3: Implement the app**

Create `services/svc-mock-provider/src/svc_mock_provider/app.py`:

```python
"""FastAPI app for svc-mock-provider -- the mock LLM provider service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ChatRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_mock_provider.provider import MockProvider


def create_mock_provider_app() -> FastAPI:
    """Create the svc-mock-provider FastAPI application."""
    config = ServiceConfig(
        name="svc-mock-provider",
        providers=[{"name": "mock", "description": "Mock LLM provider for testing"}],
    )
    app = create_app(config)

    provider = MockProvider()

    @app.post("/providers/mock/complete")
    async def complete(request: ChatRequest) -> dict[str, Any]:
        """Run a mock chat completion."""
        response = await provider.complete(request)
        return response.model_dump()

    return app


app = create_mock_provider_app()
```

Create `services/svc-mock-provider/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-mock-provider/ /build/svc-mock-provider/
RUN cd /build/svc-mock-provider && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_mock_provider.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 4: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/svc-mock-provider && uv run pytest tests/ -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/svc-mock-provider/ && git commit -m "feat(svc-mock-provider): add FastAPI app with /providers/mock/complete + Dockerfile"
```

---

### Task 6: Orchestrator -- Dapr Client Wrapper

**Files:**
- Create: `services/svc-orchestrator/pyproject.toml`
- Create: `services/svc-orchestrator/describe.yaml`
- Create: `services/svc-orchestrator/src/svc_orchestrator/__init__.py`
- Create: `services/svc-orchestrator/src/svc_orchestrator/dapr_client.py`
- Create: `services/svc-orchestrator/tests/__init__.py`
- Create: `services/svc-orchestrator/tests/test_dapr_client.py`

**Step 1: Create package scaffold**

Create `services/svc-orchestrator/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-orchestrator"
version = "0.1.0"
description = "Amplifier orchestrator service -- drives the agent loop via Dapr service invocation"
requires-python = ">=3.11"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/svc_orchestrator"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]
venvPath = "."
venv = ".venv"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Create `services/svc-orchestrator/describe.yaml`:

```yaml
name: svc-orchestrator
version: '0.1.0'
```

Create `services/svc-orchestrator/src/svc_orchestrator/__init__.py`:

```python
"""Amplifier orchestrator service."""
```

Create `services/svc-orchestrator/tests/__init__.py`:

```python
```

**Step 2: Write the failing tests**

Create `services/svc-orchestrator/tests/test_dapr_client.py`:

```python
"""Tests for the Dapr client wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from svc_orchestrator.dapr_client import DaprClient


class TestDaprClient:
    @pytest.fixture
    def client(self) -> DaprClient:
        return DaprClient(dapr_url="http://localhost:3500")

    @pytest.mark.asyncio
    async def test_invoke_builds_correct_url(self, client: DaprClient) -> None:
        """invoke() calls the correct Dapr service invocation URL."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"result": "ok"}
        mock_response.raise_for_status = lambda: None

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            result = await client.invoke(
                app_id="svc-bash",
                method="tools/bash/execute",
                data={"name": "bash", "input": {"command": "ls"}},
            )

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "svc-bash" in call_url
        assert "tools/bash/execute" in call_url
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_invoke_get(self, client: DaprClient) -> None:
        """invoke_get() calls with GET method."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"messages": []}
        mock_response.raise_for_status = lambda: None

        with patch("httpx.AsyncClient.get", return_value=mock_response) as mock_get:
            result = await client.invoke_get(
                app_id="svc-context",
                method="context/messages",
            )

        mock_get.assert_called_once()
        assert result == {"messages": []}

    @pytest.mark.asyncio
    async def test_publish_builds_correct_url(self, client: DaprClient) -> None:
        """publish() calls the correct Dapr pub/sub URL."""
        mock_response = AsyncMock()
        mock_response.status_code = 204
        mock_response.raise_for_status = lambda: None

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            await client.publish(
                pubsub_name="pubsub",
                topic="session/123/stream",
                data={"event_type": "stream.token", "text": "hello"},
            )

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "pubsub" in call_url
        assert "session/123/stream" in call_url
```

**Step 3: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv sync && uv run pytest tests/test_dapr_client.py -v -x 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError: No module named 'svc_orchestrator.dapr_client'`

**Step 4: Implement the Dapr client**

Create `services/svc-orchestrator/src/svc_orchestrator/dapr_client.py`:

```python
"""Thin wrapper for Dapr service invocation and pub/sub."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DaprClient:
    """HTTP client for Dapr sidecar communication.

    Provides:
    - Service invocation (POST/GET) via Dapr's invoke API
    - Pub/sub publishing via Dapr's publish API
    """

    def __init__(self, dapr_url: str = "http://localhost:3500") -> None:
        self._dapr_url = dapr_url.rstrip("/")

    async def invoke(
        self,
        app_id: str,
        method: str,
        data: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Invoke a service method via Dapr service invocation (POST).

        Args:
            app_id: Target service's Dapr app-id.
            method: HTTP method path (e.g., "tools/bash/execute").
            data: JSON body to send.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response dict.
        """
        url = f"{self._dapr_url}/v1.0/invoke/{app_id}/method/{method}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=data or {})
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def invoke_get(
        self,
        app_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Invoke a service method via Dapr service invocation (GET).

        Args:
            app_id: Target service's Dapr app-id.
            method: HTTP method path (e.g., "context/messages").
            params: Query parameters.
            timeout: Request timeout in seconds.

        Returns:
            Parsed JSON response dict.
        """
        url = f"{self._dapr_url}/v1.0/invoke/{app_id}/method/{method}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def publish(
        self,
        pubsub_name: str,
        topic: str,
        data: dict[str, Any],
    ) -> None:
        """Publish a message to a Dapr pub/sub topic.

        Args:
            pubsub_name: Name of the pub/sub component (e.g., "pubsub").
            topic: Topic name (e.g., "session/123/stream").
            data: JSON payload to publish.
        """
        url = f"{self._dapr_url}/v1.0/publish/{pubsub_name}/{topic}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=data)
            response.raise_for_status()

    async def get_state(
        self,
        store_name: str,
        key: str,
    ) -> dict[str, Any] | None:
        """Get a value from the Dapr state store.

        Returns None if the key does not exist.
        """
        url = f"{self._dapr_url}/v1.0/state/{store_name}/{key}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 204 or not response.content:
                return None
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def save_state(
        self,
        store_name: str,
        key: str,
        value: Any,
    ) -> None:
        """Save a value to the Dapr state store."""
        url = f"{self._dapr_url}/v1.0/state/{store_name}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url, json=[{"key": key, "value": value}]
            )
            response.raise_for_status()
```

**Step 5: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/test_dapr_client.py -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/svc-orchestrator/ && git commit -m "feat(svc-orchestrator): add Dapr client wrapper for service invocation + pub/sub + state"
```

---

### Task 7: Orchestrator -- FastAPI App Scaffold

**Files:**
- Create: `services/svc-orchestrator/src/svc_orchestrator/app.py`
- Create: `services/svc-orchestrator/Dockerfile`
- Create: `services/svc-orchestrator/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-orchestrator/tests/test_app.py`:

```python
"""Tests for the svc-orchestrator FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_orchestrator.app import create_orchestrator_app


class TestModuleLevelApp:
    def test_module_exposes_app(self) -> None:
        from svc_orchestrator import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)


class TestOrchestratorApp:
    @pytest.fixture
    def client(self) -> TestClient:
        app = create_orchestrator_app()
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe(self, client: TestClient) -> None:
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-orchestrator"

    def test_execute_endpoint_exists(self, client: TestClient) -> None:
        """POST /orchestrator/execute returns 422 with empty body (exists but needs valid input)."""
        response = client.post("/orchestrator/execute", json={})
        # 422 = endpoint exists but validation failed (missing required fields)
        assert response.status_code == 422
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/test_app.py -v -x 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError: No module named 'svc_orchestrator.app'`

**Step 3: Implement the app scaffold**

Create `services/svc-orchestrator/src/svc_orchestrator/app.py`:

```python
"""FastAPI app for svc-orchestrator -- the agent loop service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from amplifier_service_sdk.models import Message, RoutingTable
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")


class ExecuteRequest(BaseModel):
    """Request body for POST /orchestrator/execute."""

    system_prompt: str
    messages: list[Message]
    config: dict[str, Any] = {}
    routing_table: RoutingTable
    session_id: str = ""


class ExecuteResponse(BaseModel):
    """Response from POST /orchestrator/execute."""

    result: str
    messages: list[Message]


def create_orchestrator_app(dapr_url: str | None = None) -> FastAPI:
    """Create the svc-orchestrator FastAPI application."""
    if dapr_url is None:
        dapr_url = f"http://localhost:{_DAPR_HTTP_PORT}"

    config = ServiceConfig(name="svc-orchestrator")
    app = create_app(config)

    dapr = DaprClient(dapr_url=dapr_url)

    @app.post("/orchestrator/execute")
    async def execute(request: ExecuteRequest) -> dict[str, Any]:
        """Execute the agent loop."""
        orch = Orchestrator(dapr=dapr)
        result_text, result_messages = await orch.execute(
            system_prompt=request.system_prompt,
            messages=request.messages,
            config=request.config,
            routing_table=request.routing_table,
            session_id=request.session_id,
        )
        response = ExecuteResponse(result=result_text, messages=result_messages)
        return response.model_dump()

    return app


app = create_orchestrator_app()
```

Create `services/svc-orchestrator/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-orchestrator/ /build/svc-orchestrator/
RUN cd /build/svc-orchestrator && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_orchestrator.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Now create a stub `Orchestrator` class so the import works. This stub will be replaced in Task 8.

Create `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`:

```python
"""Orchestrator -- drives the agent loop via forward Dapr service invocations.

Stub implementation -- replaced in Task 8.
"""

from __future__ import annotations

from typing import Any

from amplifier_service_sdk.models import Message, RoutingTable

from svc_orchestrator.dapr_client import DaprClient


class Orchestrator:
    """Agent loop orchestrator using Dapr service invocation."""

    def __init__(self, dapr: DaprClient) -> None:
        self._dapr = dapr

    async def execute(
        self,
        system_prompt: str,
        messages: list[Message],
        config: dict[str, Any],
        routing_table: RoutingTable,
        session_id: str = "",
    ) -> tuple[str, list[Message]]:
        """Execute the agent loop. Returns (result_text, final_messages)."""
        raise NotImplementedError("Orchestrator.execute not yet implemented")
```

**Step 4: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/test_app.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/svc-orchestrator/ && git commit -m "feat(svc-orchestrator): add FastAPI app scaffold with /orchestrator/execute endpoint"
```

---

### Task 8: Orchestrator -- Core Agent Loop

**Files:**
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`
- Create: `services/svc-orchestrator/tests/test_orchestrator.py`

**Step 1: Write the failing tests**

Create `services/svc-orchestrator/tests/test_orchestrator.py`:

```python
"""Tests for the Orchestrator agent loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from amplifier_service_sdk import (
    ChatResponse,
    Message,
    RoutingTable,
    TokenUsage,
    ToolCall,
)
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator


def _make_routing_table() -> RoutingTable:
    return RoutingTable(
        tools={"bash": "svc-bash"},
        providers={"mock": "svc-mock-provider"},
        hooks={},
        context="svc-context",
    )


class TestOrchestratorTextResponse:
    """Test the simple case: provider returns text, loop exits."""

    @pytest.mark.asyncio
    async def test_text_response_returns_content(self) -> None:
        """When the provider returns text (no tool calls), the loop returns it."""
        dapr = DaprClient(dapr_url="http://fake:3500")

        # Mock context service: add_message succeeds, get_messages returns the messages
        context_messages: list[dict[str, Any]] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any] | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            if method == "context/messages" and app_id == "svc-context":
                # POST to add message
                if data and "role" in data:
                    context_messages.append(data)
                    return {"success": True}
                # POST to provider
            if app_id == "svc-mock-provider" and "complete" in method:
                return ChatResponse(
                    content="Hello from mock",
                    tool_calls=None,
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                    stop_reason="end_turn",
                ).model_dump()
            return {"success": True}

        async def mock_invoke_get(
            app_id: str, method: str, params: dict[str, Any] | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-context" and method == "context/messages":
                return {"messages": context_messages}
            return {}

        dapr.invoke = AsyncMock(side_effect=mock_invoke)  # type: ignore[method-assign]
        dapr.invoke_get = AsyncMock(side_effect=mock_invoke_get)  # type: ignore[method-assign]
        dapr.publish = AsyncMock()  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, result_messages = await orch.execute(
            system_prompt="You are helpful",
            messages=[Message(role="user", content="Hello")],
            config={"provider_name": "mock"},
            routing_table=_make_routing_table(),
            session_id="test-session",
        )

        assert "Hello from mock" in result_text


class TestOrchestratorToolLoop:
    """Test the tool call loop: provider calls tool, gets result, then returns text."""

    @pytest.mark.asyncio
    async def test_tool_call_then_text(self) -> None:
        """Provider returns tool_call, orchestrator dispatches it, provider then returns text."""
        dapr = DaprClient(dapr_url="http://fake:3500")

        context_messages: list[dict[str, Any]] = []
        call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any] | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal call_count

            # Context: add message
            if app_id == "svc-context" and method == "context/messages":
                if data and "role" in data:
                    context_messages.append(data)
                    return {"success": True}

            # Provider: first call returns tool_call, second returns text
            if app_id == "svc-mock-provider" and "complete" in method:
                call_count += 1
                if call_count == 1:
                    return ChatResponse(
                        content="",
                        tool_calls=[
                            ToolCall(id="tc_1", name="bash", arguments={"command": "ls"})
                        ],
                        usage=TokenUsage(input_tokens=10, output_tokens=5),
                        stop_reason="tool_use",
                    ).model_dump()
                else:
                    return ChatResponse(
                        content="Files listed successfully",
                        tool_calls=None,
                        usage=TokenUsage(input_tokens=20, output_tokens=10),
                        stop_reason="end_turn",
                    ).model_dump()

            # Tool: bash execute
            if app_id == "svc-bash" and "execute" in method:
                return {
                    "success": True,
                    "output": {"stdout": "file1.txt\nfile2.txt", "stderr": "", "returncode": 0},
                }

            return {"success": True}

        async def mock_invoke_get(
            app_id: str, method: str, params: dict[str, Any] | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-context" and method == "context/messages":
                return {"messages": context_messages}
            return {}

        dapr.invoke = AsyncMock(side_effect=mock_invoke)  # type: ignore[method-assign]
        dapr.invoke_get = AsyncMock(side_effect=mock_invoke_get)  # type: ignore[method-assign]
        dapr.publish = AsyncMock()  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, _ = await orch.execute(
            system_prompt="You are helpful",
            messages=[Message(role="user", content="List files")],
            config={"provider_name": "mock"},
            routing_table=_make_routing_table(),
            session_id="test-session",
        )

        assert "Files listed successfully" in result_text
        assert call_count == 2


class TestOrchestratorMaxIterations:
    """Test that max_iterations config is respected."""

    @pytest.mark.asyncio
    async def test_max_iterations_stops_loop(self) -> None:
        dapr = DaprClient(dapr_url="http://fake:3500")
        context_messages: list[dict[str, Any]] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any] | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-context" and method == "context/messages":
                if data and "role" in data:
                    context_messages.append(data)
                    return {"success": True}
            if app_id == "svc-mock-provider" and "complete" in method:
                # Always return tool calls (loop forever if not limited)
                return ChatResponse(
                    content="",
                    tool_calls=[ToolCall(id="tc_1", name="bash", arguments={"command": "ls"})],
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                    stop_reason="tool_use",
                ).model_dump()
            if app_id == "svc-bash":
                return {"success": True, "output": "ok"}
            return {"success": True}

        async def mock_invoke_get(
            app_id: str, method: str, params: dict[str, Any] | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-context" and method == "context/messages":
                return {"messages": context_messages}
            return {}

        dapr.invoke = AsyncMock(side_effect=mock_invoke)  # type: ignore[method-assign]
        dapr.invoke_get = AsyncMock(side_effect=mock_invoke_get)  # type: ignore[method-assign]
        dapr.publish = AsyncMock()  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, _ = await orch.execute(
            system_prompt="You are helpful",
            messages=[Message(role="user", content="Loop test")],
            config={"provider_name": "mock", "max_iterations": 2},
            routing_table=_make_routing_table(),
            session_id="test-session",
        )

        # Should have stopped after 2 iterations
        assert result_text is not None
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/test_orchestrator.py -v -x 2>&1 | head -20
```

Expected: FAIL with `NotImplementedError`

**Step 3: Implement the orchestrator**

Replace the contents of `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`:

```python
"""Orchestrator -- drives the agent loop via forward Dapr service invocations.

Ported from amplifier_foundation.orchestrators.streaming. Key change:
instead of client.request() over stdio, the orchestrator makes forward
Dapr service invocation calls using the DaprClient wrapper.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from amplifier_service_sdk.models import (
    ChatResponse,
    Message,
    RoutingTable,
    ToolCall,
    ToolCapability,
)

from svc_orchestrator.dapr_client import DaprClient

logger = logging.getLogger(__name__)

_MAX_PROVIDER_RETRIES = 3
_PROVIDER_RETRY_DELAYS = (1.0, 2.0, 4.0)


class Orchestrator:
    """Agent loop orchestrator using Dapr service invocation.

    The orchestrator receives a routing table mapping component names to
    Dapr app-ids, and calls everything forward via Dapr SI.
    """

    def __init__(self, dapr: DaprClient) -> None:
        self._dapr = dapr

    async def execute(
        self,
        system_prompt: str,
        messages: list[Message],
        config: dict[str, Any],
        routing_table: RoutingTable,
        session_id: str = "",
    ) -> tuple[str, list[Message]]:
        """Execute the agent loop.

        Args:
            system_prompt: Assembled system prompt.
            messages: Initial messages (typically just the user prompt).
            config: Runtime config (provider_name, max_iterations, tools, etc.).
            routing_table: Maps component names to Dapr app-ids.
            session_id: Session ID for pub/sub topic scoping.

        Returns:
            Tuple of (final_response_text, all_messages).
        """
        max_iterations: int = config.get("max_iterations", -1)
        provider_name: str = config.get("provider_name", "mock")
        tools: list[dict[str, Any]] = config.get("tools", [])

        context_app_id = routing_table.context

        # Step 1: Add system prompt as system message to context
        if system_prompt:
            await self._context_add_message(
                context_app_id,
                Message(role="system", content=system_prompt),
            )

        # Step 2: Add initial messages to context
        for msg in messages:
            await self._context_add_message(context_app_id, msg)

        # Step 3: Main agent loop
        iteration = 0
        response_text = ""

        while max_iterations == -1 or iteration < max_iterations:
            iteration += 1

            # Get messages from context
            context_messages = await self._context_get_messages(context_app_id)

            # Build ChatRequest data
            chat_request_data: dict[str, Any] = {
                "messages": [m if isinstance(m, dict) else m for m in context_messages],
            }
            if tools:
                chat_request_data["tools"] = tools

            # Call provider
            provider_app_id = routing_table.providers.get(provider_name)
            if not provider_app_id:
                raise ValueError(
                    f"Provider '{provider_name}' not found in routing table"
                )

            response_data = await self._call_provider(
                provider_app_id, provider_name, chat_request_data
            )
            chat_response = ChatResponse.model_validate(response_data)

            # Extract response text
            response_text = self._extract_text(chat_response)

            # Publish stream token event
            if response_text and session_id:
                await self._publish_stream_event(
                    session_id, "stream.token", {"text": response_text}
                )

            # Add assistant message to context
            assistant_msg = Message(
                role="assistant",
                content=response_text,
                tool_calls=chat_response.tool_calls,
            )
            await self._context_add_message(context_app_id, assistant_msg)

            # If no tool calls, we're done
            if not chat_response.tool_calls:
                break

            # Dispatch tool calls
            tool_results = await self._dispatch_tools(
                chat_response.tool_calls, routing_table, session_id
            )

            # Add tool results to context
            for tool_call_id, tool_name, content, success in tool_results:
                metadata: dict[str, Any] | None = (
                    {"is_error": True} if not success else None
                )
                tool_msg = Message(
                    role="tool",
                    name=tool_name,
                    tool_call_id=tool_call_id,
                    content=content,
                    metadata=metadata,
                )
                await self._context_add_message(context_app_id, tool_msg)

        # Get final messages from context
        final_messages_raw = await self._context_get_messages(context_app_id)
        final_messages = [
            Message.model_validate(m) if isinstance(m, dict) else m
            for m in final_messages_raw
        ]

        return response_text, final_messages

    # ------------------------------------------------------------------
    # Context manager integration
    # ------------------------------------------------------------------

    async def _context_add_message(
        self, context_app_id: str, message: Message
    ) -> None:
        """Add a message to the context service."""
        await self._dapr.invoke(
            app_id=context_app_id,
            method="context/messages",
            data=message.model_dump(),
        )

    async def _context_get_messages(
        self, context_app_id: str
    ) -> list[dict[str, Any]]:
        """Get messages from the context service."""
        result = await self._dapr.invoke_get(
            app_id=context_app_id,
            method="context/messages",
        )
        return result.get("messages", [])

    # ------------------------------------------------------------------
    # Provider dispatch
    # ------------------------------------------------------------------

    async def _call_provider(
        self,
        provider_app_id: str,
        provider_name: str,
        chat_request_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Call the provider with retry logic."""
        for attempt in range(_MAX_PROVIDER_RETRIES + 1):
            try:
                return await self._dapr.invoke(
                    app_id=provider_app_id,
                    method=f"providers/{provider_name}/complete",
                    data=chat_request_data,
                    timeout=120.0,
                )
            except Exception as exc:
                is_last = attempt >= _MAX_PROVIDER_RETRIES
                if is_last:
                    logger.error(
                        "Provider call failed (attempt %d/%d): %s",
                        attempt + 1,
                        _MAX_PROVIDER_RETRIES + 1,
                        exc,
                    )
                    raise
                delay = _PROVIDER_RETRY_DELAYS[attempt]
                logger.warning(
                    "Provider call failed (attempt %d/%d, retrying in %.1fs): %s",
                    attempt + 1,
                    _MAX_PROVIDER_RETRIES + 1,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        # Unreachable, but satisfies type checker
        raise RuntimeError("Provider call exhausted retries")

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def _dispatch_tools(
        self,
        tool_calls: list[ToolCall],
        routing_table: RoutingTable,
        session_id: str,
    ) -> list[tuple[str, str, str, bool]]:
        """Dispatch tool calls in parallel.

        Returns list of (tool_call_id, tool_name, content, success).
        """
        tasks = [
            self._execute_single_tool(tc, routing_table, session_id)
            for tc in tool_calls
        ]
        return await asyncio.gather(*tasks)

    async def _execute_single_tool(
        self,
        tool_call: ToolCall,
        routing_table: RoutingTable,
        session_id: str,
    ) -> tuple[str, str, str, bool]:
        """Execute a single tool via Dapr SI.

        Never raises -- errors become error-message strings.
        """
        try:
            # Publish tool call start event
            if session_id:
                await self._publish_stream_event(
                    session_id,
                    "stream.tool_call",
                    {"tool_name": tool_call.name, "arguments": tool_call.arguments},
                )

            # Resolve tool service
            tool_app_id = routing_table.tools.get(tool_call.name)
            if not tool_app_id:
                return (
                    tool_call.id,
                    tool_call.name,
                    f"Error: tool '{tool_call.name}' not found in routing table",
                    False,
                )

            # Call tool service
            result = await self._dapr.invoke(
                app_id=tool_app_id,
                method=f"tools/{tool_call.name}/execute",
                data={"name": tool_call.name, "input": tool_call.arguments},
            )

            # Serialize output
            success = result.get("success", True)
            output = result.get("output")
            if output is not None:
                if isinstance(output, (dict, list)):
                    content = json.dumps(output)
                else:
                    content = str(output)
            elif result.get("error"):
                content = json.dumps(result["error"])
            else:
                content = ""

            # Publish tool result event
            if session_id:
                await self._publish_stream_event(
                    session_id,
                    "stream.tool_result",
                    {
                        "tool_name": tool_call.name,
                        "success": success,
                        "output": content[:2000],
                    },
                )

            return (tool_call.id, tool_call.name, content, success)

        except Exception as exc:
            logger.error("Tool %s failed: %s", tool_call.name, exc)
            return (
                tool_call.id,
                tool_call.name,
                f"Internal error executing tool: {exc}",
                False,
            )

    # ------------------------------------------------------------------
    # Pub/sub streaming
    # ------------------------------------------------------------------

    async def _publish_stream_event(
        self, session_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        """Publish a stream event to pub/sub. Best-effort -- never raises."""
        try:
            await self._dapr.publish(
                pubsub_name="pubsub",
                topic=f"session/{session_id}/stream",
                data={
                    "session_id": session_id,
                    "event_type": event_type,
                    **data,
                },
            )
        except Exception:
            logger.debug("Failed to publish stream event %s", event_type)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(response: ChatResponse) -> str:
        """Extract plain text from a ChatResponse."""
        if isinstance(response.content, str):
            return response.content
        if isinstance(response.content, list):
            parts = []
            for block in response.content:
                if isinstance(block, dict):
                    text = block.get("text", "")
                elif hasattr(block, "text"):
                    text = block.text
                else:
                    text = ""
                if text:
                    parts.append(text)
            return "\n\n".join(parts)
        return ""
```

**Step 4: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/test_orchestrator.py -v
```

Expected: ALL PASS

**Step 5: Run all orchestrator tests**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/ -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/svc-orchestrator/ && git commit -m "feat(svc-orchestrator): implement core agent loop with context/tool/provider dispatch"
```

---

### Task 9: Orchestrator -- Tool Dispatch Edge Cases

**Files:**
- Modify: `services/svc-orchestrator/tests/test_orchestrator.py`

This task adds edge case tests for tool dispatch and verifies the existing implementation handles them correctly.

**Step 1: Add edge case tests**

Add these test classes to `services/svc-orchestrator/tests/test_orchestrator.py`:

```python
class TestToolDispatchEdgeCases:
    """Test tool dispatch edge cases."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        """Unknown tool name returns error content without raising."""
        dapr = DaprClient(dapr_url="http://fake:3500")
        context_messages: list[dict[str, Any]] = []

        provider_calls = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any] | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_calls
            if app_id == "svc-context" and method == "context/messages":
                if data and "role" in data:
                    context_messages.append(data)
                    return {"success": True}
            if app_id == "svc-mock-provider" and "complete" in method:
                provider_calls += 1
                if provider_calls == 1:
                    return ChatResponse(
                        content="",
                        tool_calls=[ToolCall(id="tc_1", name="unknown_tool", arguments={})],
                        usage=TokenUsage(input_tokens=10, output_tokens=5),
                        stop_reason="tool_use",
                    ).model_dump()
                return ChatResponse(
                    content="Got it",
                    tool_calls=None,
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                    stop_reason="end_turn",
                ).model_dump()
            return {"success": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-context" and method == "context/messages":
                return {"messages": context_messages}
            return {}

        dapr.invoke = AsyncMock(side_effect=mock_invoke)  # type: ignore[method-assign]
        dapr.invoke_get = AsyncMock(side_effect=mock_invoke_get)  # type: ignore[method-assign]
        dapr.publish = AsyncMock()  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, _ = await orch.execute(
            system_prompt="You are helpful",
            messages=[Message(role="user", content="Do something")],
            config={"provider_name": "mock"},
            routing_table=_make_routing_table(),
            session_id="test-session",
        )

        # Should not raise -- the error becomes a tool result message
        assert result_text is not None
        # Check that the error was added to context
        tool_results = [m for m in context_messages if m.get("role") == "tool"]
        assert any("not found" in (m.get("content") or "") for m in tool_results)

    @pytest.mark.asyncio
    async def test_tool_service_error_returns_error_content(self) -> None:
        """When tool service raises HTTP error, it becomes an error message."""
        import httpx

        dapr = DaprClient(dapr_url="http://fake:3500")
        context_messages: list[dict[str, Any]] = []
        provider_calls = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any] | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_calls
            if app_id == "svc-context" and method == "context/messages":
                if data and "role" in data:
                    context_messages.append(data)
                    return {"success": True}
            if app_id == "svc-mock-provider" and "complete" in method:
                provider_calls += 1
                if provider_calls == 1:
                    return ChatResponse(
                        content="",
                        tool_calls=[ToolCall(id="tc_1", name="bash", arguments={"command": "ls"})],
                        usage=TokenUsage(input_tokens=10, output_tokens=5),
                        stop_reason="tool_use",
                    ).model_dump()
                return ChatResponse(
                    content="Done",
                    tool_calls=None,
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                    stop_reason="end_turn",
                ).model_dump()
            if app_id == "svc-bash":
                raise httpx.HTTPStatusError(
                    "Service error",
                    request=httpx.Request("POST", "http://fake/"),
                    response=httpx.Response(500),
                )
            return {"success": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-context" and method == "context/messages":
                return {"messages": context_messages}
            return {}

        dapr.invoke = AsyncMock(side_effect=mock_invoke)  # type: ignore[method-assign]
        dapr.invoke_get = AsyncMock(side_effect=mock_invoke_get)  # type: ignore[method-assign]
        dapr.publish = AsyncMock()  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, _ = await orch.execute(
            system_prompt="sys",
            messages=[Message(role="user", content="test")],
            config={"provider_name": "mock"},
            routing_table=_make_routing_table(),
            session_id="test-session",
        )

        # Should not raise -- error becomes a tool result
        assert result_text is not None
        tool_results = [m for m in context_messages if m.get("role") == "tool"]
        assert any("error" in (m.get("content") or "").lower() for m in tool_results)
```

**Step 2: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/test_orchestrator.py -v
```

Expected: ALL PASS (the orchestrator already handles these cases)

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/svc-orchestrator/ && git commit -m "test(svc-orchestrator): add tool dispatch edge case tests"
```

---

### Task 10: Orchestrator -- Provider Dispatch with Retry

**Files:**
- Modify: `services/svc-orchestrator/tests/test_orchestrator.py`

**Step 1: Add retry tests**

Add this test class to `services/svc-orchestrator/tests/test_orchestrator.py`:

```python
class TestProviderRetry:
    """Test provider call retry logic."""

    @pytest.mark.asyncio
    async def test_retries_on_transient_failure(self) -> None:
        """Provider call retries on failure and succeeds on second attempt."""
        dapr = DaprClient(dapr_url="http://fake:3500")
        context_messages: list[dict[str, Any]] = []
        invoke_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any] | None = None, **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal invoke_call_count
            if app_id == "svc-context" and method == "context/messages":
                if data and "role" in data:
                    context_messages.append(data)
                    return {"success": True}
            if app_id == "svc-mock-provider" and "complete" in method:
                invoke_call_count += 1
                if invoke_call_count == 1:
                    raise ConnectionError("Transient network error")
                return ChatResponse(
                    content="Recovered",
                    tool_calls=None,
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                    stop_reason="end_turn",
                ).model_dump()
            return {"success": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            if app_id == "svc-context" and method == "context/messages":
                return {"messages": context_messages}
            return {}

        dapr.invoke = AsyncMock(side_effect=mock_invoke)  # type: ignore[method-assign]
        dapr.invoke_get = AsyncMock(side_effect=mock_invoke_get)  # type: ignore[method-assign]
        dapr.publish = AsyncMock()  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        result_text, _ = await orch.execute(
            system_prompt="sys",
            messages=[Message(role="user", content="test")],
            config={"provider_name": "mock"},
            routing_table=_make_routing_table(),
            session_id="test-session",
        )

        assert "Recovered" in result_text
        assert invoke_call_count == 2  # First failed, second succeeded
```

**Step 2: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/test_orchestrator.py::TestProviderRetry -v
```

Expected: PASS

**Step 3: Run all orchestrator tests**

```bash
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/ -v
```

Expected: ALL PASS

**Step 4: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/svc-orchestrator/ && git commit -m "test(svc-orchestrator): add provider retry tests"
```

---

## Phase 2b: Session Service + Integration

### Task 11: Session Service -- Package Scaffold + App

**Files:**
- Create: `services/session-service/pyproject.toml`
- Create: `services/session-service/describe.yaml`
- Create: `services/session-service/Dockerfile`
- Create: `services/session-service/src/session_service/__init__.py`
- Create: `services/session-service/src/session_service/app.py`
- Create: `services/session-service/tests/__init__.py`
- Create: `services/session-service/tests/test_app.py`

**Step 1: Create package scaffold**

Create `services/session-service/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "session-service"
version = "0.1.0"
description = "Amplifier session service -- thin gateway for session lifecycle"
requires-python = ">=3.11"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
    "pyyaml>=6.0",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/session_service"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]
venvPath = "."
venv = ".venv"

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Create `services/session-service/describe.yaml`:

```yaml
name: session-service
version: '0.1.0'
```

Create `services/session-service/src/session_service/__init__.py`:

```python
"""Amplifier session service -- thin gateway for session lifecycle."""
```

Create `services/session-service/tests/__init__.py`:

```python
```

**Step 2: Write the failing tests**

Create `services/session-service/tests/test_app.py`:

```python
"""Tests for the session-service FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from session_service.app import create_session_app


class TestModuleLevelApp:
    def test_module_exposes_app(self) -> None:
        from session_service import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)


class TestSessionApp:
    @pytest.fixture
    def client(self) -> TestClient:
        app = create_session_app()
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe(self, client: TestClient) -> None:
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "session-service"

    def test_turn_endpoint_exists(self, client: TestClient) -> None:
        """POST /sessions/{id}/turn returns 422 with empty body (endpoint exists)."""
        response = client.post("/sessions/test-session/turn", json={})
        assert response.status_code == 422

    def test_session_info_endpoint_exists(self, client: TestClient) -> None:
        """GET /sessions/{id} returns 404 for unknown session (endpoint exists)."""
        response = client.get("/sessions/nonexistent")
        assert response.status_code == 404
```

**Step 3: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv sync && uv run pytest tests/test_app.py -v -x 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError`

**Step 4: Implement the app scaffold**

Create `services/session-service/src/session_service/app.py`:

```python
"""FastAPI app for session-service -- the session lifecycle gateway."""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from amplifier_service_sdk.models import Message
from amplifier_service_sdk.service import ServiceConfig, create_app

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")


class TurnRequest(BaseModel):
    """Request body for POST /sessions/{session_id}/turn."""

    prompt: str
    workspace_content: dict[str, str] = Field(default_factory=dict)
    agent_ref: str = "default"
    services: list[str] = Field(default_factory=list)
    provider_name: str = "mock"


class TurnResponse(BaseModel):
    """Response from POST /sessions/{session_id}/turn."""

    session_id: str
    result: str
    messages: list[Message]


class SessionInfo(BaseModel):
    """Info about a session."""

    session_id: str
    status: str
    turn_count: int


# In-memory session store (replaced by Dapr state in Task 14)
_sessions: dict[str, dict[str, Any]] = {}


def create_session_app(dapr_url: str | None = None) -> FastAPI:
    """Create the session-service FastAPI application."""
    if dapr_url is None:
        dapr_url = f"http://localhost:{_DAPR_HTTP_PORT}"

    config = ServiceConfig(name="session-service")
    app = create_app(config)

    @app.post("/sessions/{session_id}/turn")
    async def turn(session_id: str, request: TurnRequest) -> dict[str, Any]:
        """Execute a turn in the session.

        This is the main entry point. It:
        1. Discovers services (calls /describe on each)
        2. Builds a routing table
        3. Assembles the system prompt
        4. Invokes the orchestrator
        5. Persists the transcript
        6. Returns the result
        """
        # Import here to avoid circular imports during module load
        from session_service.discovery import discover_services
        from session_service.content import assemble_system_prompt
        from session_service.state import save_transcript, load_transcript

        # Ensure session exists
        if session_id not in _sessions:
            _sessions[session_id] = {
                "status": "active",
                "turn_count": 0,
            }

        # Step 1: Discover services and build routing table
        service_app_ids = request.services or [
            "svc-bash",
            "svc-mock-provider",
            "svc-context",
        ]
        routing_table = await discover_services(
            service_app_ids=service_app_ids,
            dapr_url=dapr_url,
        )

        # Step 2: Assemble system prompt
        system_prompt = await assemble_system_prompt(
            routing_table=routing_table,
            workspace_content=request.workspace_content,
            dapr_url=dapr_url,
        )

        # Step 3: Load prior messages (for session continuity)
        prior_messages = await load_transcript(
            session_id=session_id,
            dapr_url=dapr_url,
        )

        # Step 4: Invoke orchestrator
        import httpx

        orchestrator_url = (
            f"{dapr_url}/v1.0/invoke/svc-orchestrator/method/orchestrator/execute"
        )

        # Build tools list from routing table
        tools = routing_table.get("_tool_specs", [])

        execute_payload = {
            "system_prompt": system_prompt,
            "messages": [{"role": "user", "content": request.prompt}],
            "config": {
                "provider_name": request.provider_name,
                "tools": tools,
                "max_iterations": 25,
            },
            "routing_table": routing_table,
            "session_id": session_id,
        }

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(orchestrator_url, json=execute_payload)
            response.raise_for_status()
            result_data = response.json()

        result_text = result_data.get("result", "")
        result_messages = [
            Message.model_validate(m) for m in result_data.get("messages", [])
        ]

        # Step 5: Persist transcript
        await save_transcript(
            session_id=session_id,
            messages=result_messages,
            dapr_url=dapr_url,
        )

        # Update session state
        _sessions[session_id]["turn_count"] += 1

        return TurnResponse(
            session_id=session_id,
            result=result_text,
            messages=result_messages,
        ).model_dump()

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        """Get session info."""
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        session = _sessions[session_id]
        return SessionInfo(
            session_id=session_id,
            status=session["status"],
            turn_count=session["turn_count"],
        ).model_dump()

    return app


app = create_session_app()
```

Create `services/session-service/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/session-service/ /build/session-service/
RUN cd /build/session-service && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "session_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Now create stub modules so the imports work. These will be implemented in Tasks 12-14.

Create `services/session-service/src/session_service/discovery.py`:

```python
"""Service discovery -- calls /describe on services, builds routing table."""

from __future__ import annotations

from typing import Any


async def discover_services(
    service_app_ids: list[str],
    dapr_url: str,
) -> dict[str, Any]:
    """Discover services and build a routing table. Stub -- implemented in Task 12."""
    return {
        "tools": {},
        "providers": {},
        "hooks": {},
        "context": "svc-context",
    }
```

Create `services/session-service/src/session_service/content.py`:

```python
"""Content assembly -- collects content from services and builds system prompt."""

from __future__ import annotations

from typing import Any


async def assemble_system_prompt(
    routing_table: dict[str, Any],
    workspace_content: dict[str, str],
    dapr_url: str,
) -> str:
    """Assemble system prompt from service content + workspace content. Stub -- implemented in Task 13."""
    parts = []
    for path, content in workspace_content.items():
        parts.append(f'<context_file path="{path}">\n{content}\n</context_file>')
    return "\n".join(parts) if parts else "You are a helpful assistant."
```

Create `services/session-service/src/session_service/state.py`:

```python
"""State management -- Dapr state store integration for transcripts."""

from __future__ import annotations

from typing import Any

from amplifier_service_sdk.models import Message


async def save_transcript(
    session_id: str,
    messages: list[Message],
    dapr_url: str,
) -> None:
    """Save transcript to Dapr state store. Stub -- implemented in Task 14."""
    pass


async def load_transcript(
    session_id: str,
    dapr_url: str,
) -> list[Message]:
    """Load transcript from Dapr state store. Stub -- implemented in Task 14."""
    return []
```

**Step 5: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/test_app.py -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/session-service/ && git commit -m "feat(session-service): add session service scaffold with /sessions/{id}/turn endpoint"
```

---

### Task 12: Session Service -- Discovery Module

**Files:**
- Modify: `services/session-service/src/session_service/discovery.py`
- Create: `services/session-service/tests/test_discovery.py`

**Step 1: Write the failing tests**

Create `services/session-service/tests/test_discovery.py`:

```python
"""Tests for service discovery and routing table building."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from session_service.discovery import discover_services, build_routing_table


class TestBuildRoutingTable:
    def test_builds_tool_mapping(self) -> None:
        """Tool names are mapped to their service app-ids."""
        describe_results = {
            "svc-bash": {
                "name": "svc-bash",
                "tools": [
                    {"name": "bash", "description": "Run commands", "input_schema": {}},
                ],
                "hooks": [],
                "providers": [],
                "content_paths": [],
            },
        }
        rt = build_routing_table(describe_results, context_app_id="svc-context")
        assert rt["tools"]["bash"] == "svc-bash"
        assert rt["context"] == "svc-context"

    def test_builds_provider_mapping(self) -> None:
        """Provider names are mapped to their service app-ids."""
        describe_results = {
            "svc-mock-provider": {
                "name": "svc-mock-provider",
                "tools": [],
                "hooks": [],
                "providers": [{"name": "mock"}],
                "content_paths": [],
            },
        }
        rt = build_routing_table(describe_results, context_app_id="svc-context")
        assert rt["providers"]["mock"] == "svc-mock-provider"

    def test_builds_hook_mapping(self) -> None:
        """Hook events are mapped to lists of service app-ids."""
        describe_results = {
            "svc-hooks": {
                "name": "svc-hooks",
                "tools": [],
                "hooks": [{"name": "redaction", "events": ["tool:pre", "tool:post"]}],
                "providers": [],
                "content_paths": [],
            },
        }
        rt = build_routing_table(describe_results, context_app_id="svc-context")
        assert "svc-hooks" in rt["hooks"].get("tool:pre", [])
        assert "svc-hooks" in rt["hooks"].get("tool:post", [])

    def test_collects_tool_specs(self) -> None:
        """Tool specs are collected in _tool_specs for the orchestrator."""
        describe_results = {
            "svc-bash": {
                "name": "svc-bash",
                "tools": [
                    {
                        "name": "bash",
                        "description": "Run commands",
                        "input_schema": {"type": "object"},
                    },
                ],
                "hooks": [],
                "providers": [],
                "content_paths": [],
            },
        }
        rt = build_routing_table(describe_results, context_app_id="svc-context")
        assert len(rt["_tool_specs"]) == 1
        assert rt["_tool_specs"][0]["name"] == "bash"

    def test_multiple_services(self) -> None:
        """Routing table combines tools from multiple services."""
        describe_results = {
            "svc-bash": {
                "name": "svc-bash",
                "tools": [{"name": "bash", "description": "Run commands", "input_schema": {}}],
                "hooks": [],
                "providers": [],
                "content_paths": [],
            },
            "svc-mock-provider": {
                "name": "svc-mock-provider",
                "tools": [],
                "hooks": [],
                "providers": [{"name": "mock"}],
                "content_paths": [],
            },
        }
        rt = build_routing_table(describe_results, context_app_id="svc-context")
        assert rt["tools"]["bash"] == "svc-bash"
        assert rt["providers"]["mock"] == "svc-mock-provider"


class TestDiscoverServices:
    @pytest.mark.asyncio
    async def test_calls_describe_on_each_service(self) -> None:
        """discover_services calls /describe on each service app-id."""
        mock_responses = {
            "svc-bash": {
                "name": "svc-bash",
                "tools": [{"name": "bash", "description": "Run commands", "input_schema": {}}],
                "hooks": [],
                "providers": [],
                "content_paths": [],
            },
            "svc-context": {
                "name": "svc-context",
                "tools": [],
                "hooks": [],
                "providers": [],
                "content_paths": [],
            },
        }

        with patch("session_service.discovery._call_describe") as mock_describe:
            mock_describe.side_effect = lambda app_id, dapr_url: mock_responses.get(
                app_id, {"name": app_id, "tools": [], "hooks": [], "providers": [], "content_paths": []}
            )
            rt = await discover_services(
                service_app_ids=["svc-bash", "svc-context"],
                dapr_url="http://fake:3500",
            )

        assert rt["tools"]["bash"] == "svc-bash"
        assert rt["context"] == "svc-context"
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/test_discovery.py -v -x 2>&1 | head -20
```

Expected: FAIL with `ImportError` -- `build_routing_table` doesn't exist yet

**Step 3: Implement discovery**

Replace `services/session-service/src/session_service/discovery.py`:

```python
"""Service discovery -- calls /describe on services, builds routing table."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def build_routing_table(
    describe_results: dict[str, dict[str, Any]],
    context_app_id: str,
) -> dict[str, Any]:
    """Build a routing table from collected /describe responses.

    Args:
        describe_results: Map of app_id -> describe response dict.
        context_app_id: Dapr app-id of the context manager service.

    Returns:
        Routing table dict with keys: tools, providers, hooks, context, _tool_specs.
    """
    tools: dict[str, str] = {}
    providers: dict[str, str] = {}
    hooks: dict[str, list[str]] = {}
    tool_specs: list[dict[str, Any]] = []

    for app_id, describe in describe_results.items():
        # Tools
        for tool_spec in describe.get("tools", []):
            tool_name = tool_spec.get("name")
            if tool_name:
                tools[tool_name] = app_id
                tool_specs.append(tool_spec)

        # Providers
        for provider in describe.get("providers", []):
            provider_name = provider.get("name")
            if provider_name:
                providers[provider_name] = app_id

        # Hooks
        for hook in describe.get("hooks", []):
            events = hook.get("events", [])
            if "event" in hook:
                events = [hook["event"]]
            for event in events:
                if event not in hooks:
                    hooks[event] = []
                hooks[event].append(app_id)

    return {
        "tools": tools,
        "providers": providers,
        "hooks": hooks,
        "context": context_app_id,
        "_tool_specs": tool_specs,
    }


async def _call_describe(app_id: str, dapr_url: str) -> dict[str, Any]:
    """Call GET /describe on a service via Dapr SI."""
    url = f"{dapr_url}/v1.0/invoke/{app_id}/method/describe"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


async def discover_services(
    service_app_ids: list[str],
    dapr_url: str,
    context_app_id: str = "svc-context",
) -> dict[str, Any]:
    """Discover services and build a routing table.

    Calls GET /describe on each service via Dapr service invocation,
    then builds a routing table from the collected responses.
    """
    describe_results: dict[str, dict[str, Any]] = {}

    for app_id in service_app_ids:
        try:
            describe_data = await _call_describe(app_id, dapr_url)
            describe_results[app_id] = describe_data
            logger.info("Discovered service %s: %s", app_id, describe_data.get("name"))
        except Exception as exc:
            logger.warning("Failed to describe service %s: %s", app_id, exc)

    return build_routing_table(describe_results, context_app_id=context_app_id)
```

**Step 4: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/test_discovery.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/session-service/ && git commit -m "feat(session-service): implement service discovery and routing table builder"
```

---

### Task 13: Session Service -- Content Assembly

**Files:**
- Modify: `services/session-service/src/session_service/content.py`
- Create: `services/session-service/tests/test_content.py`

**Step 1: Write the failing tests**

Create `services/session-service/tests/test_content.py`:

```python
"""Tests for content assembly."""

from __future__ import annotations

import pytest

from session_service.content import assemble_system_prompt


class TestAssembleSystemPrompt:
    @pytest.mark.asyncio
    async def test_workspace_content_included(self) -> None:
        """Workspace content is formatted as context_file blocks."""
        prompt = await assemble_system_prompt(
            routing_table={"tools": {}, "providers": {}, "hooks": {}, "context": "svc-context"},
            workspace_content={"AGENTS.md": "# Instructions\nBe helpful"},
            dapr_url="http://fake:3500",
        )
        assert "AGENTS.md" in prompt
        assert "Be helpful" in prompt
        assert "<context_file" in prompt

    @pytest.mark.asyncio
    async def test_empty_workspace_returns_default(self) -> None:
        """Empty workspace content returns a default system prompt."""
        prompt = await assemble_system_prompt(
            routing_table={"tools": {}, "providers": {}, "hooks": {}, "context": "svc-context"},
            workspace_content={},
            dapr_url="http://fake:3500",
        )
        assert len(prompt) > 0

    @pytest.mark.asyncio
    async def test_multiple_workspace_files(self) -> None:
        """Multiple workspace files are all included."""
        prompt = await assemble_system_prompt(
            routing_table={"tools": {}, "providers": {}, "hooks": {}, "context": "svc-context"},
            workspace_content={
                "AGENTS.md": "# Agents",
                ".amplifier/config.md": "# Config",
            },
            dapr_url="http://fake:3500",
        )
        assert "AGENTS.md" in prompt
        assert ".amplifier/config.md" in prompt
```

**Step 2: Run tests to verify they pass (stub already works)**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/test_content.py -v
```

Expected: PASS (the stub implementation already handles workspace content). If any fail, update the implementation.

**Step 3: Improve the content assembly implementation**

Replace `services/session-service/src/session_service/content.py`:

```python
"""Content assembly -- collects content from services and builds system prompt.

In Phase 2, this is a simplified version. Service content collection
(calling GET /content/{path} on services) will be added in Phase 3.
For now, only workspace_content (from the CLI payload) is assembled.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


async def assemble_system_prompt(
    routing_table: dict[str, Any],
    workspace_content: dict[str, str],
    dapr_url: str,
) -> str:
    """Assemble system prompt from service content + workspace content.

    Args:
        routing_table: The routing table (may contain content path info in future).
        workspace_content: Map of path -> content from the CLI payload.
        dapr_url: Dapr sidecar URL (for future service content fetching).

    Returns:
        Assembled system prompt string.
    """
    parts: list[str] = []

    # TODO (Phase 3): Fetch service content via GET /content/{path}
    # For now, only workspace_content is assembled.

    for path, content in workspace_content.items():
        parts.append(f'<context_file path="{path}">\n{content}\n</context_file>')

    if not parts:
        return _DEFAULT_SYSTEM_PROMPT

    return "\n".join(parts)
```

**Step 4: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/test_content.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/session-service/ && git commit -m "feat(session-service): implement content assembly for system prompt"
```

---

### Task 14: Session Service -- State Management

**Files:**
- Modify: `services/session-service/src/session_service/state.py`
- Create: `services/session-service/tests/test_state.py`

**Step 1: Write the failing tests**

Create `services/session-service/tests/test_state.py`:

```python
"""Tests for state management via Dapr state store."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from amplifier_service_sdk import Message
from session_service.state import save_transcript, load_transcript


class TestSaveTranscript:
    @pytest.mark.asyncio
    async def test_save_calls_dapr_state_api(self) -> None:
        """save_transcript posts to the Dapr state store API."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]

        with patch("session_service.state._save_state") as mock_save:
            mock_save.return_value = None
            await save_transcript(
                session_id="sess-123",
                messages=messages,
                dapr_url="http://fake:3500",
            )
            mock_save.assert_called_once()
            call_args = mock_save.call_args
            assert call_args[1]["key"] == "sess-123-transcript"
            assert len(call_args[1]["value"]) == 2


class TestLoadTranscript:
    @pytest.mark.asyncio
    async def test_load_returns_empty_for_missing_session(self) -> None:
        """load_transcript returns empty list when session doesn't exist."""
        with patch("session_service.state._get_state") as mock_get:
            mock_get.return_value = None
            messages = await load_transcript(
                session_id="nonexistent",
                dapr_url="http://fake:3500",
            )
            assert messages == []

    @pytest.mark.asyncio
    async def test_load_returns_messages(self) -> None:
        """load_transcript returns deserialized messages."""
        stored = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        with patch("session_service.state._get_state") as mock_get:
            mock_get.return_value = stored
            messages = await load_transcript(
                session_id="sess-123",
                dapr_url="http://fake:3500",
            )
            assert len(messages) == 2
            assert messages[0].role == "user"
            assert messages[1].content == "Hi"
```

**Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/test_state.py -v -x 2>&1 | head -20
```

Expected: FAIL (stubs don't have `_save_state` / `_get_state`)

**Step 3: Implement state management**

Replace `services/session-service/src/session_service/state.py`:

```python
"""State management -- Dapr state store integration for session transcripts.

Uses the Dapr state store API to persist and load session transcripts.
The state store component is named "statestore" (configured in docker/dapr/components/statestore.yaml).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from amplifier_service_sdk.models import Message

logger = logging.getLogger(__name__)

_STATE_STORE_NAME = "statestore"


async def _save_state(
    dapr_url: str,
    key: str,
    value: Any,
) -> None:
    """Save a value to the Dapr state store."""
    url = f"{dapr_url}/v1.0/state/{_STATE_STORE_NAME}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=[{"key": key, "value": value}])
        response.raise_for_status()


async def _get_state(
    dapr_url: str,
    key: str,
) -> Any | None:
    """Get a value from the Dapr state store. Returns None if not found."""
    url = f"{dapr_url}/v1.0/state/{_STATE_STORE_NAME}/{key}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        if response.status_code == 204 or not response.content:
            return None
        response.raise_for_status()
        return response.json()


async def save_transcript(
    session_id: str,
    messages: list[Message],
    dapr_url: str,
) -> None:
    """Save session transcript to Dapr state store."""
    key = f"{session_id}-transcript"
    value = [m.model_dump() for m in messages]
    try:
        await _save_state(dapr_url=dapr_url, key=key, value=value)
        logger.info("Saved %d messages for session %s", len(messages), session_id)
    except Exception as exc:
        logger.error("Failed to save transcript for %s: %s", session_id, exc)


async def load_transcript(
    session_id: str,
    dapr_url: str,
) -> list[Message]:
    """Load session transcript from Dapr state store."""
    key = f"{session_id}-transcript"
    try:
        data = await _get_state(dapr_url=dapr_url, key=key)
        if data is None:
            return []
        return [Message.model_validate(m) for m in data]
    except Exception as exc:
        logger.error("Failed to load transcript for %s: %s", session_id, exc)
        return []
```

**Step 4: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/test_state.py -v
```

Expected: ALL PASS

**Step 5: Run all session-service tests**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/ -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
cd /data/labs/amplifier-ipc && git add services/session-service/ && git commit -m "feat(session-service): implement Dapr state store integration for transcripts"
```

---

### Task 15: Docker Compose Update

**Files:**
- Modify: `docker-compose.yaml`

**Step 1: Update Docker Compose**

Replace the contents of `docker-compose.yaml`:

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  # --- Machine Service ---
  svc-machine:
    build:
      context: .
      dockerfile: services/svc-machine/Dockerfile
    environment:
      WORKSPACE_DIR: /workspace
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
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr:/config
    network_mode: "service:svc-machine"
    depends_on:
      - svc-machine

  # --- Bash Tool Service ---
  svc-bash:
    build:
      context: .
      dockerfile: services/svc-bash/Dockerfile
    environment:
      DAPR_HTTP_PORT: "3500"
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
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr:/config
    network_mode: "service:svc-bash"
    depends_on:
      - svc-bash

  # --- Context Manager Service ---
  svc-context:
    build:
      context: .
      dockerfile: services/svc-context/Dockerfile
    environment:
      DAPR_HTTP_PORT: "3500"
    depends_on:
      - redis

  svc-context-dapr:
    image: daprio/daprd:1.14.4
    command:
      - ./daprd
      - --app-id=svc-context
      - --app-port=8000
      - --dapr-http-port=3500
      - --dapr-grpc-port=50001
      - --resources-path=/components
      - --config=/config/config.yaml
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr:/config
    network_mode: "service:svc-context"
    depends_on:
      - svc-context

  # --- Mock Provider Service ---
  svc-mock-provider:
    build:
      context: .
      dockerfile: services/svc-mock-provider/Dockerfile
    environment:
      DAPR_HTTP_PORT: "3500"
    depends_on:
      - redis

  svc-mock-provider-dapr:
    image: daprio/daprd:1.14.4
    command:
      - ./daprd
      - --app-id=svc-mock-provider
      - --app-port=8000
      - --dapr-http-port=3500
      - --dapr-grpc-port=50001
      - --resources-path=/components
      - --config=/config/config.yaml
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr:/config
    network_mode: "service:svc-mock-provider"
    depends_on:
      - svc-mock-provider

  # --- Orchestrator Service ---
  svc-orchestrator:
    build:
      context: .
      dockerfile: services/svc-orchestrator/Dockerfile
    environment:
      DAPR_HTTP_PORT: "3500"
    depends_on:
      - redis
      - svc-context-dapr
      - svc-mock-provider-dapr
      - svc-bash-dapr

  svc-orchestrator-dapr:
    image: daprio/daprd:1.14.4
    command:
      - ./daprd
      - --app-id=svc-orchestrator
      - --app-port=8000
      - --dapr-http-port=3500
      - --dapr-grpc-port=50001
      - --resources-path=/components
      - --config=/config/config.yaml
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr:/config
    network_mode: "service:svc-orchestrator"
    depends_on:
      - svc-orchestrator

  # --- Session Service ---
  session-service:
    build:
      context: .
      dockerfile: services/session-service/Dockerfile
    environment:
      DAPR_HTTP_PORT: "3500"
    ports:
      - "8080:8000"
    depends_on:
      - redis
      - svc-orchestrator-dapr
      - svc-context-dapr
      - svc-mock-provider-dapr
      - svc-bash-dapr

  session-service-dapr:
    image: daprio/daprd:1.14.4
    command:
      - ./daprd
      - --app-id=session-service
      - --app-port=8000
      - --dapr-http-port=3500
      - --dapr-grpc-port=50001
      - --resources-path=/components
      - --config=/config/config.yaml
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr:/config
    network_mode: "service:session-service"
    depends_on:
      - session-service
```

**Step 2: Verify the compose file is valid**

```bash
cd /data/labs/amplifier-ipc && docker compose config --quiet 2>&1
```

Expected: No errors (quiet output means valid)

**Step 3: Commit**

```bash
cd /data/labs/amplifier-ipc && git add docker-compose.yaml && git commit -m "feat(docker): add all Phase 2 services to Docker Compose"
```

---

### Task 16: Integration Test

**Files:**
- Create: `tests/test_integration_phase2.py`

This integration test runs in-process (no Docker required) by creating all four service apps and routing requests between them via HTTPX TestClients.

**Step 1: Write the integration test**

Create `tests/test_integration_phase2.py`:

```python
"""Phase 2 integration test -- end-to-end prompt flow through the full service stack.

This test runs in-process, simulating Dapr service invocation by routing
httpx calls to the appropriate TestClient. No Docker or Dapr required.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from svc_context.app import create_context_app
from svc_mock_provider.app import create_mock_provider_app


class TestEndToEndFlow:
    """End-to-end test proving the full stack flow works."""

    @pytest.fixture
    def context_client(self) -> TestClient:
        return TestClient(create_context_app())

    @pytest.fixture
    def provider_client(self) -> TestClient:
        return TestClient(create_mock_provider_app())

    def test_text_response_flow(
        self,
        context_client: TestClient,
        provider_client: TestClient,
    ) -> None:
        """A simple prompt flows through context -> provider -> response."""
        # Step 1: Add system message to context
        resp = context_client.post(
            "/context/messages",
            json={"role": "system", "content": "You are helpful"},
        )
        assert resp.status_code == 200

        # Step 2: Add user message to context
        resp = context_client.post(
            "/context/messages",
            json={"role": "user", "content": "Hello world"},
        )
        assert resp.status_code == 200

        # Step 3: Get messages from context
        resp = context_client.get("/context/messages")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 2

        # Step 4: Call provider with messages
        resp = provider_client.post(
            "/providers/mock/complete",
            json={"messages": messages},
        )
        assert resp.status_code == 200
        provider_resp = resp.json()
        assert provider_resp["content"] is not None
        assert provider_resp["stop_reason"] == "end_turn"

        # Step 5: Add assistant response to context
        resp = context_client.post(
            "/context/messages",
            json={"role": "assistant", "content": provider_resp["content"]},
        )
        assert resp.status_code == 200

        # Step 6: Verify full conversation in context
        resp = context_client.get("/context/messages")
        messages = resp.json()["messages"]
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    def test_tool_call_flow(
        self,
        context_client: TestClient,
        provider_client: TestClient,
    ) -> None:
        """A prompt triggering a tool call flows through the full loop."""
        # Step 1: Add system + user messages
        context_client.post(
            "/context/messages",
            json={"role": "system", "content": "You have access to a bash tool."},
        )
        context_client.post(
            "/context/messages",
            json={"role": "user", "content": "use bash to list files"},
        )

        # Step 2: Get messages and call provider
        resp = context_client.get("/context/messages")
        messages = resp.json()["messages"]

        resp = provider_client.post(
            "/providers/mock/complete",
            json={
                "messages": messages,
                "tools": [
                    {
                        "name": "bash",
                        "description": "Run commands",
                        "input_schema": {
                            "type": "object",
                            "properties": {"command": {"type": "string"}},
                            "required": ["command"],
                        },
                    }
                ],
            },
        )
        assert resp.status_code == 200
        provider_resp = resp.json()

        # Step 3: Provider should return a tool call
        assert provider_resp["tool_calls"] is not None
        assert len(provider_resp["tool_calls"]) == 1
        tool_call = provider_resp["tool_calls"][0]
        assert tool_call["name"] == "bash"

        # Step 4: Add assistant message with tool call to context
        context_client.post(
            "/context/messages",
            json={
                "role": "assistant",
                "content": "",
                "tool_calls": [tool_call],
            },
        )

        # Step 5: Simulate tool result (would come from svc-bash in real flow)
        context_client.post(
            "/context/messages",
            json={
                "role": "tool",
                "content": "file1.txt\nfile2.txt",
                "tool_call_id": tool_call["id"],
                "name": "bash",
            },
        )

        # Step 6: Call provider again -- should get text response (end_turn)
        resp = context_client.get("/context/messages")
        messages = resp.json()["messages"]

        resp = provider_client.post(
            "/providers/mock/complete",
            json={"messages": messages},
        )
        assert resp.status_code == 200
        provider_resp = resp.json()
        assert provider_resp["tool_calls"] is None
        assert provider_resp["stop_reason"] == "end_turn"
        assert "tool returned" in provider_resp["content"].lower() or "file" in provider_resp["content"].lower()

        # Step 7: Verify full conversation
        resp = context_client.get("/context/messages")
        messages = resp.json()["messages"]
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user", "assistant", "tool"]


class TestServiceDescribeContracts:
    """Verify all Phase 2 services implement the describe contract."""

    def test_context_service_describe(self) -> None:
        client = TestClient(create_context_app())
        resp = client.get("/describe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "svc-context"
        assert "version" in data

    def test_mock_provider_describe(self) -> None:
        client = TestClient(create_mock_provider_app())
        resp = client.get("/describe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "svc-mock-provider"
        provider_names = [p["name"] for p in data["providers"]]
        assert "mock" in provider_names

    def test_context_service_healthz(self) -> None:
        client = TestClient(create_context_app())
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_mock_provider_healthz(self) -> None:
        client = TestClient(create_mock_provider_app())
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
```

**Step 2: Run the integration test**

This requires the SDK and service packages to be importable. Install them:

```bash
cd /data/labs/amplifier-ipc && uv pip install --system -e amplifier-service-sdk -e services/svc-context -e services/svc-mock-provider -e services/svc-orchestrator -e services/session-service 2>&1 | tail -5
```

Then run:

```bash
cd /data/labs/amplifier-ipc && python -m pytest tests/test_integration_phase2.py -v
```

Expected: ALL PASS

**Step 3: Run all Phase 2 unit tests across services**

```bash
cd /data/labs/amplifier-ipc/amplifier-service-sdk && uv run pytest tests/ -v
cd /data/labs/amplifier-ipc/services/svc-context && uv run pytest tests/ -v
cd /data/labs/amplifier-ipc/services/svc-mock-provider && uv run pytest tests/ -v
cd /data/labs/amplifier-ipc/services/svc-orchestrator && uv run pytest tests/ -v
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/ -v
```

Expected: ALL PASS across all services

**Step 4: Commit**

```bash
cd /data/labs/amplifier-ipc && git add tests/test_integration_phase2.py && git commit -m "test: add Phase 2 end-to-end integration test"
```

---

## Summary

After completing all 16 tasks, the following is in place:

| Component | Location | Purpose |
|---|---|---|
| SDK Models (extended) | `amplifier-service-sdk/` | Message, ChatRequest, ChatResponse, RoutingTable, StreamEvent, ToolCall, TokenUsage, HookAction |
| svc-context | `services/svc-context/` | Context manager service with ephemeral compaction |
| svc-mock-provider | `services/svc-mock-provider/` | Mock LLM provider for testing |
| svc-orchestrator | `services/svc-orchestrator/` | Agent loop with forward Dapr calls |
| session-service | `services/session-service/` | Session lifecycle gateway |
| Docker Compose | `docker-compose.yaml` | All services + sidecars |
| Integration test | `tests/test_integration_phase2.py` | In-process end-to-end test |

**What works after Phase 2:**
A prompt can flow through the entire stack -- Session Service receives it, discovers services, builds a routing table, assembles the system prompt, invokes the Orchestrator, which calls the mock provider, dispatches tool calls to svc-bash (via svc-machine), adds results to svc-context, and returns the final response. Transcripts are persisted via Dapr state store. Stream events are published via Dapr pub/sub.

**What's deferred to Phase 3+:**
- Real LLM providers (Anthropic, OpenAI)
- All other tool/hook services
- Service content fetching (GET /content/{path})
- Hook dispatch (pre-hooks via SI, post-hooks via pub/sub)
- CLI rewrite + pub/sub subscription
- Session resume, child sessions, approval gating