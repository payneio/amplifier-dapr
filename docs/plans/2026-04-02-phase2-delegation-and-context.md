# Phase 2: Delegation & Context — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Implement session transcript persistence, enriched delegation with context inheritance and session resumption, and a full-featured context manager with 7-level compaction and paired tool-call removal.

**Architecture:** The session-service already persists transcripts to Dapr state store — we add a new `GET /sessions/{session_id}/messages` endpoint so delegation can read parent context. svc-context gets session-keyed isolation (one context per session) backed by Dapr state, and its compaction engine is rewritten to use 7 progressive levels with paired tool-call/result removal from upstream. svc-delegation gets a new schema with context inheritance (fetches parent transcript, filters, prepends to child), session resumption, and recursion guards. svc-orchestrator threads `delegation_depth` through the chain.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Dapr HTTP sidecar, pytest + pytest-asyncio (asyncio_mode=auto), httpx, `amplifier_service_sdk.models.Message`

---

## Phase 2a: Session-Service & Context Manager (Tasks 1–8)

### Task 1: session-service — GET /sessions/{session_id}/messages endpoint (test)

**Files:**
- Test: `services/session-service/tests/test_messages.py` (CREATE)

**Step 1: Write the failing test**

Create `services/session-service/tests/test_messages.py`:

```python
"""Tests for GET /sessions/{session_id}/messages endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from session_service.app import create_session_app


class TestGetMessages:
    """Tests for GET /sessions/{session_id}/messages."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the session-service app."""
        app = create_session_app(dapr_url="http://localhost:3500")
        return TestClient(app)

    def test_returns_transcript_from_state_store(self, client: TestClient) -> None:
        """GET /sessions/{id}/messages returns messages from Dapr state store."""
        stored = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        with patch(
            "session_service.app.load_transcript",
            new_callable=AsyncMock,
        ) as mock_load:
            from amplifier_service_sdk.models import Message

            mock_load.return_value = [Message(**m) for m in stored]
            response = client.get("/sessions/sess-abc/messages")

        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "hello"
        assert data["messages"][1]["role"] == "assistant"

    def test_returns_empty_for_unknown_session(self, client: TestClient) -> None:
        """GET /sessions/{id}/messages returns empty list for nonexistent session."""
        with patch(
            "session_service.app.load_transcript",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = client.get("/sessions/nonexistent/messages")

        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []

    def test_returns_session_id_in_response(self, client: TestClient) -> None:
        """GET /sessions/{id}/messages includes session_id in the response."""
        with patch(
            "session_service.app.load_transcript",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = client.get("/sessions/my-session/messages")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "my-session"
```

**Step 2: Run test to verify it fails**

```bash
cd services/session-service && uv run pytest tests/test_messages.py -v
```
Expected: FAIL — the `/sessions/{session_id}/messages` GET endpoint does not exist yet (404).

**Step 3: Implement the endpoint**

In `services/session-service/src/session_service/app.py`, add a new endpoint inside the `create_session_app` function, after the existing `@app.get("/sessions/{session_id}")` endpoint (around line 382). Insert this block before the `return app` line:

```python
    @app.get("/sessions/{session_id}/messages")
    async def session_messages(session_id: str) -> dict[str, Any]:
        """Return the session transcript from Dapr state store.

        Used by svc-delegation to fetch parent context for child sessions.
        Returns an empty list if the session has no transcript yet.
        """
        transcript: list[Message] = await load_transcript(session_id, _dapr_url)
        return {
            "session_id": session_id,
            "messages": [m.model_dump() for m in transcript],
        }
```

**Step 4: Run test to verify it passes**

```bash
cd services/session-service && uv run pytest tests/test_messages.py -v
```
Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
cd services/session-service && git add tests/test_messages.py src/session_service/app.py && git commit -m "feat(session-service): add GET /sessions/{id}/messages endpoint for transcript access"
```

---

### Task 2: svc-context — Session-keyed context manager (test)

**Files:**
- Test: `services/svc-context/tests/test_session_context.py` (CREATE)
- Modify: `services/svc-context/src/svc_context/context_manager.py`

**Step 1: Write the failing test**

Create `services/svc-context/tests/test_session_context.py`:

```python
"""Tests for session-keyed context isolation in SimpleContextManager."""

from __future__ import annotations

from amplifier_service_sdk.models import Message

from svc_context.context_manager import SimpleContextManager


class TestSessionKeyedIsolation:
    """Tests that each session_id gets isolated message storage."""

    async def test_different_sessions_are_isolated(self) -> None:
        """Messages added to one session are not visible in another."""
        cm = SimpleContextManager()

        await cm.add_message("session-a", Message(role="user", content="hello from A"))
        await cm.add_message("session-b", Message(role="user", content="hello from B"))

        msgs_a = await cm.get_messages("session-a")
        msgs_b = await cm.get_messages("session-b")

        assert len(msgs_a) == 1
        assert msgs_a[0].content == "hello from A"
        assert len(msgs_b) == 1
        assert msgs_b[0].content == "hello from B"

    async def test_clear_only_affects_target_session(self) -> None:
        """Clearing one session does not affect another."""
        cm = SimpleContextManager()

        await cm.add_message("s1", Message(role="user", content="msg1"))
        await cm.add_message("s2", Message(role="user", content="msg2"))
        await cm.clear("s1")

        assert len(await cm.get_messages("s1")) == 0
        assert len(await cm.get_messages("s2")) == 1

    async def test_set_messages_is_session_scoped(self) -> None:
        """set_messages replaces only the target session's messages."""
        cm = SimpleContextManager()

        await cm.add_message("s1", Message(role="user", content="old"))
        await cm.set_messages("s1", [Message(role="user", content="new")])
        await cm.add_message("s2", Message(role="user", content="untouched"))

        msgs_s1 = await cm.get_messages("s1")
        msgs_s2 = await cm.get_messages("s2")

        assert len(msgs_s1) == 1
        assert msgs_s1[0].content == "new"
        assert len(msgs_s2) == 1
        assert msgs_s2[0].content == "untouched"

    async def test_empty_session_returns_empty_list(self) -> None:
        """get_messages for a nonexistent session returns an empty list."""
        cm = SimpleContextManager()
        messages = await cm.get_messages("does-not-exist")
        assert messages == []
```

**Step 2: Run test to verify it fails**

```bash
cd services/svc-context && uv run pytest tests/test_session_context.py -v
```
Expected: FAIL — `add_message()` and `get_messages()` do not accept a `session_id` argument.

**Step 3: Implement session-keyed context manager**

Replace `services/svc-context/src/svc_context/context_manager.py` with:

```python
"""SimpleContextManager — session-keyed in-memory message storage with ephemeral progressive compaction."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from amplifier_service_sdk.models import Message


def _estimate_tokens(message: Message) -> int:
    """Estimate token count for a message using chars / 4 heuristic."""
    content = message.content
    if content is None:
        char_count = 0
    elif isinstance(content, str):
        char_count = len(content)
    elif isinstance(content, list):
        char_count = sum(
            len(item.get("text", "")) if isinstance(item, dict) else len(str(item))
            for item in content
        )
    else:
        char_count = len(str(content))
    return max(1, char_count // 4)


def _total_tokens(messages: list[Message]) -> int:
    """Sum token estimates for all messages."""
    return sum(_estimate_tokens(m) for m in messages)


def _truncate_content(message: Message, max_chars: int) -> Message:
    """Return a copy of message with content truncated to max_chars."""
    msg = message.model_copy(deep=True)
    if isinstance(msg.content, str) and len(msg.content) > max_chars:
        msg.content = msg.content[:max_chars] + "...[truncated]"
    return msg


def _is_tool_result(message: Message) -> bool:
    """Return True if the message is a tool result (role=tool or has tool_call_id)."""
    return message.role == "tool" or message.tool_call_id is not None


def _is_system(message: Message) -> bool:
    """Return True if the message is a system message."""
    return message.role == "system"


def _has_tool_calls(message: Message) -> bool:
    """Return True if the message is an assistant message with tool_calls."""
    return message.role == "assistant" and bool(message.tool_calls)


def _find_tool_call_pair_indices(
    messages: list[Message], assistant_idx: int
) -> list[int]:
    """Find indices of tool result messages that match the assistant's tool_calls.

    Scans forward from assistant_idx to find tool results whose tool_call_id matches
    one of the tool_calls in the assistant message.
    """
    assistant_msg = messages[assistant_idx]
    if not assistant_msg.tool_calls:
        return []
    tc_ids = {tc.id for tc in assistant_msg.tool_calls if tc.id}
    result_indices: list[int] = []
    for i in range(assistant_idx + 1, len(messages)):
        if messages[i].tool_call_id and messages[i].tool_call_id in tc_ids:
            result_indices.append(i)
    return result_indices


def _compact(
    messages: list[Message],
    target_tokens: int,
    protected_recent: float,
    protected_tool_results: int,
    truncate_chars: int,
) -> tuple[list[Message], dict]:
    """Apply progressive 7-level compaction until target_tokens is reached.

    System messages are NEVER compacted. The last 2 non-system messages are
    always protected. Tool-call/result pairs are always removed together.

    Returns (compacted_messages, stats_dict).
    """
    working = [m.model_copy(deep=True) for m in messages]
    stats = {"strategy_level": 0, "messages_removed": 0, "messages_truncated": 0,
             "user_messages_stubbed": 0, "before_messages": len(messages),
             "before_tokens": _total_tokens(messages)}

    def under_target() -> bool:
        return _total_tokens(working) <= target_tokens

    if under_target():
        stats["after_messages"] = len(working)
        stats["after_tokens"] = _total_tokens(working)
        return working, stats

    # Identify system vs non-system
    system_msgs = [m for m in working if _is_system(m)]
    non_system = [m for m in working if not _is_system(m)]

    # Tool result indices (within non_system)
    tool_result_indices = [i for i, m in enumerate(non_system) if _is_tool_result(m)]
    protected_tr = (
        set(tool_result_indices[-protected_tool_results:])
        if protected_tool_results > 0
        else set()
    )
    truncatable = [i for i in tool_result_indices if i not in protected_tr]

    # Wave boundaries
    wave1_end = max(1, len(truncatable) // 4)
    wave2_end = wave1_end + max(1, len(truncatable) // 4)

    def _rebuild() -> None:
        nonlocal working
        working = system_msgs + non_system

    # === Level 1: Truncate oldest 25% of tool results ===
    stats["strategy_level"] = 1
    for idx in truncatable[:wave1_end]:
        non_system[idx] = _truncate_content(non_system[idx], truncate_chars)
        stats["messages_truncated"] += 1
    _rebuild()
    if under_target():
        stats["after_messages"] = len(working)
        stats["after_tokens"] = _total_tokens(working)
        return working, stats

    # === Level 2: Truncate next 25% of tool results (50% total) ===
    stats["strategy_level"] = 2
    for idx in truncatable[wave1_end:wave2_end]:
        non_system[idx] = _truncate_content(non_system[idx], truncate_chars)
        stats["messages_truncated"] += 1
    _rebuild()
    if under_target():
        stats["after_messages"] = len(working)
        stats["after_tokens"] = _total_tokens(working)
        return working, stats

    # === Level 3: Remove oldest tool-call/result PAIRS (always together) ===
    stats["strategy_level"] = 3
    keep_recent_count = max(2, int(len(non_system) * protected_recent))
    protected_boundary = len(non_system) - keep_recent_count
    indices_to_remove: set[int] = set()

    for i, m in enumerate(non_system):
        if _total_tokens(system_msgs + [n for j, n in enumerate(non_system) if j not in indices_to_remove]) <= target_tokens:
            break
        if i >= protected_boundary:
            continue
        if _has_tool_calls(m):
            pair_indices = _find_tool_call_pair_indices(non_system, i)
            if all(pi < protected_boundary for pi in pair_indices):
                indices_to_remove.add(i)
                indices_to_remove.update(pair_indices)
        elif _is_tool_result(m):
            # Find its assistant — scan backwards
            for j in range(i - 1, -1, -1):
                if _has_tool_calls(non_system[j]):
                    pair_indices = _find_tool_call_pair_indices(non_system, j)
                    if j < protected_boundary and all(pi < protected_boundary for pi in pair_indices):
                        indices_to_remove.add(j)
                        indices_to_remove.update(pair_indices)
                    break

    non_system = [m for i, m in enumerate(non_system) if i not in indices_to_remove]
    stats["messages_removed"] += len(indices_to_remove)
    _rebuild()
    if under_target():
        stats["after_messages"] = len(working)
        stats["after_tokens"] = _total_tokens(working)
        return working, stats

    # === Level 4: Stub old user messages (replace body with "[message compacted]") ===
    stats["strategy_level"] = 4
    keep_recent_count = max(2, int(len(non_system) * protected_recent))
    protected_boundary = len(non_system) - keep_recent_count
    for i in range(protected_boundary):
        m = non_system[i]
        if m.role == "user" and isinstance(m.content, str) and len(m.content) > 80:
            stubbed = m.model_copy(deep=True)
            stubbed.content = "[message compacted]"
            non_system[i] = stubbed
            stats["user_messages_stubbed"] += 1
    _rebuild()
    if under_target():
        stats["after_messages"] = len(working)
        stats["after_tokens"] = _total_tokens(working)
        return working, stats

    # === Level 5: Remove oldest user/assistant PAIRS ===
    stats["strategy_level"] = 5
    keep_recent_count = max(2, int(len(non_system) * protected_recent * 0.6))
    protected_boundary = len(non_system) - keep_recent_count
    removal = set()
    for i in range(protected_boundary):
        if _total_tokens(system_msgs + [n for j, n in enumerate(non_system) if j not in removal]) <= target_tokens:
            break
        m = non_system[i]
        if m.role in ("user", "assistant") and not _has_tool_calls(m):
            removal.add(i)

    non_system = [m for i, m in enumerate(non_system) if i not in removal]
    stats["messages_removed"] += len(removal)
    _rebuild()
    if under_target():
        stats["after_messages"] = len(working)
        stats["after_tokens"] = _total_tokens(working)
        return working, stats

    # === Level 6: Remove all but last N turns ===
    stats["strategy_level"] = 6
    keep_n = max(4, int(len(non_system) * 0.3))
    removed_count = max(0, len(non_system) - keep_n)
    non_system = non_system[-keep_n:]
    stats["messages_removed"] += removed_count
    _rebuild()
    if under_target():
        stats["after_messages"] = len(working)
        stats["after_tokens"] = _total_tokens(working)
        return working, stats

    # === Level 7: Emergency — keep only system prompt + last turn ===
    stats["strategy_level"] = 7
    removed_count = max(0, len(non_system) - 2)
    non_system = non_system[-2:] if len(non_system) >= 2 else non_system[-1:]
    stats["messages_removed"] += removed_count
    _rebuild()
    stats["after_messages"] = len(working)
    stats["after_tokens"] = _total_tokens(working)
    return working, stats


def format_compaction_notice(stats: dict) -> str:
    """Generate a system-reminder block describing what compaction removed."""
    level = stats.get("strategy_level", 0)
    removed = stats.get("messages_removed", 0)
    truncated = stats.get("messages_truncated", 0)
    stubbed = stats.get("user_messages_stubbed", 0)

    parts = []
    if truncated > 0:
        parts.append(f"{truncated} tool results were truncated")
    if removed > 0:
        parts.append(f"{removed} older messages were removed")
    if stubbed > 0:
        parts.append(f"{stubbed} user messages were compacted")

    affected = "; ".join(parts) if parts else "minor adjustments were made"

    return (
        f'<system-reminder source="context-compaction">\n'
        f"Context was compacted (level {level}/7) to fit within token budget. "
        f"{affected}. "
        f"Re-run tools if you need full output from earlier in the conversation.\n"
        f"</system-reminder>"
    )


class SimpleContextManager:
    """Session-keyed in-memory context manager with ephemeral progressive compaction.

    Each session_id gets its own isolated message list.
    self._sessions[session_id] is NEVER modified by compaction —
    get_messages returns a compacted copy only.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, list[Message]] = {}
        self.max_tokens: int = 200_000
        self.compact_threshold: float = 0.85
        self.target_usage: float = 0.60
        self.protected_recent: float = 0.30
        self.protected_tool_results: int = 5
        self.truncate_chars: int = 8_000

    def _get_session(self, session_id: str) -> list[Message]:
        """Get or create the message list for a session."""
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        return self._sessions[session_id]

    # ------------------------------------------------------------------ #
    # Mutation methods                                                    #
    # ------------------------------------------------------------------ #

    async def add_message(self, session_id: str, message: Message) -> None:
        """Append a message to the session's store, stamping a timestamp into metadata."""
        msg = message.model_copy(deep=True)
        if msg.metadata is None:
            msg.metadata = {}
        msg.metadata["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
        self._get_session(session_id).append(msg)

    async def set_messages(self, session_id: str, messages: list[Message]) -> None:
        """Replace the stored message list for a session."""
        self._sessions[session_id] = [m.model_copy(deep=True) for m in messages]

    async def clear(self, session_id: str) -> None:
        """Empty the stored message list for a session."""
        self._sessions[session_id] = []

    # ------------------------------------------------------------------ #
    # Query (ephemeral compaction)                                        #
    # ------------------------------------------------------------------ #

    async def get_messages(
        self,
        session_id: str,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> list[Message]:
        """Return a (possibly compacted) copy of the session's message list.

        Compaction is ephemeral: the session's stored messages are never modified.
        """
        messages = self._get_session(session_id)
        if not messages:
            return []

        if context_window is not None:
            budget = context_window - (max_output_tokens or 0)
        else:
            budget = self.max_tokens

        snapshot: list[Message] = copy.deepcopy(messages)
        current_tokens = _total_tokens(snapshot)
        threshold = int(budget * self.compact_threshold)

        if current_tokens <= threshold:
            return snapshot

        target_tokens = int(budget * self.target_usage)
        compacted, stats = _compact(
            snapshot,
            target_tokens=target_tokens,
            protected_recent=self.protected_recent,
            protected_tool_results=self.protected_tool_results,
            truncate_chars=self.truncate_chars,
        )

        # Insert compaction notice after system messages
        if stats.get("strategy_level", 0) >= 1:
            notice_text = format_compaction_notice(stats)
            notice_msg = Message(
                role="system",
                content=notice_text,
                metadata={"source": "context-compaction", "ephemeral": True},
            )
            # Insert after the last system message
            insert_idx = 0
            for i, m in enumerate(compacted):
                if _is_system(m):
                    insert_idx = i + 1
                else:
                    break
            compacted.insert(insert_idx, notice_msg)

        return compacted
```

**Step 4: Run test to verify it passes**

```bash
cd services/svc-context && uv run pytest tests/test_session_context.py -v
```
Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
cd services/svc-context && git add tests/test_session_context.py src/svc_context/context_manager.py && git commit -m "feat(svc-context): session-keyed context manager with 7-level compaction"
```

---

### Task 3: svc-context — Fix existing context manager tests for new session-keyed API

**Files:**
- Modify: `services/svc-context/tests/test_context_manager.py`

**Step 1: Update all existing tests to pass session_id**

The existing tests in `test_context_manager.py` call `cm.add_message(msg)`, `cm.get_messages()`, `cm.clear()` etc. without a session_id. Update every call to include a `session_id` parameter. Use `"test-session"` as the default session_id throughout.

For every occurrence in the file, apply these transformations:
- `await cm.add_message(msg)` → `await cm.add_message("test-session", msg)`
- `await cm.get_messages()` → `await cm.get_messages("test-session")`
- `await cm.get_messages(context_window=..., max_output_tokens=...)` → `await cm.get_messages("test-session", context_window=..., max_output_tokens=...)`
- `await cm.set_messages(msgs)` → `await cm.set_messages("test-session", msgs)`
- `await cm.clear()` → `await cm.clear("test-session")`
- `cm.messages` → `cm._sessions.get("test-session", [])` (for direct access checks)

Also: the `_compact` function signature changed — it now returns `tuple[list[Message], dict]` and the old `_compact` signature is gone. The internal tests that directly tested `_compact` (if any) should be left for the compaction test file.

**Step 2: Run tests to verify they pass**

```bash
cd services/svc-context && uv run pytest tests/test_context_manager.py -v
```
Expected: All existing tests PASS with the updated API.

**Step 3: Commit**

```bash
cd services/svc-context && git add tests/test_context_manager.py && git commit -m "fix(svc-context): update existing tests for session-keyed context manager API"
```

---

### Task 4: svc-context — Update app.py for session-keyed endpoints

**Files:**
- Modify: `services/svc-context/src/svc_context/app.py`
- Modify: `services/svc-context/tests/test_app.py`

**Step 1: Update app tests to use session-keyed URL paths**

In `services/svc-context/tests/test_app.py`, update the test class `TestContextApp` to use the new session-keyed URL paths. Replace:
- `POST /context/messages` → `POST /context/test-session/messages`
- `GET /context/messages` → `GET /context/test-session/messages`
- `PUT /context/messages/bulk` → `PUT /context/test-session/messages/bulk`
- `POST /context/clear` → `POST /context/test-session/clear`

The request body for `POST /context/{session_id}/messages` stays the same (a `Message` JSON). The query params for `GET` stay the same.

Also add a test for the new system-prompt endpoint:

```python
    def test_set_system_prompt(self, client: TestClient) -> None:
        """POST /context/{session_id}/system-prompt stores a system prompt."""
        response = client.post(
            "/context/test-session/system-prompt",
            json={"content": "You are a helpful assistant."},
        )
        assert response.status_code == 200
        assert response.json() == {"success": True}

        # Verify it appears in messages
        get_response = client.get("/context/test-session/messages")
        msgs = get_response.json()["messages"]
        system_msgs = [m for m in msgs if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "You are a helpful assistant."
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-context && uv run pytest tests/test_app.py -v
```
Expected: FAIL — old paths still active, new session-keyed paths don't exist.

**Step 3: Rewrite app.py to use session-keyed paths**

Replace `services/svc-context/src/svc_context/app.py` with:

```python
"""FastAPI app factory for svc-context — the context management service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from amplifier_service_sdk.models import Message
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_context.context_manager import SimpleContextManager


class BulkMessagesRequest(BaseModel):
    """Request body for PUT /context/{session_id}/messages/bulk."""

    messages: list[Message]


class SystemPromptRequest(BaseModel):
    """Request body for POST /context/{session_id}/system-prompt."""

    content: str


def create_context_app() -> FastAPI:
    """Create the svc-context FastAPI application.

    All endpoints are session-keyed: /context/{session_id}/...
    Each session gets isolated message storage.

    Returns:
        Configured FastAPI application.
    """
    config = ServiceConfig(name="svc-context")
    app = create_app(config)
    manager = SimpleContextManager()

    @app.post("/context/{session_id}/messages")
    async def add_message(session_id: str, message: Message) -> dict[str, Any]:
        """Add a message to the session's context."""
        await manager.add_message(session_id, message)
        return {"success": True}

    @app.get("/context/{session_id}/messages")
    async def get_messages(
        session_id: str,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Get all messages from the session's context, with optional compaction."""
        messages = await manager.get_messages(
            session_id,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
        )
        return {"messages": [m.model_dump() for m in messages]}

    @app.put("/context/{session_id}/messages/bulk")
    async def bulk_set_messages(
        session_id: str, request: BulkMessagesRequest
    ) -> dict[str, Any]:
        """Replace all messages in the session's context."""
        await manager.set_messages(session_id, request.messages)
        return {"success": True}

    @app.post("/context/{session_id}/clear")
    async def clear_messages(session_id: str) -> dict[str, Any]:
        """Clear all messages from the session's context."""
        await manager.clear(session_id)
        return {"success": True}

    @app.post("/context/{session_id}/system-prompt")
    async def set_system_prompt(
        session_id: str, request: SystemPromptRequest
    ) -> dict[str, Any]:
        """Set the system prompt for a session.

        Replaces any existing system message at position 0.
        """
        messages = manager._get_session(session_id)
        system_msg = Message(role="system", content=request.content)
        # Replace existing system message if present, otherwise prepend
        if messages and messages[0].role == "system":
            messages[0] = system_msg
        else:
            messages.insert(0, system_msg)
        return {"success": True}

    return app


app = create_context_app()
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-context && uv run pytest tests/test_app.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd services/svc-context && git add src/svc_context/app.py tests/test_app.py && git commit -m "feat(svc-context): session-keyed endpoints and system-prompt factory"
```

---

### Task 5: svc-context — Update orchestrator's context URL paths

**Files:**
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`

The orchestrator calls `/context/messages` and `/context/clear`. These need to become session-keyed: `/context/{session_id}/messages`. The orchestrator already has `session_id` available.

**Step 1: Update context helper methods**

In `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`, update the two context helper methods:

Replace the `_context_add_message` method (around line 411-415):

```python
    async def _context_add_message(
        self, context_app_id: str, message: dict[str, Any], session_id: str = ""
    ) -> None:
        """POST a single message to the context service."""
        await self._dapr.invoke(
            context_app_id, f"context/{session_id}/messages", message
        )
```

Replace the `_context_get_messages` method (around line 417-421):

```python
    async def _context_get_messages(
        self, context_app_id: str, session_id: str = ""
    ) -> list[dict[str, Any]]:
        """GET the current message list from the context service."""
        result = await self._dapr.invoke_get(
            context_app_id, f"context/{session_id}/messages"
        )
        msgs: list[dict[str, Any]] = result.get("messages", [])
        return msgs
```

Then update all call sites in `execute()` and `execute_stream()` to pass `session_id`:

In `execute()`:
- `await self._context_add_message(context_app_id, msg.model_dump())` → `await self._context_add_message(context_app_id, msg.model_dump(), session_id)`
- `await self._context_add_message(context_app_id, assistant_msg.model_dump())` → `await self._context_add_message(context_app_id, assistant_msg.model_dump(), session_id)`
- `await self._context_add_message(context_app_id, tool_msg.model_dump())` → `await self._context_add_message(context_app_id, tool_msg.model_dump(), session_id)`
- `context_msgs = await self._context_get_messages(context_app_id)` → `context_msgs = await self._context_get_messages(context_app_id, session_id)`
- `final_msgs = await self._context_get_messages(context_app_id)` → `final_msgs = await self._context_get_messages(context_app_id, session_id)`

Apply the same changes in `execute_stream()`.

**Step 2: Run orchestrator tests**

```bash
cd services/svc-orchestrator && uv run pytest tests/test_orchestrator.py -v
```
Expected: Tests pass. The orchestrator tests mock `dapr.invoke` and `dapr.invoke_get` at the DaprClient level, so the URL change is transparent. If any tests fail because they assert on the exact method path, update those assertions to include `context/{session_id}/messages`.

**Step 3: Commit**

```bash
cd services/svc-orchestrator && git add src/svc_orchestrator/orchestrator.py && git commit -m "feat(svc-orchestrator): pass session_id in context service URL paths"
```

---

### Task 6: svc-context — 7-level compaction tests

**Files:**
- Test: `services/svc-context/tests/test_compaction.py` (CREATE)

**Step 1: Write compaction tests**

Create `services/svc-context/tests/test_compaction.py`:

```python
"""Tests for 7-level compaction with paired tool-call/result removal."""

from __future__ import annotations

from amplifier_service_sdk.models import Message, ToolCall

from svc_context.context_manager import (
    SimpleContextManager,
    _compact,
    _total_tokens,
    format_compaction_notice,
)


def _make_tool_pair(call_id: str, content: str = "result") -> tuple[Message, Message]:
    """Create an assistant-with-tool-call + tool-result pair."""
    assistant = Message(
        role="assistant",
        content=None,
        tool_calls=[ToolCall(id=call_id, name="test_tool", arguments={"q": "x"})],
    )
    tool_result = Message(
        role="tool", content=content, tool_call_id=call_id, name="test_tool"
    )
    return assistant, tool_result


class TestPairedToolCallRemoval:
    """Tests that tool-call and tool-result are always removed together."""

    async def test_tool_call_and_result_removed_together(self) -> None:
        """When compaction removes a tool result, its assistant tool-call is also removed."""
        cm = SimpleContextManager()
        cm.max_tokens = 200
        cm.compact_threshold = 0.50
        cm.target_usage = 0.20

        session = "pair-test"
        # System prompt
        await cm.add_message(session, Message(role="system", content="sys"))
        # Old tool pair (should get removed together)
        assistant, tool_result = _make_tool_pair("call-old", "x" * 400)
        await cm.add_message(session, assistant)
        await cm.add_message(session, tool_result)
        # Recent conversation (should survive)
        await cm.add_message(session, Message(role="user", content="recent question"))
        await cm.add_message(session, Message(role="assistant", content="recent answer"))

        messages = await cm.get_messages(session)

        # The old tool-call and tool-result should both be gone or both present
        tool_call_ids = set()
        tool_result_ids = set()
        for m in messages:
            if m.tool_calls:
                for tc in m.tool_calls:
                    tool_call_ids.add(tc.id)
            if m.tool_call_id:
                tool_result_ids.add(m.tool_call_id)

        # Either both "call-old" exist or neither exists — never orphaned
        has_call = "call-old" in tool_call_ids
        has_result = "call-old" in tool_result_ids
        assert has_call == has_result, (
            f"Tool pair must be removed together: call={has_call}, result={has_result}"
        )

    async def test_no_orphaned_tool_results_after_compaction(self) -> None:
        """After compaction, every tool_call_id in results has a matching tool_call."""
        cm = SimpleContextManager()
        cm.max_tokens = 400
        cm.compact_threshold = 0.50
        cm.target_usage = 0.25

        session = "orphan-test"
        await cm.add_message(session, Message(role="system", content="sys"))

        # Create 5 tool pairs
        for i in range(5):
            a, t = _make_tool_pair(f"call-{i}", f"result content {'x' * 200}")
            await cm.add_message(session, a)
            await cm.add_message(session, t)

        await cm.add_message(session, Message(role="user", content="final"))
        await cm.add_message(session, Message(role="assistant", content="done"))

        messages = await cm.get_messages(session)

        # Collect all tool_call ids from assistant messages
        available_call_ids = set()
        for m in messages:
            if m.tool_calls:
                for tc in m.tool_calls:
                    available_call_ids.add(tc.id)

        # Every tool result must have its call present
        for m in messages:
            if m.tool_call_id:
                assert m.tool_call_id in available_call_ids, (
                    f"Orphaned tool result: {m.tool_call_id} has no matching tool call"
                )


class TestCompactionLevels:
    """Tests for progressive compaction level behavior."""

    async def test_level1_truncates_tool_results(self) -> None:
        """Level 1 truncates the oldest tool results without removing messages."""
        messages = [
            Message(role="system", content="sys"),
            Message(role="tool", content="x" * 10000, tool_call_id="c1"),
            Message(role="user", content="q"),
            Message(role="assistant", content="a"),
        ]
        # Budget tight enough to trigger L1 truncation but not removal
        compacted, stats = _compact(
            messages,
            target_tokens=500,
            protected_recent=0.30,
            protected_tool_results=0,
            truncate_chars=100,
        )

        assert stats["strategy_level"] >= 1
        # The tool result should be truncated
        tool_msgs = [m for m in compacted if m.role == "tool"]
        if tool_msgs:
            assert len(str(tool_msgs[0].content)) < 10000

    async def test_system_messages_never_compacted(self) -> None:
        """System messages survive all compaction levels."""
        cm = SimpleContextManager()
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.10

        session = "sys-test"
        await cm.add_message(session, Message(role="system", content="You are helpful."))
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(session, Message(role=role, content="x" * 200))

        messages = await cm.get_messages(session)
        # Filter out compaction notice system messages
        real_system = [
            m for m in messages
            if m.role == "system"
            and not (m.metadata and m.metadata.get("source") == "context-compaction")
        ]
        assert len(real_system) >= 1
        assert real_system[0].content == "You are helpful."

    async def test_last_turn_always_preserved(self) -> None:
        """The most recent user + assistant turn survives even extreme compaction."""
        cm = SimpleContextManager()
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.05

        session = "last-turn"
        await cm.add_message(session, Message(role="system", content="sys"))
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(session, Message(role=role, content="x" * 200))
        await cm.add_message(session, Message(role="user", content="FINAL_USER"))
        await cm.add_message(session, Message(role="assistant", content="FINAL_ASST"))

        messages = await cm.get_messages(session)
        non_system = [m for m in messages if m.role != "system"]
        # The last two non-system messages should be the final pair
        assert non_system[-1].content == "FINAL_ASST"
        # FINAL_USER should be present somewhere
        user_contents = [m.content for m in non_system if m.role == "user"]
        assert any("FINAL_USER" in str(c) for c in user_contents)


class TestCompactionNotice:
    """Tests for compaction notice generation."""

    def test_notice_contains_level_and_actions(self) -> None:
        """format_compaction_notice includes level and description of removals."""
        stats = {
            "strategy_level": 3,
            "messages_removed": 5,
            "messages_truncated": 2,
            "user_messages_stubbed": 1,
        }
        notice = format_compaction_notice(stats)
        assert "context-compaction" in notice
        assert "level 3" in notice
        assert "5" in notice  # removed count
        assert "truncated" in notice

    async def test_compaction_notice_inserted_in_messages(self) -> None:
        """When compaction occurs, a system-reminder message is inserted."""
        cm = SimpleContextManager()
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.30

        session = "notice-test"
        await cm.add_message(session, Message(role="system", content="sys"))
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(session, Message(role=role, content="x" * 200))

        messages = await cm.get_messages(session)
        compaction_notices = [
            m for m in messages
            if m.role == "system"
            and m.metadata
            and m.metadata.get("source") == "context-compaction"
        ]
        assert len(compaction_notices) >= 1
        assert "context-compaction" in str(compaction_notices[0].content)


class TestEphemeralCompaction:
    """Tests that compaction never modifies stored messages."""

    async def test_get_messages_does_not_modify_stored(self) -> None:
        """Compaction in get_messages must NOT modify the session's stored messages."""
        cm = SimpleContextManager()
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.30

        session = "ephemeral"
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(session, Message(role=role, content="x" * 200))

        original_count = len(cm._sessions[session])
        compacted = await cm.get_messages(session)

        assert len(compacted) < original_count
        assert len(cm._sessions[session]) == original_count
```

**Step 2: Run compaction tests**

```bash
cd services/svc-context && uv run pytest tests/test_compaction.py -v
```
Expected: All tests PASS.

**Step 3: Commit**

```bash
cd services/svc-context && git add tests/test_compaction.py && git commit -m "test(svc-context): 7-level compaction with paired removal and notices"
```

---

## Phase 2b: Delegation & Orchestrator (Tasks 7–12)

### Task 7: svc-delegation — New tool schema (test)

**Files:**
- Modify: `services/svc-delegation/src/svc_delegation/tool.py`
- Modify: `services/svc-delegation/tests/test_tool.py`
- Modify: `services/svc-delegation/tests/test_app.py`

**Step 1: Write the failing test for new schema**

Add to `services/svc-delegation/tests/test_tool.py`, replacing the existing fixture and adding new test class:

```python
"""Tests for DelegateTool."""

from __future__ import annotations

import httpx
import pytest
from unittest.mock import AsyncMock

from svc_delegation.tool import DelegateTool


@pytest.fixture
def tool() -> DelegateTool:
    """Create a DelegateTool for testing."""
    return DelegateTool(
        orchestrator_base_url="http://orchestrator:8080",
        session_service_base_url="http://session-service:8080",
    )


class TestDelegateToolSchema:
    """Tests for the new delegate tool schema."""

    def test_schema_has_instruction_as_required(self, tool: DelegateTool) -> None:
        """input_schema requires 'instruction' (not 'prompt')."""
        assert "instruction" in tool.input_schema["required"]
        assert "prompt" not in tool.input_schema.get("required", [])

    def test_schema_has_all_new_properties(self, tool: DelegateTool) -> None:
        """input_schema declares all new parameters."""
        props = tool.input_schema["properties"]
        expected_keys = {
            "instruction", "agent", "session_id", "context_depth",
            "context_scope", "context_turns", "model_role",
            "provider_preferences",
        }
        assert expected_keys.issubset(props.keys())

    def test_context_depth_has_enum(self, tool: DelegateTool) -> None:
        """context_depth declares enum: none, recent, all."""
        cd = tool.input_schema["properties"]["context_depth"]
        assert set(cd["enum"]) == {"none", "recent", "all"}

    def test_context_scope_has_enum(self, tool: DelegateTool) -> None:
        """context_scope declares enum: conversation, agents, full."""
        cs = tool.input_schema["properties"]["context_scope"]
        assert set(cs["enum"]) == {"conversation", "agents", "full"}


class TestDelegateToolMissingInstruction:
    """Tests for missing instruction validation."""

    async def test_execute_missing_instruction_returns_error(
        self, tool: DelegateTool
    ) -> None:
        """execute() with no instruction returns error ToolResult."""
        result = await tool.execute({})
        assert result.success is False
        assert result.error is not None
        assert "instruction" in result.error["message"].lower()


class TestDelegateToolSuccess:
    """Tests for successful delegation scenarios."""

    async def test_execute_delegates_with_instruction(
        self, tool: DelegateTool
    ) -> None:
        """execute() calls _call_orchestrator with instruction in payload."""
        mock_response = {"session_id": "abc123", "result": "done"}
        tool._call_orchestrator = AsyncMock(return_value=mock_response)
        tool._fetch_parent_messages = AsyncMock(return_value=[])

        result = await tool.execute({"instruction": "do something"})

        assert result.success is True
        assert result.output is not None
        assert result.output["child_session_id"] == "abc123"

    async def test_execute_forwards_agent_parameter(
        self, tool: DelegateTool
    ) -> None:
        """execute() forwards agent parameter to orchestrator payload."""
        mock_response = {"session_id": "abc123", "result": "done"}
        tool._call_orchestrator = AsyncMock(return_value=mock_response)
        tool._fetch_parent_messages = AsyncMock(return_value=[])

        await tool.execute({
            "instruction": "explore code",
            "agent": "foundation:explorer",
        })

        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["agent_ref"] == "foundation:explorer"


class TestDelegateToolErrors:
    """Tests for orchestrator error handling."""

    async def test_execute_orchestrator_unreachable_returns_error(
        self, tool: DelegateTool
    ) -> None:
        """execute() returns error when orchestrator is unreachable."""
        tool._call_orchestrator = AsyncMock(
            side_effect=httpx.RequestError("Connection refused")
        )
        tool._fetch_parent_messages = AsyncMock(return_value=[])

        result = await tool.execute({"instruction": "hello"})

        assert result.success is False
        assert result.error is not None
        assert "unreachable" in result.error["message"].lower()

    async def test_execute_http_error_returns_error_with_status_code(
        self, tool: DelegateTool
    ) -> None:
        """execute() returns error containing HTTP status code on HTTPStatusError."""
        mock_request = httpx.Request(
            "POST", "http://orchestrator:8080/orchestrator/delegate"
        )
        mock_response = httpx.Response(500, request=mock_request)
        tool._call_orchestrator = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Server error", request=mock_request, response=mock_response
            )
        )
        tool._fetch_parent_messages = AsyncMock(return_value=[])

        result = await tool.execute({"instruction": "hello"})

        assert result.success is False
        assert result.error is not None
        assert "500" in result.error["message"]
```

Also update `services/svc-delegation/tests/test_app.py` — change the `test_describe_tool_has_prompt_in_required` test:

```python
    def test_describe_tool_has_instruction_in_required(self, client: TestClient) -> None:
        """GET /describe returns delegate tool schema with 'instruction' in required."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        delegate_tool = next(t for t in data["tools"] if t["name"] == "delegate")
        assert "instruction" in delegate_tool["input_schema"]["required"]
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-delegation && uv run pytest tests/ -v
```
Expected: FAIL — old schema uses "prompt", not "instruction".

**Step 3: Implement the new tool**

Replace `services/svc-delegation/src/svc_delegation/tool.py` with:

```python
"""DelegateTool — spawn child agent sessions via the orchestrator."""

from __future__ import annotations

from typing import Any

import httpx

from amplifier_service_sdk.models import ToolResult

MAX_DELEGATION_DEPTH = 10


class DelegateTool:
    """Tool that delegates work to a child agent session via the orchestrator."""

    name = "delegate"
    description = (
        "Delegate a task to a child agent session. Supports context inheritance "
        "from the parent session, session resumption, and agent selection."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": "Task for the child agent",
            },
            "agent": {
                "type": "string",
                "default": "self",
                "description": "Agent ref (e.g. 'foundation:explorer')",
            },
            "session_id": {
                "type": "string",
                "description": "Resume existing child session",
            },
            "context_depth": {
                "type": "string",
                "enum": ["none", "recent", "all"],
                "default": "recent",
            },
            "context_scope": {
                "type": "string",
                "enum": ["conversation", "agents", "full"],
                "default": "conversation",
            },
            "context_turns": {
                "type": "integer",
                "default": 5,
            },
            "model_role": {
                "type": "string",
                "description": "Override child model role",
            },
            "provider_preferences": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Provider/model fallback chain",
            },
        },
        "required": ["instruction"],
    }

    def __init__(
        self,
        orchestrator_base_url: str,
        session_service_base_url: str | None = None,
        parent_session_id: str = "",
        delegation_depth: int = 0,
    ) -> None:
        """Initialize the DelegateTool.

        Args:
            orchestrator_base_url: Base URL for the orchestrator service.
            session_service_base_url: Base URL for the session-service
                (for fetching parent transcript). Defaults to orchestrator URL's
                Dapr invoke prefix targeting session-service.
            parent_session_id: ID of the parent session (for context inheritance).
            delegation_depth: Current delegation depth (for recursion guard).
        """
        self._orchestrator_base_url = orchestrator_base_url
        self._session_service_base_url = session_service_base_url or ""
        self._parent_session_id = parent_session_id
        self._delegation_depth = delegation_depth

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a delegation request.

        Validates instruction, checks recursion depth, optionally fetches
        parent context, and calls the orchestrator's delegate endpoint.
        """
        instruction = input.get("instruction")
        if not instruction:
            return ToolResult(
                success=False,
                error={"message": "Missing required field: instruction"},
            )

        # Recursion guard
        if self._delegation_depth >= MAX_DELEGATION_DEPTH:
            return ToolResult(
                success=False,
                error={
                    "message": (
                        f"Maximum delegation depth ({MAX_DELEGATION_DEPTH}) reached. "
                        "Cannot spawn further child sessions."
                    )
                },
            )

        # Context inheritance: fetch parent messages if requested
        context_depth = input.get("context_depth", "recent")
        context_messages: list[dict[str, Any]] = []
        if context_depth != "none" and self._parent_session_id:
            try:
                parent_messages = await self._fetch_parent_messages(
                    self._parent_session_id
                )
                context_messages = self._filter_context(
                    parent_messages,
                    scope=input.get("context_scope", "conversation"),
                    depth=context_depth,
                    turns=input.get("context_turns", 5),
                )
            except Exception:
                pass  # best-effort — proceed without context

        # Build orchestrator payload
        agent_ref = input.get("agent", "self")
        if agent_ref == "self":
            agent_ref = "default"

        payload: dict[str, Any] = {
            "prompt": instruction,
            "agent_ref": agent_ref,
            "delegation_depth": self._delegation_depth + 1,
        }
        if input.get("session_id"):
            payload["child_session_id"] = input["session_id"]
        if context_messages:
            payload["context_messages"] = context_messages
        if input.get("model_role"):
            payload["model_role"] = input["model_role"]
        if input.get("provider_preferences"):
            payload["provider_preferences"] = input["provider_preferences"]

        try:
            result = await self._call_orchestrator(payload)
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error={
                    "message": f"Orchestrator returned HTTP {exc.response.status_code}"
                },
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Orchestrator unreachable"},
            )

        child_session_id = result.get("child_session_id", result.get("session_id", ""))
        return ToolResult(
            success=True,
            output={
                "child_session_id": child_session_id,
                "result": result,
            },
        )

    def _filter_context(
        self,
        messages: list[dict[str, Any]],
        scope: str,
        depth: str,
        turns: int,
    ) -> list[dict[str, Any]]:
        """Filter parent messages by scope and depth.

        scope: "conversation" keeps user/assistant text only,
               "agents" adds delegate results,
               "full" keeps everything.
        depth: "recent" takes last N turns, "all" takes everything.
        """
        if scope == "conversation":
            filtered = [
                m for m in messages if m.get("role") in ("user", "assistant")
            ]
        elif scope == "agents":
            filtered = [
                m for m in messages
                if m.get("role") in ("user", "assistant")
                or (m.get("role") == "tool" and m.get("name") == "delegate")
            ]
        else:  # "full"
            filtered = list(messages)

        # Remove system messages from inherited context
        filtered = [m for m in filtered if m.get("role") != "system"]

        if depth == "recent":
            # A "turn" is a user+assistant pair = 2 messages
            max_messages = turns * 2
            filtered = filtered[-max_messages:]

        return filtered

    async def _fetch_parent_messages(
        self, parent_session_id: str
    ) -> list[dict[str, Any]]:
        """Fetch the parent session's transcript from session-service."""
        url = f"{self._session_service_base_url}/sessions/{parent_session_id}/messages"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            return data.get("messages", [])

    async def _call_orchestrator(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST the delegation payload to the orchestrator."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._orchestrator_base_url}/orchestrator/delegate",
                json=payload,
                timeout=300.0,
            )
            response.raise_for_status()
            return response.json()
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-delegation && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Update app.py to wire new constructor params**

In `services/svc-delegation/src/svc_delegation/app.py`, update `create_delegation_app`:

```python
def create_delegation_app(
    orchestrator_base_url: str | None = None,
    session_service_base_url: str | None = None,
) -> FastAPI:
    """Create the svc-delegation FastAPI application."""
    if orchestrator_base_url is None:
        dapr_port = os.environ.get("DAPR_HTTP_PORT", "3500")
        orchestrator_base_url = (
            f"http://localhost:{dapr_port}/v1.0/invoke/svc-orchestrator/method"
        )

    if session_service_base_url is None:
        dapr_port = os.environ.get("DAPR_HTTP_PORT", "3500")
        session_service_base_url = (
            f"http://localhost:{dapr_port}/v1.0/invoke/session-service/method"
        )

    tool = DelegateTool(
        orchestrator_base_url=orchestrator_base_url,
        session_service_base_url=session_service_base_url,
    )

    config = ServiceConfig(
        name="svc-delegation",
        tools=[
            ToolCapability(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            ),
        ],
    )

    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/delegate/execute")
    async def execute_delegate(request: ToolRequest) -> dict[str, Any]:
        """Spawn a child agent session via the orchestrator."""
        result = await tool.execute(request.input)
        return result.model_dump()

    return fastapi_app


app = create_delegation_app()
```

Update the test fixture in `test_app.py`:

```python
    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the delegation app with a test orchestrator URL."""
        app = create_delegation_app(
            orchestrator_base_url="http://test-orchestrator:8080",
            session_service_base_url="http://test-session:8080",
        )
        return TestClient(app)
```

**Step 6: Run all tests again**

```bash
cd services/svc-delegation && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 7: Commit**

```bash
cd services/svc-delegation && git add src/svc_delegation/ tests/ && git commit -m "feat(svc-delegation): new tool schema with context inheritance and recursion guard"
```

---

### Task 8: svc-delegation — Context inheritance tests

**Files:**
- Modify: `services/svc-delegation/tests/test_tool.py`

**Step 1: Write context inheritance tests**

Add to `services/svc-delegation/tests/test_tool.py`:

```python
class TestContextInheritance:
    """Tests for context inheritance from parent session."""

    async def test_context_depth_none_sends_no_context(self) -> None:
        """When context_depth='none', no parent messages are fetched."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            parent_session_id="parent-1",
        )
        tool._call_orchestrator = AsyncMock(
            return_value={"session_id": "child-1", "result": "ok"}
        )
        tool._fetch_parent_messages = AsyncMock(return_value=[])

        await tool.execute({"instruction": "do it", "context_depth": "none"})

        # _fetch_parent_messages should NOT be called
        tool._fetch_parent_messages.assert_not_called()
        payload = tool._call_orchestrator.call_args[0][0]
        assert "context_messages" not in payload

    async def test_context_scope_conversation_filters_to_user_assistant(self) -> None:
        """context_scope='conversation' keeps only user/assistant messages."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            parent_session_id="parent-1",
        )
        parent_messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "tool", "content": "result", "tool_call_id": "c1", "name": "bash"},
        ]
        tool._fetch_parent_messages = AsyncMock(return_value=parent_messages)
        tool._call_orchestrator = AsyncMock(
            return_value={"session_id": "child-1", "result": "ok"}
        )

        await tool.execute({
            "instruction": "continue",
            "context_depth": "all",
            "context_scope": "conversation",
        })

        payload = tool._call_orchestrator.call_args[0][0]
        ctx = payload["context_messages"]
        roles = [m["role"] for m in ctx]
        assert "system" not in roles
        assert "tool" not in roles
        assert "user" in roles
        assert "assistant" in roles

    async def test_context_depth_recent_limits_turns(self) -> None:
        """context_depth='recent' with context_turns=2 keeps only last 4 messages."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            parent_session_id="parent-1",
        )
        parent_messages = [
            {"role": "user", "content": f"msg-{i}"}
            if i % 2 == 0
            else {"role": "assistant", "content": f"reply-{i}"}
            for i in range(10)
        ]
        tool._fetch_parent_messages = AsyncMock(return_value=parent_messages)
        tool._call_orchestrator = AsyncMock(
            return_value={"session_id": "child-1", "result": "ok"}
        )

        await tool.execute({
            "instruction": "continue",
            "context_depth": "recent",
            "context_turns": 2,
        })

        payload = tool._call_orchestrator.call_args[0][0]
        ctx = payload["context_messages"]
        assert len(ctx) == 4  # 2 turns * 2 messages per turn

    async def test_context_scope_full_keeps_everything(self) -> None:
        """context_scope='full' keeps all non-system messages."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            parent_session_id="parent-1",
        )
        parent_messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "tool", "content": "r", "tool_call_id": "c1", "name": "bash"},
        ]
        tool._fetch_parent_messages = AsyncMock(return_value=parent_messages)
        tool._call_orchestrator = AsyncMock(
            return_value={"session_id": "child-1", "result": "ok"}
        )

        await tool.execute({
            "instruction": "continue",
            "context_depth": "all",
            "context_scope": "full",
        })

        payload = tool._call_orchestrator.call_args[0][0]
        ctx = payload["context_messages"]
        # Should have user, assistant, tool — but not system
        roles = [m["role"] for m in ctx]
        assert "system" not in roles
        assert len(ctx) == 3
```

**Step 2: Run tests**

```bash
cd services/svc-delegation && uv run pytest tests/test_tool.py::TestContextInheritance -v
```
Expected: All 4 tests PASS (implementation already done in Task 7).

**Step 3: Commit**

```bash
cd services/svc-delegation && git add tests/test_tool.py && git commit -m "test(svc-delegation): context inheritance tests for scope and depth filtering"
```

---

### Task 9: svc-delegation — Recursion guard and session resumption tests

**Files:**
- Modify: `services/svc-delegation/tests/test_tool.py`

**Step 1: Write recursion guard and session resumption tests**

Add to `services/svc-delegation/tests/test_tool.py`:

```python
class TestRecursionGuard:
    """Tests for delegation depth recursion guard."""

    async def test_depth_at_max_returns_error(self) -> None:
        """execute() returns error when delegation_depth >= MAX_DELEGATION_DEPTH."""
        from svc_delegation.tool import MAX_DELEGATION_DEPTH

        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            delegation_depth=MAX_DELEGATION_DEPTH,
        )

        result = await tool.execute({"instruction": "do something"})

        assert result.success is False
        assert "maximum delegation depth" in result.error["message"].lower()

    async def test_depth_below_max_succeeds(self) -> None:
        """execute() succeeds when delegation_depth is below MAX_DELEGATION_DEPTH."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            delegation_depth=5,
        )
        tool._call_orchestrator = AsyncMock(
            return_value={"session_id": "ok", "result": "done"}
        )
        tool._fetch_parent_messages = AsyncMock(return_value=[])

        result = await tool.execute({"instruction": "do something"})

        assert result.success is True

    async def test_depth_incremented_in_payload(self) -> None:
        """execute() sends delegation_depth + 1 in the orchestrator payload."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            delegation_depth=3,
        )
        tool._call_orchestrator = AsyncMock(
            return_value={"session_id": "ok", "result": "done"}
        )
        tool._fetch_parent_messages = AsyncMock(return_value=[])

        await tool.execute({"instruction": "task"})

        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["delegation_depth"] == 4


class TestSessionResumption:
    """Tests for resuming existing child sessions."""

    async def test_session_id_forwarded_as_child_session_id(self) -> None:
        """When session_id is provided, it's forwarded as child_session_id."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
        )
        tool._call_orchestrator = AsyncMock(
            return_value={"session_id": "existing-child", "result": "resumed"}
        )
        tool._fetch_parent_messages = AsyncMock(return_value=[])

        await tool.execute({
            "instruction": "continue where you left off",
            "session_id": "existing-child",
        })

        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["child_session_id"] == "existing-child"

    async def test_no_session_id_means_new_session(self) -> None:
        """When session_id is not provided, child_session_id is not in payload."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
        )
        tool._call_orchestrator = AsyncMock(
            return_value={"session_id": "new-child", "result": "done"}
        )
        tool._fetch_parent_messages = AsyncMock(return_value=[])

        await tool.execute({"instruction": "new task"})

        payload = tool._call_orchestrator.call_args[0][0]
        assert "child_session_id" not in payload
```

**Step 2: Run tests**

```bash
cd services/svc-delegation && uv run pytest tests/test_tool.py -v
```
Expected: All tests PASS.

**Step 3: Commit**

```bash
cd services/svc-delegation && git add tests/test_tool.py && git commit -m "test(svc-delegation): recursion guard and session resumption tests"
```

---

### Task 10: svc-orchestrator — Accept enriched delegation params

**Files:**
- Modify: `services/svc-orchestrator/src/svc_orchestrator/app.py`
- Modify: `services/svc-orchestrator/src/svc_orchestrator/child_session.py`
- Modify: `services/svc-orchestrator/tests/test_child_session.py`

**Step 1: Write the failing test**

Add to `services/svc-orchestrator/tests/test_child_session.py`:

```python
class TestEnrichedDelegation:
    """Tests for enriched delegation parameters."""

    @pytest.mark.asyncio
    async def test_spawn_forwards_delegation_depth(self) -> None:
        """spawn() forwards delegation_depth in the payload."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "ok", "messages": []}

        spawner = ChildSessionSpawner(dapr=dapr)
        request = ChildSessionRequest(
            prompt="hello",
            child_session_id="test-child",
            delegation_depth=3,
        )

        await spawner.spawn(request)

        call_args = dapr.invoke.call_args
        payload: dict = call_args[0][2]
        assert payload["delegation_depth"] == 3

    @pytest.mark.asyncio
    async def test_spawn_forwards_agent_ref(self) -> None:
        """spawn() forwards agent_ref in the payload."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "ok", "messages": []}

        spawner = ChildSessionSpawner(dapr=dapr)
        request = ChildSessionRequest(
            prompt="explore",
            child_session_id="child-1",
            agent_ref="foundation:explorer",
        )

        await spawner.spawn(request)

        call_args = dapr.invoke.call_args
        payload: dict = call_args[0][2]
        assert payload["agent_ref"] == "foundation:explorer"

    @pytest.mark.asyncio
    async def test_spawn_forwards_context_messages(self) -> None:
        """spawn() forwards context_messages in the payload when provided."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"result": "ok", "messages": []}

        spawner = ChildSessionSpawner(dapr=dapr)
        ctx = [{"role": "user", "content": "hello"}]
        request = ChildSessionRequest(
            prompt="continue",
            child_session_id="child-ctx",
            context_messages=ctx,
        )

        await spawner.spawn(request)

        call_args = dapr.invoke.call_args
        payload: dict = call_args[0][2]
        assert payload["context_messages"] == ctx
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-orchestrator && uv run pytest tests/test_child_session.py::TestEnrichedDelegation -v
```
Expected: FAIL — `ChildSessionRequest` doesn't have `delegation_depth` or `context_messages` fields yet.

**Step 3: Update ChildSessionRequest and ChildSessionSpawner**

In `services/svc-orchestrator/src/svc_orchestrator/child_session.py`, update:

```python
class ChildSessionRequest(BaseModel):
    """Request model for spawning a child session."""

    prompt: str
    child_session_id: str = ""
    provider_name: str = "mock"
    services: list[str] = Field(default_factory=list)
    workspace_content: dict[str, str] = Field(default_factory=dict)
    agent_ref: str = "default"
    delegation_depth: int = 0
    context_messages: list[dict[str, Any]] = Field(default_factory=list)
    model_role: str = ""
```

Add `from typing import Any` to the imports (it's already imported).

Update the `spawn` method's payload construction:

```python
    async def spawn(self, request: ChildSessionRequest) -> dict[str, Any]:
        """Spawn a child session by invoking the session-service."""
        session_id = request.child_session_id or str(uuid4())[:8]

        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "provider_name": request.provider_name,
            "services": request.services,
            "workspace_content": request.workspace_content,
            "agent_ref": request.agent_ref,
            "delegation_depth": request.delegation_depth,
        }
        if request.context_messages:
            payload["context_messages"] = request.context_messages
        if request.model_role:
            payload["model_role"] = request.model_role

        result: dict[str, Any] = await self._dapr.invoke(
            self._session_service_app_id,
            f"sessions/{session_id}/turn",
            payload,
            timeout=300.0,
        )
        return {"session_id": session_id, **result}
```

**Step 4: Update DelegateRequest in orchestrator app.py**

In `services/svc-orchestrator/src/svc_orchestrator/app.py`, update `DelegateRequest`:

```python
class DelegateRequest(BaseModel):
    """Request model for POST /orchestrator/delegate."""

    prompt: str
    child_session_id: str = ""
    provider_name: str = "mock"
    services: list[str] = Field(default_factory=list)
    workspace_content: dict[str, str] = Field(default_factory=dict)
    agent_ref: str = "default"
    delegation_depth: int = 0
    context_messages: list[dict[str, Any]] = Field(default_factory=list)
    model_role: str = ""
```

Add `from typing import Any` to imports if not already present (it is).

Update the `delegate` endpoint to forward new fields:

```python
    @app.post("/orchestrator/delegate")
    async def delegate(request: DelegateRequest) -> dict[str, Any]:
        """Spawn a child session via the session-service."""
        child_request = ChildSessionRequest(
            prompt=request.prompt,
            child_session_id=request.child_session_id,
            provider_name=request.provider_name,
            services=request.services,
            workspace_content=request.workspace_content,
            agent_ref=request.agent_ref,
            delegation_depth=request.delegation_depth,
            context_messages=request.context_messages,
            model_role=request.model_role,
        )
        result = await spawner.spawn(child_request)
        session_id = result.get("session_id", child_request.child_session_id)
        return DelegateResponse(
            child_session_id=session_id,
            result=result,
            messages=result.get("messages", []),
        ).model_dump()
```

**Step 5: Run tests to verify they pass**

```bash
cd services/svc-orchestrator && uv run pytest tests/test_child_session.py -v
```
Expected: All tests PASS (both old and new).

**Step 6: Commit**

```bash
cd services/svc-orchestrator && git add src/svc_orchestrator/child_session.py src/svc_orchestrator/app.py tests/test_child_session.py && git commit -m "feat(svc-orchestrator): accept enriched delegation params (depth, context, model_role)"
```

---

### Task 11: Run all service test suites

This task verifies everything works together across all four services.

**Step 1: Run session-service tests**

```bash
cd services/session-service && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 2: Run svc-context tests**

```bash
cd services/svc-context && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 3: Run svc-delegation tests**

```bash
cd services/svc-delegation && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 4: Run svc-orchestrator tests**

```bash
cd services/svc-orchestrator && uv run pytest tests/ -v
```
Expected: All tests PASS. Note: orchestrator tests that mock `dapr.invoke` with exact path `"context/messages"` will need to be updated to match the new `"context/{session_id}/messages"` pattern. Fix any such failures by updating the mock assertions.

**Step 5: Fix any cross-service test failures**

If orchestrator tests fail because they assert on the old `context/messages` path, update those assertions. The mock will be called with the new path like `context/test-session/messages`. Check `services/svc-orchestrator/tests/test_orchestrator.py` for calls that verify the method parameter of `dapr.invoke` and `dapr.invoke_get`.

**Step 6: Commit any fixes**

```bash
git add services/ && git commit -m "fix: update cross-service test assertions for session-keyed context paths"
```

---

### Task 12: Integration verification — delegation end-to-end path

**Files:**
- Test: `services/svc-delegation/tests/test_integration.py` (CREATE)

**Step 1: Write end-to-end integration test**

Create `services/svc-delegation/tests/test_integration.py`:

```python
"""Integration test — verifies the delegation end-to-end path with mocked Dapr calls."""

from __future__ import annotations

from unittest.mock import AsyncMock

from svc_delegation.tool import DelegateTool


class TestDelegationEndToEnd:
    """End-to-end delegation flow with mocked external services."""

    async def test_full_delegation_with_context_inheritance(self) -> None:
        """Full flow: fetch parent context → filter → delegate to child → return result."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            parent_session_id="parent-session",
            delegation_depth=1,
        )

        # Mock parent transcript
        parent_transcript = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
            {"role": "user", "content": "Show me an example."},
            {"role": "assistant", "content": "Here is print('hello')."},
            {"role": "user", "content": "Now explain decorators."},
            {"role": "assistant", "content": "Decorators wrap functions."},
        ]
        tool._fetch_parent_messages = AsyncMock(return_value=parent_transcript)

        # Mock orchestrator response
        tool._call_orchestrator = AsyncMock(
            return_value={
                "session_id": "child-abc",
                "result": "Decorators are explained.",
                "messages": [],
            }
        )

        result = await tool.execute({
            "instruction": "Explain Python decorators in depth",
            "agent": "foundation:explorer",
            "context_depth": "recent",
            "context_scope": "conversation",
            "context_turns": 2,
        })

        # Verify success
        assert result.success is True
        assert result.output["child_session_id"] == "child-abc"

        # Verify orchestrator was called with correct payload
        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["prompt"] == "Explain Python decorators in depth"
        assert payload["agent_ref"] == "foundation:explorer"
        assert payload["delegation_depth"] == 2  # parent was 1, child is 2

        # Verify context was filtered correctly:
        # context_turns=2 means last 4 messages (2 user+assistant pairs)
        # context_scope=conversation means only user/assistant, no system
        ctx = payload["context_messages"]
        assert len(ctx) == 4
        assert all(m["role"] in ("user", "assistant") for m in ctx)
        # Should be the last 2 turns from the parent
        assert ctx[0]["content"] == "Show me an example."
        assert ctx[1]["content"] == "Here is print('hello')."
        assert ctx[2]["content"] == "Now explain decorators."
        assert ctx[3]["content"] == "Decorators wrap functions."

    async def test_recursion_guard_blocks_deep_delegation(self) -> None:
        """Delegation at max depth returns an error instead of spawning."""
        from svc_delegation.tool import MAX_DELEGATION_DEPTH

        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            parent_session_id="deep-parent",
            delegation_depth=MAX_DELEGATION_DEPTH,
        )

        result = await tool.execute({"instruction": "infinite recursion"})

        assert result.success is False
        assert "maximum delegation depth" in result.error["message"].lower()

    async def test_session_resumption_flow(self) -> None:
        """Resuming an existing child session forwards the session_id."""
        tool = DelegateTool(
            orchestrator_base_url="http://orch:8080",
            session_service_base_url="http://sess:8080",
            parent_session_id="parent-resume",
            delegation_depth=0,
        )
        tool._fetch_parent_messages = AsyncMock(return_value=[])
        tool._call_orchestrator = AsyncMock(
            return_value={
                "session_id": "existing-child",
                "result": "Resumed successfully.",
                "messages": [],
            }
        )

        result = await tool.execute({
            "instruction": "Continue the analysis",
            "session_id": "existing-child",
            "context_depth": "none",
        })

        assert result.success is True
        payload = tool._call_orchestrator.call_args[0][0]
        assert payload["child_session_id"] == "existing-child"
```

**Step 2: Run integration tests**

```bash
cd services/svc-delegation && uv run pytest tests/test_integration.py -v
```
Expected: All 3 tests PASS.

**Step 3: Commit**

```bash
cd services/svc-delegation && git add tests/test_integration.py && git commit -m "test(svc-delegation): end-to-end delegation path integration tests"
```

---

## Summary

| Task | Service | What | Files |
|------|---------|------|-------|
| 1 | session-service | GET /sessions/{id}/messages endpoint | app.py, test_messages.py |
| 2 | svc-context | Session-keyed context manager + 7-level compaction | context_manager.py, test_session_context.py |
| 3 | svc-context | Fix existing tests for new session-keyed API | test_context_manager.py |
| 4 | svc-context | Session-keyed app endpoints + system-prompt | app.py, test_app.py |
| 5 | svc-orchestrator | Update context URL paths to session-keyed | orchestrator.py |
| 6 | svc-context | 7-level compaction test suite | test_compaction.py |
| 7 | svc-delegation | New tool schema + full implementation | tool.py, app.py, test_tool.py, test_app.py |
| 8 | svc-delegation | Context inheritance tests | test_tool.py |
| 9 | svc-delegation | Recursion guard + session resumption tests | test_tool.py |
| 10 | svc-orchestrator | Accept enriched delegation params | child_session.py, app.py, test_child_session.py |
| 11 | all | Cross-service test verification | all test files |
| 12 | svc-delegation | End-to-end integration tests | test_integration.py |