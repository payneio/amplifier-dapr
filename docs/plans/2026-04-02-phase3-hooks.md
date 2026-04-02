# Phase 3: Hook Services — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Enrich existing hook services (approval, routing) to feature parity and create 3 new hook services (redaction, status-context, todo-reminder). Also implement svc-todo Dapr state persistence, todo hooks, and svc-skills visibility hook.

**Architecture:** Existing sync hook services follow a pattern: a `hook.py` class with `name`, `events`, `priority`, `mode` class-level attributes and an `async handle(event, data) -> HookResult` method, wired via FastAPI app factory in `app.py`. New services replicate this structure end-to-end, each in its own `services/svc-hooks-{name}/` directory. The svc-todo tool gains Dapr state store persistence so hooks in other services can read todo state. The routing hook gains real `resolve(model_role)` logic using the routing matrix YAML.

**Tech Stack:** Python 3.12, FastAPI, pytest + pytest-asyncio, amplifier-service-sdk (HookResult, HookEvent, HookRegistration, ServiceConfig, create_app), Dapr state store for cross-service state, YAML for routing matrix, httpx for service invocation.

**Design doc:** `docs/plans/2026-04-02-service-implementation-parity-design.md` — Sections 1.3, 1.5 (svc-todo), and Slice 3.

---

## Phase 3A: Enrich Existing Services (Tasks 1–8)

### Task 1: Approval Hook — Allow-list and argument inspection

**Files:**
- Modify: `services/svc-hooks-approval/src/svc_hooks_approval/hook.py`
- Modify: `services/svc-hooks-approval/tests/test_hook.py`

**Step 1: Write failing tests for allow-list, argument inspection, risk metadata, and structured denial**

Replace the entire contents of `services/svc-hooks-approval/tests/test_hook.py` with:

```python
"""Tests for ApprovalHook — allow-list, deny-list, argument inspection, risk metadata."""

import pytest
from svc_hooks_approval.hook import ApprovalHook


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def hook_no_rules():
    """ApprovalHook with no allow/deny rules."""
    return ApprovalHook(config={})


@pytest.fixture
def hook_deny_bash():
    """ApprovalHook with 'bash' in deny list."""
    return ApprovalHook(config={"deny_tools": ["bash"]})


@pytest.fixture
def hook_allow_only():
    """ApprovalHook that only allows web_search and read_file."""
    return ApprovalHook(config={"allow_tools": ["web_search", "read_file"]})


@pytest.fixture
def hook_both():
    """ApprovalHook with allow-list and deny-list."""
    return ApprovalHook(config={
        "allow_tools": ["bash", "web_search"],
        "deny_tools": ["bash"],
    })


# ---------------------------------------------------------------------------
# Existing behavior (preserved)
# ---------------------------------------------------------------------------

class TestBasicDenyList:
    async def test_unknown_event_continues(self, hook_no_rules):
        result = await hook_no_rules.handle("some:event", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    async def test_tool_pre_approved_by_default(self, hook_no_rules):
        result = await hook_no_rules.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    async def test_tool_pre_denied_by_rule(self, hook_deny_bash):
        result = await hook_deny_bash.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "DENY"
        assert result.reason is not None
        assert "bash" in result.reason

    async def test_glob_pattern_deny(self):
        hook = ApprovalHook(config={"deny_tools": ["bash*"]})
        result = await hook.handle("tool:pre", {"tool_name": "bash_exec"})
        assert result.action == "DENY"

    async def test_safe_tool_continues_with_deny_rules(self, hook_deny_bash):
        result = await hook_deny_bash.handle("tool:pre", {"tool_name": "web_search"})
        assert result.action == "CONTINUE"

    async def test_missing_tool_name_continues(self, hook_deny_bash):
        result = await hook_deny_bash.handle("tool:pre", {})
        assert result.action == "CONTINUE"


# ---------------------------------------------------------------------------
# NEW: Allow-list mode
# ---------------------------------------------------------------------------

class TestAllowList:
    async def test_allowed_tool_continues(self, hook_allow_only):
        result = await hook_allow_only.handle("tool:pre", {"tool_name": "web_search"})
        assert result.action == "CONTINUE"

    async def test_unlisted_tool_denied(self, hook_allow_only):
        result = await hook_allow_only.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "DENY"
        assert "not in allow-list" in result.reason

    async def test_deny_takes_precedence_over_allow(self, hook_both):
        """If a tool is in both allow and deny lists, deny wins."""
        result = await hook_both.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "DENY"

    async def test_allow_glob_pattern(self):
        hook = ApprovalHook(config={"allow_tools": ["web_*"]})
        result = await hook.handle("tool:pre", {"tool_name": "web_fetch"})
        assert result.action == "CONTINUE"


# ---------------------------------------------------------------------------
# NEW: Argument inspection for bash commands
# ---------------------------------------------------------------------------

class TestArgumentInspection:
    async def test_dangerous_rm_rf_denied(self, hook_no_rules):
        data = {"tool_name": "bash", "input": {"command": "rm -rf /"}}
        result = await hook_no_rules.handle("tool:pre", data)
        assert result.action == "DENY"
        assert "dangerous" in result.reason.lower() or "blocked" in result.reason.lower()

    async def test_sudo_rm_denied(self, hook_no_rules):
        data = {"tool_name": "bash", "input": {"command": "sudo rm -rf /var"}}
        result = await hook_no_rules.handle("tool:pre", data)
        assert result.action == "DENY"

    async def test_mkfs_denied(self, hook_no_rules):
        data = {"tool_name": "bash", "input": {"command": "mkfs.ext4 /dev/sda1"}}
        result = await hook_no_rules.handle("tool:pre", data)
        assert result.action == "DENY"

    async def test_safe_bash_command_continues(self, hook_no_rules):
        data = {"tool_name": "bash", "input": {"command": "ls -la"}}
        result = await hook_no_rules.handle("tool:pre", data)
        assert result.action == "CONTINUE"

    async def test_dd_of_dev_denied(self, hook_no_rules):
        data = {"tool_name": "bash", "input": {"command": "dd if=/dev/zero of=/dev/sda"}}
        result = await hook_no_rules.handle("tool:pre", data)
        assert result.action == "DENY"

    async def test_non_bash_tool_skips_inspection(self, hook_no_rules):
        """Argument inspection only applies to bash tool."""
        data = {"tool_name": "web_search", "input": {"command": "rm -rf /"}}
        result = await hook_no_rules.handle("tool:pre", data)
        assert result.action == "CONTINUE"


# ---------------------------------------------------------------------------
# NEW: Risk metadata
# ---------------------------------------------------------------------------

class TestRiskMetadata:
    async def test_requires_approval_triggers_deny(self, hook_no_rules):
        data = {
            "tool_name": "bash",
            "metadata": {"requires_approval": True, "risk_level": "high"},
            "input": {"command": "echo hello"},
        }
        result = await hook_no_rules.handle("tool:pre", data)
        assert result.action == "DENY"
        assert "approval" in result.reason.lower() or "risk" in result.reason.lower()

    async def test_no_approval_metadata_continues(self, hook_no_rules):
        data = {
            "tool_name": "bash",
            "metadata": {"requires_approval": False},
            "input": {"command": "echo hello"},
        }
        result = await hook_no_rules.handle("tool:pre", data)
        assert result.action == "CONTINUE"
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-hooks-approval && uv run pytest tests/test_hook.py -v
```

Expected: Multiple FAIL (TestAllowList, TestArgumentInspection, TestRiskMetadata classes fail).

**Step 3: Implement the enriched ApprovalHook**

Replace the entire contents of `services/svc-hooks-approval/src/svc_hooks_approval/hook.py` with:

```python
"""Approval pre-hook: allow-list, deny-list, argument inspection, risk metadata."""

from __future__ import annotations

import fnmatch
import re
from typing import Any, Literal

from amplifier_service_sdk.models import HookResult

# Dangerous bash command patterns (compiled once at import time)
_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-\w*r\w*f\w*|-\w*f\w*r\w*)\s+/\s*$"), "rm -rf /"),
    (re.compile(r"\bsudo\s+rm\b"), "sudo rm"),
    (re.compile(r"\bmkfs\b"), "mkfs"),
    (re.compile(r"\bdd\b.*\bof=/dev/"), "dd to device"),
    (re.compile(r"\bchmod\s+-R\s+777\s+/\s*$"), "chmod 777 /"),
    (re.compile(r":\(\)\s*\{\s*:\|:&\s*\}"), "fork bomb"),
    (re.compile(r">\s*/dev/sd[a-z]"), "write to raw device"),
]


def _matches_any(name: str, patterns: list[str]) -> bool:
    """Return True if *name* matches any glob pattern in *patterns*."""
    return any(fnmatch.fnmatch(name, p) for p in patterns)


class ApprovalHook:
    """Sync pre-hook that enforces tool approval policy.

    Supports:
    - deny_tools: glob patterns — matching tools are always denied
    - allow_tools: glob patterns — if set, ONLY matching tools are allowed
    - Argument inspection for bash tool (dangerous command patterns)
    - Risk metadata (requires_approval / risk_level on tool call data)
    """

    name: str = "approval"
    events: list[str] = ["tool:pre"]
    priority: int = 5
    mode: Literal["sync", "async"] = "sync"

    def __init__(self, config: dict[str, Any]) -> None:
        self.deny_tools: list[str] = config.get("deny_tools", [])
        self.allow_tools: list[str] = config.get("allow_tools", [])

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Evaluate a hook event and return CONTINUE or DENY."""
        if event != "tool:pre":
            return HookResult(action="CONTINUE")

        tool_name: str = data.get("tool_name", "")
        if not tool_name:
            return HookResult(action="CONTINUE")

        # 1. Deny-list check (highest priority)
        if self.deny_tools and _matches_any(tool_name, self.deny_tools):
            return HookResult(
                action="DENY",
                reason=f"Tool '{tool_name}' is denied by deny-list pattern",
            )

        # 2. Allow-list check (if configured, unlisted tools are denied)
        if self.allow_tools and not _matches_any(tool_name, self.allow_tools):
            return HookResult(
                action="DENY",
                reason=f"Tool '{tool_name}' is not in allow-list",
            )

        # 3. Risk metadata check
        metadata = data.get("metadata", {})
        if isinstance(metadata, dict) and metadata.get("requires_approval"):
            risk_level = metadata.get("risk_level", "unknown")
            return HookResult(
                action="DENY",
                reason=f"Tool '{tool_name}' requires approval (risk_level={risk_level})",
            )

        # 4. Argument inspection (bash tool only)
        if tool_name == "bash":
            input_data = data.get("input", {})
            command = input_data.get("command", "") if isinstance(input_data, dict) else ""
            if command:
                for pattern, description in _DANGEROUS_PATTERNS:
                    if pattern.search(command):
                        return HookResult(
                            action="DENY",
                            reason=f"Blocked dangerous command pattern: {description}",
                        )

        return HookResult(action="CONTINUE")
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-hooks-approval && uv run pytest tests/test_hook.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-hooks-approval/src/svc_hooks_approval/hook.py services/svc-hooks-approval/tests/test_hook.py && git commit -m "feat(hooks-approval): add allow-list, argument inspection, risk metadata"
```

---

### Task 2: Routing Hook — Real resolve(model_role) logic

**Files:**
- Modify: `services/svc-hooks-routing/src/svc_hooks_routing/hook.py`
- Modify: `services/svc-hooks-routing/tests/test_hook.py`

**Step 1: Write failing tests for resolve(model_role)**

Replace the entire contents of `services/svc-hooks-routing/tests/test_hook.py` with:

```python
"""Tests for RoutingHook — resolve(model_role) and context injection."""

import pytest
from svc_hooks_routing.hook import RoutingHook


SAMPLE_MATRIX = {
    "name": "balanced",
    "roles": {
        "general": {
            "description": "General purpose tasks",
            "candidates": [
                {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                {"provider": "openai", "model": "gpt-5.4"},
            ],
        },
        "fast": {
            "description": "Quick utility tasks",
            "candidates": [
                {"provider": "anthropic", "model": "claude-haiku-4-5"},
                {"provider": "openai", "model": "gpt-5-mini"},
            ],
        },
    },
}


@pytest.fixture
def hook_no_matrix():
    return RoutingHook(matrix={})


@pytest.fixture
def hook_with_matrix():
    return RoutingHook(matrix=SAMPLE_MATRIX)


# ---------------------------------------------------------------------------
# Existing behavior (preserved)
# ---------------------------------------------------------------------------

class TestBasicBehavior:
    async def test_unknown_event_continues(self, hook_no_matrix):
        result = await hook_no_matrix.handle("some:event", {})
        assert result.action == "CONTINUE"

    async def test_provider_request_no_matrix_continues(self, hook_no_matrix):
        result = await hook_no_matrix.handle("provider:request", {})
        assert result.action == "CONTINUE"

    async def test_session_start_continues(self, hook_with_matrix):
        result = await hook_with_matrix.handle("session:start", {})
        assert result.action == "CONTINUE"

    async def test_provider_request_no_role_injects_context(self, hook_with_matrix):
        """When no model_role is set, inject the matrix overview context."""
        result = await hook_with_matrix.handle("provider:request", {})
        assert result.action == "INJECT_CONTEXT"
        assert "general" in result.data["context_injection"]
        assert "fast" in result.data["context_injection"]


# ---------------------------------------------------------------------------
# NEW: resolve(model_role) logic
# ---------------------------------------------------------------------------

class TestResolveModelRole:
    async def test_resolve_known_role_modifies_request(self, hook_with_matrix):
        """When model_role is set, resolve it and return MODIFY with provider/model."""
        data = {"model_role": "fast"}
        result = await hook_with_matrix.handle("provider:request", data)
        assert result.action == "MODIFY"
        assert result.data["provider"] == "anthropic"
        assert result.data["model"] == "claude-haiku-4-5"

    async def test_resolve_general_role(self, hook_with_matrix):
        data = {"model_role": "general"}
        result = await hook_with_matrix.handle("provider:request", data)
        assert result.action == "MODIFY"
        assert result.data["provider"] == "anthropic"
        assert result.data["model"] == "claude-sonnet-4-6"

    async def test_resolve_unknown_role_continues(self, hook_with_matrix):
        """Unknown role falls back to CONTINUE (no resolution)."""
        data = {"model_role": "nonexistent"}
        result = await hook_with_matrix.handle("provider:request", data)
        assert result.action == "CONTINUE"

    async def test_resolve_empty_candidates_continues(self):
        """Role with empty candidates list falls back to CONTINUE."""
        matrix = {
            "name": "test",
            "roles": {
                "empty_role": {
                    "description": "No candidates",
                    "candidates": [],
                },
            },
        }
        hook = RoutingHook(matrix=matrix)
        data = {"model_role": "empty_role"}
        result = await hook.handle("provider:request", data)
        assert result.action == "CONTINUE"

    async def test_resolve_preserves_original_data(self, hook_with_matrix):
        """MODIFY result includes the original data fields plus provider/model."""
        data = {"model_role": "fast", "messages": [{"role": "user", "content": "hi"}]}
        result = await hook_with_matrix.handle("provider:request", data)
        assert result.action == "MODIFY"
        assert result.data["messages"] == [{"role": "user", "content": "hi"}]
        assert result.data["provider"] == "anthropic"
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-hooks-routing && uv run pytest tests/test_hook.py -v
```

Expected: TestResolveModelRole tests FAIL.

**Step 3: Implement resolve(model_role) in RoutingHook**

Replace the entire contents of `services/svc-hooks-routing/src/svc_hooks_routing/hook.py` with:

```python
"""Routing pre-hook: resolves model_role to provider+model, injects routing matrix context."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from amplifier_service_sdk.models import HookResult

logger = logging.getLogger(__name__)


def load_matrix_from_file(path: Path) -> dict:
    """Load a routing matrix from a YAML file.

    Returns an empty dict if the file is not found or cannot be parsed.
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("Failed to load routing matrix from %s", path)
        return {}


class RoutingHook:
    """Sync pre-hook that resolves model roles and injects routing context."""

    name: str = "routing"
    events: list[str] = ["session:start", "provider:request"]
    priority: int = 5
    mode: Literal["sync", "async"] = "sync"

    def __init__(self, matrix: dict[str, Any]) -> None:
        self.matrix = matrix
        self.effective_matrix: dict[str, Any] = matrix.get("roles", {})

    def resolve(self, model_role: str) -> dict[str, str] | None:
        """Resolve a model_role to the first candidate's provider+model.

        Returns:
            Dict with ``provider`` and ``model`` keys, or None if unresolvable.
        """
        role_info = self.effective_matrix.get(model_role)
        if not isinstance(role_info, dict):
            return None

        candidates = role_info.get("candidates", [])
        if not candidates:
            return None

        first = candidates[0]
        provider = first.get("provider")
        model = first.get("model")
        if not provider or not model:
            return None

        return {"provider": provider, "model": model}

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Evaluate a hook event and return an appropriate HookResult."""
        if event == "session:start":
            return HookResult(action="CONTINUE")
        if event == "provider:request":
            return await self._on_provider_request(data)
        return HookResult(action="CONTINUE")

    async def _on_provider_request(self, data: dict[str, Any]) -> HookResult:
        """Handle provider:request events.

        If model_role is present, resolve it to a concrete provider+model
        and return MODIFY. Otherwise, inject the matrix overview context.
        """
        # If model_role is specified, resolve it
        model_role = data.get("model_role")
        if model_role:
            resolved = self.resolve(model_role)
            if resolved is None:
                logger.warning("Could not resolve model_role '%s'", model_role)
                return HookResult(action="CONTINUE")
            # Merge resolved provider/model into the original data
            modified = {**data, **resolved}
            return HookResult(action="MODIFY", data=modified)

        # No model_role — inject matrix overview as context
        if not self.effective_matrix:
            return HookResult(action="CONTINUE")

        matrix_name = self.matrix.get("name", "unknown")
        lines = [f"Routing Matrix: {matrix_name}", "Available roles:"]
        for role_name, role_info in self.effective_matrix.items():
            if isinstance(role_info, dict):
                description = role_info.get("description", "")
                lines.append(f"- {role_name}: {description}")
            else:
                lines.append(f"- {role_name}")

        context_text = "\n".join(lines)
        return HookResult(
            action="INJECT_CONTEXT",
            data={"context_injection": context_text, "ephemeral": True},
        )
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-hooks-routing && uv run pytest tests/test_hook.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-hooks-routing/src/svc_hooks_routing/hook.py services/svc-hooks-routing/tests/test_hook.py && git commit -m "feat(hooks-routing): add resolve(model_role) with routing matrix lookup"
```

---

### Task 3: Todo Tool — Dapr state store persistence

**Files:**
- Modify: `services/svc-todo/src/svc_todo/tool.py`
- Modify: `services/svc-todo/tests/test_tool.py`
- Modify: `services/svc-todo/pyproject.toml` (add httpx dependency)

**Step 1: Add httpx dependency to pyproject.toml**

In `services/svc-todo/pyproject.toml`, change:
```
dependencies = [
    "amplifier-service-sdk",
]
```
to:
```
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
]
```

**Step 2: Write failing tests for Dapr state store writes**

Add the following at the end of `services/svc-todo/tests/test_tool.py`:

```python
from unittest.mock import AsyncMock, patch


class TestDaprStatePersistence:
    """TodoTool should write state to Dapr state store on create and update."""

    @pytest.fixture
    def tool_with_session(self) -> TodoTool:
        return TodoTool(session_id="test-session-123")

    async def test_create_writes_to_dapr(self, tool_with_session: TodoTool) -> None:
        """create action should POST state to Dapr state store."""
        with patch.object(tool_with_session, "_save_state", new_callable=AsyncMock) as mock_save:
            result = await tool_with_session.execute(
                {"action": "create", "todos": [VALID_TODO]}
            )
            assert result.success is True
            mock_save.assert_awaited_once()

    async def test_update_writes_to_dapr(self, tool_with_session: TodoTool) -> None:
        """update action should POST state to Dapr state store."""
        with patch.object(tool_with_session, "_save_state", new_callable=AsyncMock) as mock_save:
            await tool_with_session.execute(
                {"action": "create", "todos": [VALID_TODO]}
            )
            mock_save.reset_mock()
            result = await tool_with_session.execute(
                {"action": "update", "todos": [VALID_TODO, VALID_TODO_2]}
            )
            assert result.success is True
            mock_save.assert_awaited_once()

    async def test_list_does_not_write_to_dapr(self, tool_with_session: TodoTool) -> None:
        """list action should NOT write to Dapr state store."""
        with patch.object(tool_with_session, "_save_state", new_callable=AsyncMock) as mock_save:
            result = await tool_with_session.execute({"action": "list"})
            assert result.success is True
            mock_save.assert_not_awaited()

    async def test_no_session_id_skips_save(self) -> None:
        """Without a session_id, state is stored in-memory only (no Dapr call)."""
        tool = TodoTool()
        with patch.object(tool, "_save_state", new_callable=AsyncMock) as mock_save:
            result = await tool.execute(
                {"action": "create", "todos": [VALID_TODO]}
            )
            assert result.success is True
            mock_save.assert_not_awaited()
```

**Step 3: Run tests to verify they fail**

```bash
cd services/svc-todo && uv run pytest tests/test_tool.py::TestDaprStatePersistence -v
```

Expected: FAIL (TodoTool does not accept `session_id` yet).

**Step 4: Implement Dapr state persistence in TodoTool**

Replace the entire contents of `services/svc-todo/src/svc_todo/tool.py` with:

```python
"""TodoTool — AI-managed todo list with Dapr state store persistence."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from amplifier_service_sdk.models import ToolResult


logger = logging.getLogger(__name__)

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")
_STATE_STORE_NAME = "statestore"


class TodoTool:
    """AI-managed todo list for self-accountability through complex turns."""

    name = "todo"

    description = """Manage your todo list for tracking complex multi-step tasks.

Use this tool to:
- Create a todo list when starting complex multi-step work
- Update the list as you complete each step
- Stay accountable and focused through long turns

Todo items have:
- content: Imperative description (e.g., "Run tests", "Build project")
- activeForm: Present continuous (e.g., "Running tests", "Building project")
- status: "pending" | "in_progress" | "completed"

Recommended pattern:
1. Create list when you start complex multi-step work
2. Update after completing each step
3. Keep exactly ONE item as "in_progress" at a time
4. Mark items "completed" immediately after finishing"""

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "update", "list"],
                "description": "Action to perform: create (replace all), update (replace all), list (read current)",
            },
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Imperative description: 'Run tests', 'Build project'",
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "Present continuous: 'Running tests', 'Building project'",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Current status of this todo item",
                        },
                    },
                    "required": ["content", "status", "activeForm"],
                },
                "description": "List of todos (required for create/update, ignored for list)",
            },
        },
        "required": ["action"],
    }

    def __init__(self, session_id: str | None = None) -> None:
        self._todo_state: list[dict[str, Any]] = []
        self.session_id = session_id

    def _validate_todos(self, todos: list[dict[str, Any]]) -> ToolResult | None:
        """Validate todos list; return error ToolResult on failure, None on success."""
        valid_statuses = {"pending", "in_progress", "completed"}
        for i, todo in enumerate(todos):
            if not all(k in todo for k in ["content", "status", "activeForm"]):
                return ToolResult(
                    success=False,
                    error={
                        "message": f"Todo {i} missing required fields (content, status, activeForm)"
                    },
                )
            if todo["status"] not in valid_statuses:
                return ToolResult(
                    success=False,
                    error={"message": f"Todo {i} has invalid status: {todo['status']}"},
                )
        return None

    async def _save_state(self) -> None:
        """Persist current todo state to Dapr state store (fire-and-forget)."""
        if not self.session_id:
            return
        key = f"todo-{self.session_id}"
        url = f"http://localhost:{_DAPR_HTTP_PORT}/v1.0/state/{_STATE_STORE_NAME}"
        payload = [{"key": key, "value": self._todo_state}]
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=5.0)
                resp.raise_for_status()
            logger.info("Saved todo state to Dapr: key=%s, items=%d", key, len(self._todo_state))
        except Exception:
            logger.warning("Failed to save todo state to Dapr: key=%s", key, exc_info=True)

    async def _handle_create(self, todos: list[dict[str, Any]]) -> ToolResult:
        """Replace entire list with new todos."""
        error = self._validate_todos(todos)
        if error is not None:
            return error
        self._todo_state = todos
        if self.session_id:
            await self._save_state()
        return ToolResult(
            success=True,
            output={"status": "created", "count": len(todos), "todos": todos},
        )

    async def _handle_update(self, todos: list[dict[str, Any]]) -> ToolResult:
        """Replace entire list (AI manages state transitions)."""
        error = self._validate_todos(todos)
        if error is not None:
            return error
        self._todo_state = todos
        if self.session_id:
            await self._save_state()
        pending = sum(1 for t in todos if t["status"] == "pending")
        in_progress = sum(1 for t in todos if t["status"] == "in_progress")
        completed = sum(1 for t in todos if t["status"] == "completed")
        return ToolResult(
            success=True,
            output={
                "status": "updated",
                "count": len(todos),
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
            },
        )

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute todo operation.

        Actions:
        - create: Replace entire list with new todos
        - update: Replace entire list (AI manages state transitions)
        - list: Return current todos
        """
        action = input.get("action")

        if action == "create":
            return await self._handle_create(input.get("todos", []))

        if action == "update":
            return await self._handle_update(input.get("todos", []))

        if action == "list":
            return ToolResult(
                success=True,
                output={
                    "status": "listed",
                    "count": len(self._todo_state),
                    "todos": self._todo_state,
                },
            )

        return ToolResult(
            success=False,
            error={
                "message": f"Unknown action: {action}. Valid actions: create, update, list"
            },
        )
```

**Step 5: Run all tool tests to verify everything passes**

```bash
cd services/svc-todo && uv run pytest tests/test_tool.py -v
```

Expected: All tests PASS (existing tests still work, new Dapr tests pass).

**Step 6: Commit**

```bash
git add services/svc-todo/src/svc_todo/tool.py services/svc-todo/tests/test_tool.py services/svc-todo/pyproject.toml && git commit -m "feat(todo): add Dapr state store persistence with session_id"
```

---

### Task 4: Todo Hooks — TodoReminderHook and TodoDisplayHook

**Files:**
- Modify: `services/svc-todo/src/svc_todo/hooks.py`
- Modify: `services/svc-todo/tests/test_hooks.py`

**Step 1: Write failing tests for real hook logic**

Replace the entire contents of `services/svc-todo/tests/test_hooks.py` with:

```python
"""Tests for TodoReminderHook and TodoDisplayHook."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from svc_todo.hooks import TodoReminderHook, TodoDisplayHook


SAMPLE_TODOS = [
    {"content": "Write tests", "activeForm": "Writing tests", "status": "completed"},
    {"content": "Implement hook", "activeForm": "Implementing hook", "status": "in_progress"},
    {"content": "Run CI", "activeForm": "Running CI", "status": "pending"},
]


class TestTodoReminderHook:
    @pytest.fixture
    def hook(self) -> TodoReminderHook:
        return TodoReminderHook()

    async def test_non_provider_request_continues(self, hook: TodoReminderHook) -> None:
        result = await hook.handle("tool:pre", {})
        assert result.action == "CONTINUE"

    async def test_no_session_id_continues(self, hook: TodoReminderHook) -> None:
        """Without session_id in data, no state to read — returns CONTINUE."""
        result = await hook.handle("provider:request", {})
        assert result.action == "CONTINUE"

    async def test_empty_state_continues(self, hook: TodoReminderHook) -> None:
        """When Dapr state is empty, returns CONTINUE (no reminder needed)."""
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=[]):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            assert result.action == "CONTINUE"

    async def test_injects_context_when_todos_exist(self, hook: TodoReminderHook) -> None:
        """When todos exist, inject system-reminder context."""
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=SAMPLE_TODOS):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            assert result.action == "INJECT_CONTEXT"
            content = result.data["content"]
            assert "hooks-todo-reminder" in content
            assert "Writing tests" not in content  # completed, shows "content" not "activeForm"
            assert "Implementing hook" in content  # in_progress shows activeForm
            assert "Run CI" in content

    async def test_formats_status_symbols(self, hook: TodoReminderHook) -> None:
        """Status symbols: ✓ completed, → in_progress, ☐ pending."""
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=SAMPLE_TODOS):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            content = result.data["content"]
            assert "✓" in content
            assert "→" in content
            assert "☐" in content


class TestTodoDisplayHook:
    @pytest.fixture
    def hook(self) -> TodoDisplayHook:
        return TodoDisplayHook()

    async def test_non_tool_result_continues(self, hook: TodoDisplayHook) -> None:
        result = await hook.handle("provider:request", {})
        assert result.action == "CONTINUE"

    async def test_non_todo_tool_continues(self, hook: TodoDisplayHook) -> None:
        result = await hook.handle("tool:post", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    async def test_todo_tool_post_formats_progress(self, hook: TodoDisplayHook) -> None:
        """For todo tool results, format progress counts."""
        data = {
            "tool_name": "todo",
            "result": {
                "success": True,
                "output": {
                    "status": "updated",
                    "count": 3,
                    "pending": 1,
                    "in_progress": 1,
                    "completed": 1,
                },
            },
        }
        result = await hook.handle("tool:post", data)
        assert result.action == "CONTINUE"
        assert result.data is not None
        assert result.data["display"] is not None
        assert "1 pending" in result.data["display"] or "1/3" in result.data["display"]
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-todo && uv run pytest tests/test_hooks.py -v
```

Expected: Most tests FAIL (hooks are stubs).

**Step 3: Implement real hook logic**

Replace the entire contents of `services/svc-todo/src/svc_todo/hooks.py` with:

```python
"""Todo hooks — reminder injection and display formatting."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import httpx
from amplifier_service_sdk.models import HookResult


logger = logging.getLogger(__name__)

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")
_STATE_STORE_NAME = "statestore"


class TodoReminderHook:
    """Pre-hook on provider:request that injects current todo state as a reminder."""

    name: str = "todo_reminder"
    events: list[str] = ["provider:request"]
    priority: int = 10
    mode: Literal["sync", "async"] = "sync"

    async def _read_state(self, session_id: str) -> list[dict[str, Any]]:
        """Read todo state from Dapr state store."""
        key = f"todo-{session_id}"
        url = f"http://localhost:{_DAPR_HTTP_PORT}/v1.0/state/{_STATE_STORE_NAME}/{key}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=5.0)
                if resp.status_code == 204 or not resp.content:
                    return []
                return resp.json()
        except Exception:
            logger.warning("Failed to read todo state from Dapr: key=%s", key, exc_info=True)
            return []

    def _format_todos(self, todos: list[dict[str, Any]]) -> str:
        """Format todos with status symbols."""
        lines = []
        for todo in todos:
            status = todo.get("status", "pending")
            if status == "completed":
                symbol = "✓"
                text = todo.get("content", "")
            elif status == "in_progress":
                symbol = "→"
                text = todo.get("activeForm", todo.get("content", ""))
            else:
                symbol = "☐"
                text = todo.get("content", "")
            lines.append(f"{symbol} {text}")
        return "\n".join(lines)

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle hook event — inject todo reminder on provider:request."""
        if event != "provider:request":
            return HookResult(action="CONTINUE")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="CONTINUE")

        todos = await self._read_state(session_id)
        if not todos:
            return HookResult(action="CONTINUE")

        formatted = self._format_todos(todos)
        content = (
            f'<system-reminder source="hooks-todo-reminder">\n'
            f"{formatted}\n"
            f"DO NOT mention this reminder to the user. Process silently and continue your work.\n"
            f"</system-reminder>"
        )

        return HookResult(
            action="INJECT_CONTEXT",
            data={"content": content, "ephemeral": True},
        )


class TodoDisplayHook:
    """Post-hook on tool:post that formats todo progress for display."""

    name: str = "todo_display"
    events: list[str] = ["tool:post"]
    priority: int = 50
    mode: Literal["sync", "async"] = "sync"

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle hook event — format todo progress on tool:post for todo tool."""
        if event != "tool:post":
            return HookResult(action="CONTINUE")

        tool_name = data.get("tool_name", "")
        if tool_name != "todo":
            return HookResult(action="CONTINUE")

        result = data.get("result", {})
        output = result.get("output", {}) if isinstance(result, dict) else {}
        if not isinstance(output, dict):
            return HookResult(action="CONTINUE")

        status = output.get("status")
        count = output.get("count", 0)
        pending = output.get("pending", 0)
        in_progress = output.get("in_progress", 0)
        completed = output.get("completed", 0)

        if status in ("created", "updated"):
            display = f"Todo: {completed}/{count} done, {in_progress} active, {pending} pending"
            return HookResult(action="CONTINUE", data={"display": display})

        return HookResult(action="CONTINUE")
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-todo && uv run pytest tests/test_hooks.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-todo/src/svc_todo/hooks.py services/svc-todo/tests/test_hooks.py && git commit -m "feat(todo): implement TodoReminderHook and TodoDisplayHook with Dapr state"
```

---

### Task 5: Skills Visibility Hook

**Files:**
- Create: `services/svc-skills/src/svc_skills/visibility_hook.py`
- Create: `services/svc-skills/tests/test_visibility_hook.py`
- Modify: `services/svc-skills/src/svc_skills/app.py`

**Step 1: Write failing tests for SkillsVisibilityHook**

Create `services/svc-skills/tests/test_visibility_hook.py`:

```python
"""Tests for SkillsVisibilityHook."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from svc_skills.visibility_hook import SkillsVisibilityHook


@pytest.fixture
def mock_skills_tool():
    """Mock SkillsTool with pre-loaded skills."""
    tool = MagicMock()
    tool._initialized = True
    skill1 = MagicMock()
    skill1.name = "python-standards"
    skill1.description = "Python coding standards"
    skill2 = MagicMock()
    skill2.name = "design-patterns"
    skill2.description = "Software design patterns"
    tool.skills = {"python-standards": skill1, "design-patterns": skill2}
    return tool


@pytest.fixture
def hook(mock_skills_tool) -> SkillsVisibilityHook:
    return SkillsVisibilityHook(skills_tool=mock_skills_tool)


@pytest.fixture
def hook_empty() -> SkillsVisibilityHook:
    tool = MagicMock()
    tool._initialized = True
    tool.skills = {}
    return SkillsVisibilityHook(skills_tool=tool)


class TestSkillsVisibilityHook:
    async def test_non_provider_request_continues(self, hook):
        result = await hook.handle("tool:pre", {})
        assert result.action == "CONTINUE"

    async def test_injects_skills_list(self, hook):
        result = await hook.handle("provider:request", {})
        assert result.action == "INJECT_CONTEXT"
        content = result.data["content"]
        assert "hooks-skills-visibility" in content
        assert "python-standards" in content
        assert "design-patterns" in content

    async def test_empty_skills_continues(self, hook_empty):
        result = await hook_empty.handle("provider:request", {})
        assert result.action == "CONTINUE"

    async def test_content_is_system_reminder(self, hook):
        result = await hook.handle("provider:request", {})
        content = result.data["content"]
        assert content.startswith('<system-reminder source="hooks-skills-visibility">')
        assert content.endswith("</system-reminder>")
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-skills && uv run pytest tests/test_visibility_hook.py -v
```

Expected: FAIL (module `svc_skills.visibility_hook` does not exist).

**Step 3: Implement SkillsVisibilityHook**

Create `services/svc-skills/src/svc_skills/visibility_hook.py`:

```python
"""SkillsVisibilityHook — injects available skills list into provider context."""

from __future__ import annotations

import logging
from typing import Any, Literal

from amplifier_service_sdk.models import HookResult


logger = logging.getLogger(__name__)


class SkillsVisibilityHook:
    """Pre-hook on provider:request that injects available skills as system context."""

    name: str = "skills_visibility"
    events: list[str] = ["provider:request"]
    priority: int = 20
    mode: Literal["sync", "async"] = "sync"

    def __init__(self, skills_tool: Any) -> None:
        """Initialize with a reference to the SkillsTool instance.

        Args:
            skills_tool: SkillsTool instance whose `skills` dict is read.
        """
        self._skills_tool = skills_tool

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Inject available skills list on provider:request events."""
        if event != "provider:request":
            return HookResult(action="CONTINUE")

        skills = self._skills_tool.skills
        if not skills:
            return HookResult(action="CONTINUE")

        lines = ["Available skills (use load_skill tool):", ""]
        for name in sorted(skills):
            metadata = skills[name]
            desc = getattr(metadata, "description", str(metadata))
            lines.append(f"- **{name}**: {desc}")

        skills_text = "\n".join(lines)
        content = (
            f'<system-reminder source="hooks-skills-visibility">\n'
            f"{skills_text}\n"
            f"</system-reminder>"
        )

        return HookResult(
            action="INJECT_CONTEXT",
            data={"content": content, "ephemeral": True},
        )
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-skills && uv run pytest tests/test_visibility_hook.py -v
```

Expected: All tests PASS.

**Step 5: Wire the hook into svc-skills app.py**

In `services/svc-skills/src/svc_skills/app.py`, replace the entire file with:

```python
"""FastAPI app factory for svc-skills — the skills tool service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration, ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_skills.tool import SkillsTool
from svc_skills.visibility_hook import SkillsVisibilityHook


def create_skills_app() -> FastAPI:
    """Create the svc-skills FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    skills-specific /tools/load_skill/execute endpoint, plus the
    skills visibility hook endpoint.

    Returns:
        Configured FastAPI application.
    """
    skills_tool = SkillsTool()
    visibility_hook = SkillsVisibilityHook(skills_tool=skills_tool)

    config = ServiceConfig(
        name="svc-skills",
        tools=[
            ToolCapability(
                name=skills_tool.name,
                description=skills_tool.description,
                input_schema=skills_tool.input_schema,
            ),
        ],
        hooks=[
            HookRegistration(
                name=SkillsVisibilityHook.name,
                events=SkillsVisibilityHook.events,
                priority=SkillsVisibilityHook.priority,
                mode=SkillsVisibilityHook.mode,
            ),
        ],
    )
    fastapi_app = create_app(config)

    @fastapi_app.post("/tools/load_skill/execute")
    async def execute_load_skill(request: ToolRequest) -> dict[str, Any]:
        """Load domain knowledge from a skill."""
        result = await skills_tool.execute(request.input)
        return result.model_dump()

    @fastapi_app.post("/hooks/skills_visibility/invoke")
    async def invoke_visibility_hook(event: HookEvent) -> dict[str, Any]:
        """Invoke the skills visibility hook."""
        result = await visibility_hook.handle(event.event, event.data)
        return result.model_dump()

    @fastapi_app.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return fastapi_app


app = create_skills_app()
```

**Step 6: Run full svc-skills test suite**

```bash
cd services/svc-skills && uv run pytest tests/ -v
```

Expected: All tests PASS (existing tests + new hook tests).

**Step 7: Commit**

```bash
git add services/svc-skills/src/svc_skills/visibility_hook.py services/svc-skills/src/svc_skills/app.py services/svc-skills/tests/test_visibility_hook.py && git commit -m "feat(skills): add SkillsVisibilityHook injecting available skills list"
```

---

## Phase 3B: New Hook Services (Tasks 6–8)

### Task 6: svc-hooks-redaction — Scaffold and implement

**Files:**
- Create: `services/svc-hooks-redaction/src/svc_hooks_redaction/__init__.py`
- Create: `services/svc-hooks-redaction/src/svc_hooks_redaction/hook.py`
- Create: `services/svc-hooks-redaction/src/svc_hooks_redaction/app.py`
- Create: `services/svc-hooks-redaction/tests/__init__.py`
- Create: `services/svc-hooks-redaction/tests/test_hook.py`
- Create: `services/svc-hooks-redaction/pyproject.toml`
- Create: `services/svc-hooks-redaction/Dockerfile`

**Step 1: Create pyproject.toml**

Create `services/svc-hooks-redaction/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-hooks-redaction"
version = "0.1.0"
description = "Amplifier redaction pre-hook — masks secrets and PII in event payloads"
requires-python = ">=3.11"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/svc_hooks_redaction"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[dependency-groups]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]
```

**Step 2: Create Dockerfile**

Create `services/svc-hooks-redaction/Dockerfile`:

```dockerfile
# ── Stage 1: Shared Amplifier service base ────────────────────────────────
FROM python:3.12-slim AS amplifier-service-base
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY amplifier-service-sdk/ /build/amplifier-service-sdk/
RUN cd /build/amplifier-service-sdk && uv pip install --system . && rm -rf /build
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
EXPOSE 8000

# ── Stage 2: svc-hooks-redaction ──────────────────────────────────────────
FROM amplifier-service-base
COPY amplifier-service-sdk/ /amplifier-service-sdk/
COPY services/svc-hooks-redaction/ /build/svc-hooks-redaction/
RUN cd /build/svc-hooks-redaction && uv pip install --system . && rm -rf /build /amplifier-service-sdk

CMD ["uvicorn", "svc_hooks_redaction.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Create __init__.py files**

Create empty `services/svc-hooks-redaction/src/svc_hooks_redaction/__init__.py` and `services/svc-hooks-redaction/tests/__init__.py`.

**Step 4: Write failing tests for RedactionHook**

Create `services/svc-hooks-redaction/tests/test_hook.py`:

```python
"""Tests for RedactionHook — regex-based secret/PII masking."""

import pytest
from svc_hooks_redaction.hook import RedactionHook


@pytest.fixture
def hook() -> RedactionHook:
    return RedactionHook()


class TestRedactionPatterns:
    async def test_redacts_aws_key(self, hook):
        data = {"content": "My key is AKIAIOSFODNN7EXAMPLE and that's it"}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert "AKIAIOSFODNN7EXAMPLE" not in result.data["content"]
        assert "[REDACTED:aws-key]" in result.data["content"]

    async def test_redacts_jwt(self, hook):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456"
        data = {"content": f"Token: {jwt}"}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert "[REDACTED:jwt]" in result.data["content"]

    async def test_redacts_api_key(self, hook):
        data = {"content": "Use sk-abc123def456ghi789jkl012mno for auth"}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert "[REDACTED:api-key]" in result.data["content"]

    async def test_redacts_email(self, hook):
        data = {"content": "Contact user@example.com for help"}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert "[REDACTED:email]" in result.data["content"]

    async def test_redacts_private_key(self, hook):
        data = {"content": "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert "[REDACTED:private-key]" in result.data["content"]

    async def test_no_secrets_continues(self, hook):
        data = {"content": "Just a normal message with no secrets"}
        result = await hook.handle("tool:pre", data)
        assert result.action == "CONTINUE"


class TestStructuralFieldSkipping:
    async def test_skips_tool_name_field(self, hook):
        """Structural fields like tool_name are not scanned for secrets."""
        data = {"tool_name": "AKIAIOSFODNN7EXAMPLE", "content": "hello"}
        result = await hook.handle("tool:pre", data)
        # tool_name is preserved as-is (structural field)
        if result.action == "MODIFY":
            assert result.data["tool_name"] == "AKIAIOSFODNN7EXAMPLE"
        else:
            assert result.action == "CONTINUE"

    async def test_skips_event_field(self, hook):
        data = {"event": "AKIAIOSFODNN7EXAMPLE", "content": "hello"}
        result = await hook.handle("tool:pre", data)
        if result.action == "MODIFY":
            assert result.data["event"] == "AKIAIOSFODNN7EXAMPLE"
        else:
            assert result.action == "CONTINUE"


class TestNestedRedaction:
    async def test_redacts_in_nested_dict(self, hook):
        data = {"result": {"output": "Key is AKIAIOSFODNN7EXAMPLE"}}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert "[REDACTED:aws-key]" in result.data["result"]["output"]

    async def test_redacts_in_list(self, hook):
        data = {"messages": ["Secret is AKIAIOSFODNN7EXAMPLE"]}
        result = await hook.handle("tool:pre", data)
        assert result.action == "MODIFY"
        assert "[REDACTED:aws-key]" in result.data["messages"][0]


class TestUnrelatedEvents:
    async def test_handles_all_event_types(self, hook):
        """Redaction hook fires on all events (universal pre-hook)."""
        data = {"content": "AKIAIOSFODNN7EXAMPLE"}
        for event in ["tool:pre", "tool:post", "provider:request", "session:start"]:
            result = await hook.handle(event, data)
            assert result.action == "MODIFY"
            assert "[REDACTED:aws-key]" in result.data["content"]
```

**Step 5: Run tests to verify they fail**

```bash
cd services/svc-hooks-redaction && uv sync && uv run pytest tests/test_hook.py -v
```

Expected: FAIL (module does not exist yet).

**Step 6: Implement RedactionHook**

Create `services/svc-hooks-redaction/src/svc_hooks_redaction/hook.py`:

```python
"""Redaction pre-hook: masks secrets and PII in event payloads."""

from __future__ import annotations

import copy
import re
from typing import Any, Literal

from amplifier_service_sdk.models import HookResult

# Compiled patterns: (regex, replacement_type)
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws-key"),
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "jwt"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "api-key"),
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "email"),
    (re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"), "private-key"),
]

# Fields that are structural and should NOT be scanned for secrets
_SKIP_FIELDS: frozenset[str] = frozenset({
    "tool_name", "event", "hook_name", "action", "session_id",
})


def _redact_string(value: str) -> tuple[str, bool]:
    """Apply all redaction patterns to a string. Returns (result, changed)."""
    changed = False
    for pattern, rtype in PATTERNS:
        new_value = pattern.sub(f"[REDACTED:{rtype}]", value)
        if new_value != value:
            changed = True
            value = new_value
    return value, changed


def _redact_value(value: Any, skip_key: bool = False) -> tuple[Any, bool]:
    """Recursively redact secrets from a value. Returns (result, changed)."""
    if skip_key:
        return value, False
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        return _redact_dict(value)
    if isinstance(value, list):
        return _redact_list(value)
    return value, False


def _redact_dict(d: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Redact secrets in a dict, skipping structural fields."""
    result = {}
    changed = False
    for key, value in d.items():
        if key in _SKIP_FIELDS:
            result[key] = value
        else:
            new_value, field_changed = _redact_value(value)
            result[key] = new_value
            if field_changed:
                changed = True
    return result, changed


def _redact_list(lst: list[Any]) -> tuple[list[Any], bool]:
    """Redact secrets in a list."""
    result = []
    changed = False
    for item in lst:
        new_item, item_changed = _redact_value(item)
        result.append(new_item)
        if item_changed:
            changed = True
    return result, changed


class RedactionHook:
    """Universal pre-hook that masks secrets and PII in all event payloads."""

    name: str = "redaction"
    events: list[str] = ["*"]  # fires on all events
    priority: int = 1  # runs first (lowest number = highest priority)
    mode: Literal["sync", "async"] = "sync"

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Scan event data for secrets and replace with [REDACTED:type] markers."""
        redacted, changed = _redact_dict(data)
        if changed:
            return HookResult(action="MODIFY", data=redacted)
        return HookResult(action="CONTINUE")
```

**Step 7: Create app.py**

Create `services/svc-hooks-redaction/src/svc_hooks_redaction/app.py`:

```python
"""FastAPI application for the redaction pre-hook service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_redaction.hook import RedactionHook


def create_redaction_hook_app() -> FastAPI:
    """Create and configure the redaction hook FastAPI application."""
    hook = RedactionHook()

    service_config = ServiceConfig(
        name="svc-hooks-redaction",
        hooks=[
            HookRegistration(
                name=RedactionHook.name,
                events=RedactionHook.events,
                priority=RedactionHook.priority,
                mode=RedactionHook.mode,
            )
        ],
    )

    application = create_app(service_config)

    @application.post("/hooks/redaction/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return application


app = create_redaction_hook_app()
```

**Step 8: Run tests to verify they pass**

```bash
cd services/svc-hooks-redaction && uv sync && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 9: Commit**

```bash
git add services/svc-hooks-redaction/ && git commit -m "feat: create svc-hooks-redaction service with regex-based secret masking"
```

---

### Task 7: svc-hooks-status-context — Scaffold and implement

**Files:**
- Create: `services/svc-hooks-status-context/src/svc_hooks_status_context/__init__.py`
- Create: `services/svc-hooks-status-context/src/svc_hooks_status_context/hook.py`
- Create: `services/svc-hooks-status-context/src/svc_hooks_status_context/app.py`
- Create: `services/svc-hooks-status-context/tests/__init__.py`
- Create: `services/svc-hooks-status-context/tests/test_hook.py`
- Create: `services/svc-hooks-status-context/pyproject.toml`
- Create: `services/svc-hooks-status-context/Dockerfile`

**Step 1: Create pyproject.toml**

Create `services/svc-hooks-status-context/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-hooks-status-context"
version = "0.1.0"
description = "Amplifier status context pre-hook — injects git, platform, and datetime info"
requires-python = ">=3.11"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/svc_hooks_status_context"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[dependency-groups]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]
```

**Step 2: Create Dockerfile**

Create `services/svc-hooks-status-context/Dockerfile`:

```dockerfile
# ── Stage 1: Shared Amplifier service base ────────────────────────────────
FROM python:3.12-slim AS amplifier-service-base
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY amplifier-service-sdk/ /build/amplifier-service-sdk/
RUN cd /build/amplifier-service-sdk && uv pip install --system . && rm -rf /build
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
EXPOSE 8000

# ── Stage 2: svc-hooks-status-context ─────────────────────────────────────
FROM amplifier-service-base
COPY amplifier-service-sdk/ /amplifier-service-sdk/
COPY services/svc-hooks-status-context/ /build/svc-hooks-status-context/
RUN cd /build/svc-hooks-status-context && uv pip install --system . && rm -rf /build /amplifier-service-sdk

CMD ["uvicorn", "svc_hooks_status_context.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Create __init__.py files**

Create empty `services/svc-hooks-status-context/src/svc_hooks_status_context/__init__.py` and `services/svc-hooks-status-context/tests/__init__.py`.

**Step 4: Write failing tests for StatusContextHook**

Create `services/svc-hooks-status-context/tests/test_hook.py`:

```python
"""Tests for StatusContextHook — git status, platform, datetime injection."""

import pytest
from unittest.mock import AsyncMock, patch

from svc_hooks_status_context.hook import StatusContextHook


@pytest.fixture
def hook() -> StatusContextHook:
    return StatusContextHook()


class TestStatusContextHook:
    async def test_non_provider_request_continues(self, hook):
        result = await hook.handle("tool:pre", {})
        assert result.action == "CONTINUE"

    async def test_injects_context_on_provider_request(self, hook):
        mock_info = {
            "git_branch": "main",
            "git_status": "clean",
            "platform": "Linux x86_64",
            "working_directory": "/workspace",
        }
        with patch.object(hook, "_gather_info", new_callable=AsyncMock, return_value=mock_info):
            result = await hook.handle("provider:request", {})
            assert result.action == "INJECT_CONTEXT"
            content = result.data["content"]
            assert "hooks-status-context" in content
            assert "main" in content
            assert "clean" in content
            assert "Linux" in content

    async def test_content_is_system_reminder(self, hook):
        mock_info = {
            "git_branch": "feat/test",
            "git_status": "3 files modified",
            "platform": "Darwin arm64",
            "working_directory": "/home/user/project",
        }
        with patch.object(hook, "_gather_info", new_callable=AsyncMock, return_value=mock_info):
            result = await hook.handle("provider:request", {})
            content = result.data["content"]
            assert content.startswith('<system-reminder source="hooks-status-context">')
            assert content.endswith("</system-reminder>")

    async def test_includes_datetime(self, hook):
        mock_info = {
            "git_branch": "main",
            "git_status": "clean",
            "platform": "Linux x86_64",
            "working_directory": "/workspace",
        }
        with patch.object(hook, "_gather_info", new_callable=AsyncMock, return_value=mock_info):
            result = await hook.handle("provider:request", {})
            content = result.data["content"]
            # Should contain a date-like string (YYYY-MM-DD)
            assert "202" in content  # year prefix

    async def test_gather_info_failure_continues(self, hook):
        """If gathering info fails, return CONTINUE (don't block the request)."""
        with patch.object(hook, "_gather_info", new_callable=AsyncMock, side_effect=Exception("fail")):
            result = await hook.handle("provider:request", {})
            assert result.action == "CONTINUE"
```

**Step 5: Run tests to verify they fail**

```bash
cd services/svc-hooks-status-context && uv sync && uv run pytest tests/test_hook.py -v
```

Expected: FAIL (module does not exist yet).

**Step 6: Implement StatusContextHook**

Create `services/svc-hooks-status-context/src/svc_hooks_status_context/hook.py`:

```python
"""Status context pre-hook: injects git, platform, and datetime info."""

from __future__ import annotations

import logging
import os
import platform
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from amplifier_service_sdk.models import HookResult


logger = logging.getLogger(__name__)

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")
_MACHINE_APP_ID = os.environ.get("MACHINE_APP_ID", "svc-machine")


class StatusContextHook:
    """Pre-hook on provider:request that injects environmental context."""

    name: str = "status_context"
    events: list[str] = ["provider:request"]
    priority: int = 8
    mode: Literal["sync", "async"] = "sync"

    async def _exec_on_machine(self, command: str) -> str:
        """Execute a command on svc-machine and return stdout."""
        url = f"http://localhost:{_DAPR_HTTP_PORT}/v1.0/invoke/{_MACHINE_APP_ID}/method/exec"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    json={"command": command, "timeout": 5},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("stdout", "").strip()
        except Exception:
            logger.debug("Failed to exec '%s' on svc-machine", command, exc_info=True)
        return ""

    async def _gather_info(self) -> dict[str, str]:
        """Gather git, platform, and working directory info."""
        git_branch = await self._exec_on_machine("git branch --show-current")
        git_porcelain = await self._exec_on_machine("git status --porcelain")
        platform_info = await self._exec_on_machine("uname -a")

        if not git_porcelain:
            git_status = "clean"
        else:
            file_count = len([l for l in git_porcelain.splitlines() if l.strip()])
            git_status = f"{file_count} files modified"

        return {
            "git_branch": git_branch or "unknown",
            "git_status": git_status,
            "platform": platform_info or f"{platform.system()} {platform.machine()}",
            "working_directory": os.environ.get("WORKSPACE_DIR", "/workspace"),
        }

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Inject status context on provider:request events."""
        if event != "provider:request":
            return HookResult(action="CONTINUE")

        try:
            info = await self._gather_info()
        except Exception:
            logger.warning("Failed to gather status context", exc_info=True)
            return HookResult(action="CONTINUE")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            f"Working directory: {info['working_directory']}",
            f"Git branch: {info['git_branch']}",
            f"Git status: {info['git_status']}",
            f"Platform: {info['platform']}",
            f"Date: {now}",
        ]

        content = (
            '<system-reminder source="hooks-status-context">\n'
            + "\n".join(lines)
            + "\n</system-reminder>"
        )

        return HookResult(
            action="INJECT_CONTEXT",
            data={"content": content, "ephemeral": True},
        )
```

**Step 7: Create app.py**

Create `services/svc-hooks-status-context/src/svc_hooks_status_context/app.py`:

```python
"""FastAPI application for the status context pre-hook service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_status_context.hook import StatusContextHook


def create_status_context_hook_app() -> FastAPI:
    """Create and configure the status context hook FastAPI application."""
    hook = StatusContextHook()

    service_config = ServiceConfig(
        name="svc-hooks-status-context",
        hooks=[
            HookRegistration(
                name=StatusContextHook.name,
                events=StatusContextHook.events,
                priority=StatusContextHook.priority,
                mode=StatusContextHook.mode,
            )
        ],
    )

    application = create_app(service_config)

    @application.post("/hooks/status_context/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return application


app = create_status_context_hook_app()
```

**Step 8: Run tests to verify they pass**

```bash
cd services/svc-hooks-status-context && uv sync && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 9: Commit**

```bash
git add services/svc-hooks-status-context/ && git commit -m "feat: create svc-hooks-status-context service with git/platform/datetime injection"
```

---

### Task 8: svc-hooks-todo-reminder — Scaffold and implement

**Files:**
- Create: `services/svc-hooks-todo-reminder/src/svc_hooks_todo_reminder/__init__.py`
- Create: `services/svc-hooks-todo-reminder/src/svc_hooks_todo_reminder/hook.py`
- Create: `services/svc-hooks-todo-reminder/src/svc_hooks_todo_reminder/app.py`
- Create: `services/svc-hooks-todo-reminder/tests/__init__.py`
- Create: `services/svc-hooks-todo-reminder/tests/test_hook.py`
- Create: `services/svc-hooks-todo-reminder/pyproject.toml`
- Create: `services/svc-hooks-todo-reminder/Dockerfile`

This is a standalone service (separate from svc-todo) that reads todo state from Dapr state store and injects reminders before each LLM call. It is ported from `related-projects/amplifier-module-hooks-todo-reminder/`.

**Step 1: Create pyproject.toml**

Create `services/svc-hooks-todo-reminder/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-hooks-todo-reminder"
version = "0.1.0"
description = "Amplifier todo reminder pre-hook — injects current todo state before LLM calls"
requires-python = ">=3.11"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/svc_hooks_todo_reminder"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[dependency-groups]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]
```

**Step 2: Create Dockerfile**

Create `services/svc-hooks-todo-reminder/Dockerfile`:

```dockerfile
# ── Stage 1: Shared Amplifier service base ────────────────────────────────
FROM python:3.12-slim AS amplifier-service-base
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY amplifier-service-sdk/ /build/amplifier-service-sdk/
RUN cd /build/amplifier-service-sdk && uv pip install --system . && rm -rf /build
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
EXPOSE 8000

# ── Stage 2: svc-hooks-todo-reminder ──────────────────────────────────────
FROM amplifier-service-base
COPY amplifier-service-sdk/ /amplifier-service-sdk/
COPY services/svc-hooks-todo-reminder/ /build/svc-hooks-todo-reminder/
RUN cd /build/svc-hooks-todo-reminder && uv pip install --system . && rm -rf /build /amplifier-service-sdk

CMD ["uvicorn", "svc_hooks_todo_reminder.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Create __init__.py files**

Create empty `services/svc-hooks-todo-reminder/src/svc_hooks_todo_reminder/__init__.py` and `services/svc-hooks-todo-reminder/tests/__init__.py`.

**Step 4: Write failing tests for TodoReminderHook**

Create `services/svc-hooks-todo-reminder/tests/test_hook.py`:

```python
"""Tests for standalone TodoReminderHook — reads Dapr state, injects reminder."""

import pytest
from unittest.mock import AsyncMock, patch

from svc_hooks_todo_reminder.hook import TodoReminderHook


SAMPLE_TODOS = [
    {"content": "Write tests", "activeForm": "Writing tests", "status": "completed"},
    {"content": "Implement hook", "activeForm": "Implementing hook", "status": "in_progress"},
    {"content": "Run CI", "activeForm": "Running CI", "status": "pending"},
]


@pytest.fixture
def hook() -> TodoReminderHook:
    return TodoReminderHook()


class TestTodoReminderHook:
    async def test_non_provider_request_continues(self, hook):
        result = await hook.handle("tool:pre", {})
        assert result.action == "CONTINUE"

    async def test_no_session_id_continues(self, hook):
        result = await hook.handle("provider:request", {})
        assert result.action == "CONTINUE"

    async def test_empty_state_continues(self, hook):
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=[]):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            assert result.action == "CONTINUE"

    async def test_injects_reminder_when_todos_exist(self, hook):
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=SAMPLE_TODOS):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            assert result.action == "INJECT_CONTEXT"
            content = result.data["content"]
            assert "hooks-todo-reminder" in content
            assert "✓" in content
            assert "→" in content
            assert "☐" in content

    async def test_completed_shows_content_not_activeForm(self, hook):
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=SAMPLE_TODOS):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            content = result.data["content"]
            assert "Write tests" in content
            assert "Writing tests" not in content  # completed shows content, not activeForm

    async def test_in_progress_shows_activeForm(self, hook):
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=SAMPLE_TODOS):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            content = result.data["content"]
            assert "Implementing hook" in content  # in_progress shows activeForm

    async def test_read_state_called_with_session_id(self, hook):
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=[]) as mock:
            await hook.handle("provider:request", {"session_id": "my-session"})
            mock.assert_awaited_once_with("my-session")

    async def test_read_state_failure_continues(self, hook):
        """If Dapr state read fails, return CONTINUE (don't block the request)."""
        with patch.object(hook, "_read_state", new_callable=AsyncMock, side_effect=Exception("fail")):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            assert result.action == "CONTINUE"

    async def test_content_wraps_in_system_reminder(self, hook):
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=SAMPLE_TODOS):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            content = result.data["content"]
            assert content.startswith('<system-reminder source="hooks-todo-reminder">')
            assert content.endswith("</system-reminder>")

    async def test_ephemeral_flag_set(self, hook):
        with patch.object(hook, "_read_state", new_callable=AsyncMock, return_value=SAMPLE_TODOS):
            result = await hook.handle("provider:request", {"session_id": "sess-1"})
            assert result.data["ephemeral"] is True
```

**Step 5: Run tests to verify they fail**

```bash
cd services/svc-hooks-todo-reminder && uv sync && uv run pytest tests/test_hook.py -v
```

Expected: FAIL (module does not exist yet).

**Step 6: Implement TodoReminderHook**

Create `services/svc-hooks-todo-reminder/src/svc_hooks_todo_reminder/hook.py`:

```python
"""Todo reminder pre-hook: reads Dapr state and injects todo reminders."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import httpx
from amplifier_service_sdk.models import HookResult


logger = logging.getLogger(__name__)

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")
_STATE_STORE_NAME = "statestore"


class TodoReminderHook:
    """Pre-hook on provider:request that injects current todo state as a reminder.

    Reads session-keyed todo state from Dapr state store (key: todo-{session_id})
    and injects it as a system-reminder block. Only injects when the todo list
    is non-empty.
    """

    name: str = "todo_reminder"
    events: list[str] = ["provider:request"]
    priority: int = 10
    mode: Literal["sync", "async"] = "sync"

    async def _read_state(self, session_id: str) -> list[dict[str, Any]]:
        """Read todo state from Dapr state store."""
        key = f"todo-{session_id}"
        url = f"http://localhost:{_DAPR_HTTP_PORT}/v1.0/state/{_STATE_STORE_NAME}/{key}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=5.0)
                if resp.status_code == 204 or not resp.content:
                    return []
                data = resp.json()
                return data if isinstance(data, list) else []
        except Exception:
            logger.warning("Failed to read todo state: key=%s", key, exc_info=True)
            return []

    def _format_todos(self, todos: list[dict[str, Any]]) -> str:
        """Format todos with status symbols.

        Symbols: ✓ (completed), → (in progress), ☐ (pending).
        Shows activeForm for in_progress items, content otherwise.
        """
        lines = []
        for todo in todos:
            status = todo.get("status", "pending")
            if status == "completed":
                symbol = "✓"
                text = todo.get("content", "")
            elif status == "in_progress":
                symbol = "→"
                text = todo.get("activeForm", todo.get("content", ""))
            else:
                symbol = "☐"
                text = todo.get("content", "")
            lines.append(f"{symbol} {text}")
        return "\n".join(lines)

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle hook event — inject todo reminder on provider:request."""
        if event != "provider:request":
            return HookResult(action="CONTINUE")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="CONTINUE")

        try:
            todos = await self._read_state(session_id)
        except Exception:
            logger.warning("Failed to read todo state for reminder", exc_info=True)
            return HookResult(action="CONTINUE")

        if not todos:
            return HookResult(action="CONTINUE")

        formatted = self._format_todos(todos)
        content = (
            '<system-reminder source="hooks-todo-reminder">\n'
            f"{formatted}\n"
            "DO NOT mention this reminder to the user. Process silently and continue your work.\n"
            "</system-reminder>"
        )

        return HookResult(
            action="INJECT_CONTEXT",
            data={"content": content, "ephemeral": True},
        )
```

**Step 7: Create app.py**

Create `services/svc-hooks-todo-reminder/src/svc_hooks_todo_reminder/app.py`:

```python
"""FastAPI application for the todo reminder pre-hook service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_todo_reminder.hook import TodoReminderHook


def create_todo_reminder_hook_app() -> FastAPI:
    """Create and configure the todo reminder hook FastAPI application."""
    hook = TodoReminderHook()

    service_config = ServiceConfig(
        name="svc-hooks-todo-reminder",
        hooks=[
            HookRegistration(
                name=TodoReminderHook.name,
                events=TodoReminderHook.events,
                priority=TodoReminderHook.priority,
                mode=TodoReminderHook.mode,
            )
        ],
    )

    application = create_app(service_config)

    @application.post("/hooks/todo_reminder/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @application.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict]:
        return []

    return application


app = create_todo_reminder_hook_app()
```

**Step 8: Run tests to verify they pass**

```bash
cd services/svc-hooks-todo-reminder && uv sync && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 9: Commit**

```bash
git add services/svc-hooks-todo-reminder/ && git commit -m "feat: create svc-hooks-todo-reminder service reading Dapr state for reminders"
```

---

## Final Verification

### Task 9: Run all tests across all modified and new services

**Step 1: Run svc-hooks-approval tests**

```bash
cd services/svc-hooks-approval && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 2: Run svc-hooks-routing tests**

```bash
cd services/svc-hooks-routing && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 3: Run svc-todo tests**

```bash
cd services/svc-todo && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 4: Run svc-skills tests**

```bash
cd services/svc-skills && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 5: Run svc-hooks-redaction tests**

```bash
cd services/svc-hooks-redaction && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 6: Run svc-hooks-status-context tests**

```bash
cd services/svc-hooks-status-context && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 7: Run svc-hooks-todo-reminder tests**

```bash
cd services/svc-hooks-todo-reminder && uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 8: Commit final verification**

```bash
git add -A && git status
```

Verify no uncommitted changes remain. If clean, the phase is complete.

---

## Summary

| Task | Service | What Changed |
|------|---------|-------------|
| 1 | svc-hooks-approval | Allow-list, argument inspection, risk metadata, structured denial |
| 2 | svc-hooks-routing | `resolve(model_role)` with routing matrix lookup, MODIFY action |
| 3 | svc-todo (tool) | Dapr state store persistence with `session_id`, `_save_state()` |
| 4 | svc-todo (hooks) | `TodoReminderHook` reads Dapr state, `TodoDisplayHook` formats progress |
| 5 | svc-skills | `SkillsVisibilityHook` + hook endpoint in app.py |
| 6 | svc-hooks-redaction | **NEW** — regex-based secret/PII masking, universal pre-hook |
| 7 | svc-hooks-status-context | **NEW** — git/platform/datetime injection via svc-machine |
| 8 | svc-hooks-todo-reminder | **NEW** — standalone Dapr state reader, reminder injection |
| 9 | All services | Final cross-service verification |

**Total new files:** ~24 (3 new services × 7 files + 1 new hook file in svc-skills + 1 new test file)
**Total modified files:** ~10 (hook.py + tests in approval, routing, todo, skills)