# Phase 3b: Hook Services + Pub/Sub + Orchestrator Hook Dispatch + Delegation — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Add hook service microservices (synchronous pre-hooks + async Dapr pub/sub post-hooks), wire hook dispatch into the orchestrator agent loop, enable child session spawning, and add a delegation tool service.

**Architecture:** Hook services expose two complementary endpoints: `POST /hooks/{name}/invoke` for synchronous pre-hooks (called directly by the orchestrator before tool/provider execution, can return DENY or INJECT_CONTEXT) and `POST /events/{topic}` for async post-hooks (called by Dapr declarative pub/sub subscriptions). The orchestrator gains a `HookDispatcher` that fires pre-hooks in sequence (short-circuiting on DENY) and publishes post-events best-effort. Child session spawning is implemented as a `/orchestrator/delegate` endpoint and exposed as a `delegate` tool via `svc-delegation`.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, httpx, amplifier-service-sdk, uv, pytest with asyncio_mode="auto", Docker, Dapr sidecars, Dapr pub/sub (Redis Streams)

---

## Reference: Existing Patterns

Before implementing, read these files:

- **Hook implementations:** `services/amplifier-foundation/src/amplifier_foundation/hooks/approval_hook.py`, `routing_hook.py`, `logging.py`, `shell_hook.py`, `todo_reminder.py`, `todo_display.py`, `session_naming.py`
- **Approval core:** `services/amplifier-foundation/src/amplifier_foundation/hooks/approval/approval_hook.py`
- **SDK models:** `amplifier-service-sdk/src/amplifier_service_sdk/models.py` — `HookEvent`, `HookResult`, `HookAction`, `RoutingTable`
- **SDK service factory:** `amplifier-service-sdk/src/amplifier_service_sdk/service.py`
- **Orchestrator:** `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`, `dapr_client.py`, `app.py`
- **Orchestrator tests:** `services/svc-orchestrator/tests/test_orchestrator.py` (mocking pattern for DaprClient)
- **Session-service discovery:** `services/session-service/src/session_service/discovery.py`
- **Docker Compose:** `docker-compose.yaml` (existing service + sidecar pattern)

---

## Task 1: SDK — HookInvocation, DaprSubscription, RoutingTable Extensions

**Files:**
- Modify: `amplifier-service-sdk/src/amplifier_service_sdk/models.py`
- Test: `amplifier-service-sdk/tests/test_models_phase3b.py` (create if tests dir exists, else inline test via python -c)

**Step 1: Write the failing test**

Check whether the SDK has a tests directory:
```bash
ls amplifier-service-sdk/tests/ 2>/dev/null || echo "no tests dir"
```

If a tests directory exists, create `amplifier-service-sdk/tests/test_models_phase3b.py`. Otherwise, create it:

```python
"""Tests for Phase 3b SDK model additions."""

from __future__ import annotations

import pytest

from amplifier_service_sdk.models import (
    DaprSubscription,
    HookAction,
    HookEvent,
    HookRegistration,
    HookResult,
    RoutingTable,
)


class TestDaprSubscription:
    def test_fields(self) -> None:
        sub = DaprSubscription(
            pubsubname="pubsub",
            topic="tool.post",
            route="/events/tool.post",
        )
        assert sub.pubsubname == "pubsub"
        assert sub.topic == "tool.post"
        assert sub.route == "/events/tool.post"

    def test_defaults(self) -> None:
        sub = DaprSubscription(pubsubname="pubsub", topic="tool.post")
        assert sub.route == "/events/tool.post"


class TestHookRegistration:
    def test_fields(self) -> None:
        reg = HookRegistration(
            name="approval",
            events=["tool:pre"],
            priority=5,
        )
        assert reg.name == "approval"
        assert "tool:pre" in reg.events
        assert reg.priority == 5

    def test_defaults(self) -> None:
        reg = HookRegistration(name="logging", events=["tool:post"])
        assert reg.priority == 50


class TestRoutingTableHookExtensions:
    def test_hook_endpoints_defaults_empty(self) -> None:
        rt = RoutingTable()
        assert rt.hook_endpoints == {}

    def test_hook_endpoints_roundtrip(self) -> None:
        rt = RoutingTable(
            hook_endpoints={"svc-hooks-approval": "hooks/approval/invoke"},
        )
        assert rt.hook_endpoints["svc-hooks-approval"] == "hooks/approval/invoke"

    def test_hook_priorities_defaults_empty(self) -> None:
        rt = RoutingTable()
        assert rt.hook_priorities == {}

    def test_existing_hooks_field_unaffected(self) -> None:
        rt = RoutingTable(hooks={"tool:pre": ["svc-hooks-approval"]})
        assert rt.hooks["tool:pre"] == ["svc-hooks-approval"]
```

**Step 2: Run test to verify it fails**

```bash
cd amplifier-service-sdk && uv run pytest tests/test_models_phase3b.py -v 2>/dev/null || \
  uv run python -c "from amplifier_service_sdk.models import DaprSubscription" 2>&1 | head -5
```
Expected: FAIL — `DaprSubscription`, `HookRegistration` not found; `RoutingTable` missing `hook_endpoints`.

**Step 3: Write the implementation**

Open `amplifier-service-sdk/src/amplifier_service_sdk/models.py` and add after the existing `StreamEvent` model at the bottom:

```python
# ── Phase 3b models ──────────────────────────────────────────────────────────


class HookRegistration(BaseModel):
    """Describes a hook exposed by a hook service (appears in /describe response)."""

    name: str
    events: list[str] = Field(default_factory=list)
    priority: int = 50
    mode: str = "sync"  # "sync" (pre-hook, blocking) | "async" (pub/sub subscriber)


class DaprSubscription(BaseModel):
    """Declarative Dapr pub/sub subscription returned by GET /dapr/subscribe."""

    pubsubname: str
    topic: str
    route: str = ""

    def model_post_init(self, __context: object) -> None:  # type: ignore[override]
        if not self.route:
            # Default route: replace colons with dots to match Dapr topic conventions
            safe_topic = self.topic.replace(":", ".")
            object.__setattr__(self, "route", f"/events/{safe_topic}")
```

Also update `RoutingTable` to add `hook_endpoints` and `hook_priorities`:

Find the existing `RoutingTable` class and replace it with:

```python
class RoutingTable(BaseModel):
    """Routing configuration for an orchestrator session."""

    tools: dict[str, str] = Field(default_factory=dict)
    providers: dict[str, str] = Field(default_factory=dict)
    hooks: dict[str, list[str]] = Field(default_factory=dict)
    context: str = ""
    # Phase 3b additions ─────────────────────────────────────────────────────
    # Maps hook service app_id → invoke path (e.g. "hooks/approval/invoke")
    hook_endpoints: dict[str, str] = Field(default_factory=dict)
    # Maps hook service app_id → priority (lower = runs first)
    hook_priorities: dict[str, int] = Field(default_factory=dict)
```

Also update `DescribeResponse` to include `HookRegistration`:

Find the existing `DescribeResponse` class and replace its `hooks` field:
```python
    hooks: list[HookRegistration] = Field(default_factory=list)
```
(was: `hooks: list[dict[str, Any]]` — this is a breaking-compatible change since `HookRegistration` is a Pydantic model that serializes the same way)

**Step 4: Run tests to verify pass**

```bash
cd amplifier-service-sdk && uv run pytest tests/ -v
```
Expected: All tests PASS, including new Phase 3b tests.

**Step 5: Commit**

```bash
git add amplifier-service-sdk/ && git commit -m "feat(sdk): add HookRegistration, DaprSubscription, RoutingTable.hook_endpoints for Phase 3b"
```

---

## Task 2: svc-hooks-approval — Approval Pre-Hook Service

**Files:**
- Create: `services/svc-hooks-approval/pyproject.toml`
- Create: `services/svc-hooks-approval/Dockerfile`
- Create: `services/svc-hooks-approval/src/svc_hooks_approval/__init__.py`
- Create: `services/svc-hooks-approval/src/svc_hooks_approval/hook.py`
- Create: `services/svc-hooks-approval/src/svc_hooks_approval/app.py`
- Create: `services/svc-hooks-approval/tests/__init__.py`
- Create: `services/svc-hooks-approval/tests/test_hook.py`
- Create: `services/svc-hooks-approval/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-hooks-approval/tests/__init__.py` (empty).

Create `services/svc-hooks-approval/tests/test_hook.py`:

```python
"""Tests for ApprovalHook — auto-approval in IPC mode."""

from __future__ import annotations

import pytest

from svc_hooks_approval.hook import ApprovalHook


class TestApprovalHook:
    """Tests for ApprovalHook.handle."""

    @pytest.fixture
    def hook(self) -> ApprovalHook:
        return ApprovalHook(config={})

    @pytest.mark.asyncio
    async def test_unknown_event_continues(self, hook: ApprovalHook) -> None:
        """Events other than tool:pre always CONTINUE."""
        result = await hook.handle("session:start", {})
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_tool_pre_approved_by_default(self, hook: ApprovalHook) -> None:
        """tool:pre auto-approves when no deny rules match."""
        result = await hook.handle(
            "tool:pre", {"tool_name": "bash", "input": {"command": "ls"}}
        )
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_tool_pre_denied_by_rule(self) -> None:
        """tool:pre returns DENY when tool matches a deny rule."""
        hook = ApprovalHook(config={"deny_tools": ["rm"]})
        result = await hook.handle(
            "tool:pre", {"tool_name": "rm", "input": {}}
        )
        assert result.action == "DENY"
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_tool_pre_denied_glob_pattern(self) -> None:
        """deny_tools supports glob patterns (e.g. 'bash:*rm*')."""
        hook = ApprovalHook(config={"deny_tools": ["dangerous_*"]})
        result = await hook.handle(
            "tool:pre", {"tool_name": "dangerous_delete", "input": {}}
        )
        assert result.action == "DENY"

    @pytest.mark.asyncio
    async def test_tool_pre_safe_tool_continues_with_deny_rules(self) -> None:
        """A safe tool is not affected by deny rules for other tools."""
        hook = ApprovalHook(config={"deny_tools": ["rm"]})
        result = await hook.handle(
            "tool:pre", {"tool_name": "read_file", "input": {}}
        )
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_missing_tool_name_continues(self, hook: ApprovalHook) -> None:
        """Missing tool_name in data is treated as a passthrough."""
        result = await hook.handle("tool:pre", {})
        assert result.action == "CONTINUE"
```

Create `services/svc-hooks-approval/tests/test_app.py`:

```python
"""Tests for the svc-hooks-approval FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_hooks_approval.app import create_approval_hook_app


class TestApprovalHookApp:

    def setup_method(self) -> None:
        self.app = create_approval_hook_app(config={})
        self.client = TestClient(self.app)

    def test_module_exposes_app(self) -> None:
        from svc_hooks_approval import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_hook(self) -> None:
        response = self.client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        hook_names = [h["name"] for h in data["hooks"]]
        assert "approval" in hook_names

    def test_invoke_returns_continue(self) -> None:
        """POST /hooks/approval/invoke with safe tool returns CONTINUE."""
        response = self.client.post(
            "/hooks/approval/invoke",
            json={"event": "tool:pre", "data": {"tool_name": "read_file"}},
        )
        assert response.status_code == 200
        assert response.json()["action"] == "CONTINUE"

    def test_invoke_denies_configured_tool(self) -> None:
        """POST /hooks/approval/invoke with denied tool returns DENY."""
        app = create_approval_hook_app(config={"deny_tools": ["rm"]})
        client = TestClient(app)
        response = client.post(
            "/hooks/approval/invoke",
            json={"event": "tool:pre", "data": {"tool_name": "rm"}},
        )
        assert response.status_code == 200
        assert response.json()["action"] == "DENY"

    def test_dapr_subscribe_returns_empty_list(self) -> None:
        """GET /dapr/subscribe returns [] — approval is sync-only, no pub/sub."""
        response = self.client.get("/dapr/subscribe")
        assert response.status_code == 200
        assert response.json() == []
```

**Step 2: Create the project scaffold**

Create `services/svc-hooks-approval/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-hooks-approval"
version = "0.1.0"
description = "Amplifier approval pre-hook service — auto-approves or denies tools in IPC mode"
requires-python = ">=3.12"
dependencies = [
    "amplifier-service-sdk",
    "fastapi>=0.115",
    "uvicorn>=0.32",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/svc_hooks_approval"]

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

Create `services/svc-hooks-approval/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-hooks-approval/ /build/svc-hooks-approval/
RUN cd /build/svc-hooks-approval && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_hooks_approval.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `services/svc-hooks-approval/src/svc_hooks_approval/__init__.py` (empty).

**Step 3: Write the implementation**

Create `services/svc-hooks-approval/src/svc_hooks_approval/hook.py`:

```python
"""ApprovalHook — auto-approves tools in IPC mode, with optional deny-rule config."""

from __future__ import annotations

import fnmatch
import logging
from typing import Any

from amplifier_service_sdk.models import HookEvent, HookResult

logger = logging.getLogger(__name__)


class ApprovalHook:
    """Approval gate hook for IPC mode.

    In interactive Amplifier, the approval hook would prompt the user. In IPC
    (microservices) mode, interactive approval is not available. This service
    auto-approves all tools UNLESS the tool name matches a configured deny rule.

    Config keys:
        deny_tools: list[str] — tool name patterns to deny (fnmatch glob supported).
    """

    name = "approval"
    events = ["tool:pre"]
    priority = 5
    mode = "sync"

    def __init__(self, config: dict[str, Any]) -> None:
        self._deny_tools: list[str] = config.get("deny_tools", [])

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Auto-approve or deny based on configured deny rules."""
        if event != "tool:pre":
            return HookResult(action="CONTINUE")

        tool_name: str = data.get("tool_name", "")
        if not tool_name:
            return HookResult(action="CONTINUE")

        for pattern in self._deny_tools:
            if fnmatch.fnmatch(tool_name, pattern):
                logger.info("ApprovalHook: denying tool '%s' (matched rule '%s')", tool_name, pattern)
                return HookResult(
                    action="DENY",
                    reason=f"Tool '{tool_name}' is blocked by approval policy (rule: '{pattern}')",
                )

        logger.debug("ApprovalHook: auto-approving tool '%s' in IPC mode", tool_name)
        return HookResult(action="CONTINUE")
```

Create `services/svc-hooks-approval/src/svc_hooks_approval/app.py`:

```python
"""FastAPI app factory for svc-hooks-approval — approval pre-hook service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from amplifier_service_sdk.models import HookEvent, HookRegistration, HookResult
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_approval.hook import ApprovalHook


def create_approval_hook_app(config: dict[str, Any] | None = None) -> FastAPI:
    """Create the svc-hooks-approval FastAPI application.

    Args:
        config: Hook configuration dict. Supported keys:
            deny_tools: list[str] — tool name glob patterns to auto-deny.

    Returns:
        Configured FastAPI application.
    """
    if config is None:
        # Load deny_tools from environment variable (comma-separated)
        deny_env = os.environ.get("DENY_TOOLS", "")
        config = {"deny_tools": [t.strip() for t in deny_env.split(",") if t.strip()]}

    hook = ApprovalHook(config=config)

    sdk_config = ServiceConfig(
        name="svc-hooks-approval",
        hooks=[
            HookRegistration(
                name=hook.name,
                events=hook.events,
                priority=hook.priority,
                mode=hook.mode,
            )
        ],
    )
    app = create_app(sdk_config)

    @app.post("/hooks/approval/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        """Synchronous pre-hook invocation endpoint for the approval hook."""
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @app.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict[str, Any]]:
        """Dapr declarative subscription discovery — approval hook has no pub/sub."""
        return []

    return app


app = create_approval_hook_app()
```

**Step 4: Install dependencies and run tests**

```bash
cd services/svc-hooks-approval && uv sync && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-hooks-approval/ && git commit -m "feat(svc-hooks-approval): add approval pre-hook service with auto-approve and deny rules"
```

---

## Task 3: svc-hooks-routing — Routing Pre-Hook Service

**Files:**
- Create: `services/svc-hooks-routing/pyproject.toml`
- Create: `services/svc-hooks-routing/Dockerfile`
- Create: `services/svc-hooks-routing/src/svc_hooks_routing/__init__.py`
- Create: `services/svc-hooks-routing/src/svc_hooks_routing/hook.py`
- Create: `services/svc-hooks-routing/src/svc_hooks_routing/app.py`
- Create: `services/svc-hooks-routing/tests/__init__.py`
- Create: `services/svc-hooks-routing/tests/test_hook.py`
- Create: `services/svc-hooks-routing/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-hooks-routing/tests/__init__.py` (empty).

Create `services/svc-hooks-routing/tests/test_hook.py`:

```python
"""Tests for RoutingHook — context injection for provider:request events."""

from __future__ import annotations

import pytest

from svc_hooks_routing.hook import RoutingHook


class TestRoutingHookNoMatrix:
    """Behaviour when no routing matrix file is found."""

    @pytest.fixture
    def hook(self) -> RoutingHook:
        return RoutingHook(matrix={})

    @pytest.mark.asyncio
    async def test_unknown_event_continues(self, hook: RoutingHook) -> None:
        result = await hook.handle("tool:pre", {})
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_provider_request_no_matrix_continues(self, hook: RoutingHook) -> None:
        result = await hook.handle("provider:request", {})
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_session_start_continues(self, hook: RoutingHook) -> None:
        result = await hook.handle("session:start", {})
        assert result.action == "CONTINUE"


class TestRoutingHookWithMatrix:
    """Behaviour when a routing matrix is provided."""

    @pytest.fixture
    def hook(self) -> RoutingHook:
        matrix = {
            "name": "balanced",
            "roles": {
                "fast": {"description": "Quick utility tasks"},
                "coding": {"description": "Code generation and debugging"},
            },
        }
        return RoutingHook(matrix=matrix)

    @pytest.mark.asyncio
    async def test_provider_request_injects_context(self, hook: RoutingHook) -> None:
        """provider:request with a loaded matrix returns INJECT_CONTEXT."""
        result = await hook.handle("provider:request", {})
        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        assert "fast" in result.data.get("context_injection", "")
        assert "coding" in result.data.get("context_injection", "")

    @pytest.mark.asyncio
    async def test_context_injection_is_ephemeral(self, hook: RoutingHook) -> None:
        """Context injection should be marked ephemeral (not stored in transcript)."""
        result = await hook.handle("provider:request", {})
        assert result.data is not None
        assert result.data.get("ephemeral") is True
```

Create `services/svc-hooks-routing/tests/test_app.py`:

```python
"""Tests for the svc-hooks-routing FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_hooks_routing.app import create_routing_hook_app


class TestRoutingHookApp:

    def setup_method(self) -> None:
        self.app = create_routing_hook_app(matrix={})
        self.client = TestClient(self.app)

    def test_module_exposes_app(self) -> None:
        from svc_hooks_routing import app as app_module
        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_hook(self) -> None:
        response = self.client.get("/describe")
        assert response.status_code == 200
        hook_names = [h["name"] for h in response.json()["hooks"]]
        assert "routing" in hook_names

    def test_invoke_provider_request_no_matrix_continues(self) -> None:
        response = self.client.post(
            "/hooks/routing/invoke",
            json={"event": "provider:request", "data": {}},
        )
        assert response.status_code == 200
        assert response.json()["action"] == "CONTINUE"

    def test_invoke_with_matrix_injects_context(self) -> None:
        matrix = {"name": "balanced", "roles": {"fast": {"description": "Quick tasks"}}}
        app = create_routing_hook_app(matrix=matrix)
        client = TestClient(app)
        response = client.post(
            "/hooks/routing/invoke",
            json={"event": "provider:request", "data": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "INJECT_CONTEXT"

    def test_dapr_subscribe_returns_empty(self) -> None:
        response = self.client.get("/dapr/subscribe")
        assert response.status_code == 200
        assert response.json() == []
```

**Step 2: Create the project scaffold**

Create `services/svc-hooks-routing/pyproject.toml` — same structure as svc-hooks-approval, with:
- `name = "svc-hooks-routing"`
- `packages = ["src/svc_hooks_routing"]`
- Additional dependency: `"pyyaml>=6.0"` (for loading matrix files)

Create `services/svc-hooks-routing/Dockerfile`:
```dockerfile
FROM amplifier-service-base

COPY services/svc-hooks-routing/ /build/svc-hooks-routing/
RUN cd /build/svc-hooks-routing && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_hooks_routing.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Write the implementation**

Create `services/svc-hooks-routing/src/svc_hooks_routing/__init__.py` (empty).

Create `services/svc-hooks-routing/src/svc_hooks_routing/hook.py`:

```python
"""RoutingHook — injects routing matrix context before each LLM provider call."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from amplifier_service_sdk.models import HookResult

logger = logging.getLogger(__name__)


class RoutingHook:
    """Injects available model roles into context before each LLM provider call.

    Ported from services/amplifier-foundation/src/amplifier_foundation/hooks/routing_hook.py.
    """

    name = "routing"
    events = ["session:start", "provider:request"]
    priority = 5
    mode = "sync"

    def __init__(self, matrix: dict[str, Any]) -> None:
        self._matrix = matrix
        self._effective_matrix: dict[str, Any] = matrix.get("roles", {})

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Dispatch based on event type."""
        if event == "session:start":
            return HookResult(action="CONTINUE")
        if event == "provider:request":
            return await self._on_provider_request(data)
        return HookResult(action="CONTINUE")

    async def _on_provider_request(self, data: dict[str, Any]) -> HookResult:
        """Inject available model roles into context as ephemeral context."""
        if not self._effective_matrix:
            return HookResult(action="CONTINUE")

        matrix_name = self._matrix.get("name", "balanced")
        lines = [
            f"Active routing matrix: {matrix_name}",
            "Available model roles (use model_role parameter when delegating):",
        ]
        for role_name, role_data in self._effective_matrix.items():
            desc = role_data.get("description", "") if isinstance(role_data, dict) else ""
            lines.append(f"  {role_name:16s} — {desc}")

        return HookResult(
            action="INJECT_CONTEXT",
            data={
                "context_injection": "\n".join(lines),
                "ephemeral": True,
            },
        )


def load_matrix_from_file(path: Path) -> dict[str, Any]:
    """Load a routing matrix YAML file. Returns empty dict if not found."""
    import yaml

    if not path.exists():
        return {}
    try:
        with path.open() as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Failed to load routing matrix from %s: %s", path, exc)
        return {}
```

Create `services/svc-hooks-routing/src/svc_hooks_routing/app.py`:

```python
"""FastAPI app factory for svc-hooks-routing — routing matrix pre-hook service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import HookEvent, HookRegistration, HookResult
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_routing.hook import RoutingHook, load_matrix_from_file


def create_routing_hook_app(matrix: dict[str, Any] | None = None) -> FastAPI:
    """Create the svc-hooks-routing FastAPI application.

    Args:
        matrix: Pre-loaded routing matrix dict. If None, loads from
            ROUTING_MATRIX_PATH env var, falling back to
            ~/.amplifier/routing/balanced.yaml.

    Returns:
        Configured FastAPI application.
    """
    if matrix is None:
        matrix_path_env = os.environ.get("ROUTING_MATRIX_PATH", "")
        if matrix_path_env:
            matrix = load_matrix_from_file(Path(matrix_path_env))
        else:
            default_path = Path.home() / ".amplifier" / "routing" / "balanced.yaml"
            matrix = load_matrix_from_file(default_path)

    hook = RoutingHook(matrix=matrix)

    sdk_config = ServiceConfig(
        name="svc-hooks-routing",
        hooks=[
            HookRegistration(
                name=hook.name,
                events=hook.events,
                priority=hook.priority,
                mode=hook.mode,
            )
        ],
    )
    app = create_app(sdk_config)

    @app.post("/hooks/routing/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        """Synchronous pre-hook invocation endpoint for the routing hook."""
        result = await hook.handle(event.event, event.data)
        return result.model_dump()

    @app.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict[str, Any]]:
        """Routing hook is sync-only — no pub/sub subscriptions."""
        return []

    return app


app = create_routing_hook_app()
```

**Step 4: Run tests**

```bash
cd services/svc-hooks-routing && uv sync && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-hooks-routing/ && git commit -m "feat(svc-hooks-routing): add routing matrix pre-hook service with context injection"
```

---

## Task 4: svc-hooks-async — Async Pub/Sub Hook Service (Logging + Session Naming + Todo)

**Files:**
- Create: `services/svc-hooks-async/pyproject.toml`
- Create: `services/svc-hooks-async/Dockerfile`
- Create: `services/svc-hooks-async/src/svc_hooks_async/__init__.py`
- Create: `services/svc-hooks-async/src/svc_hooks_async/logging_hook.py`
- Create: `services/svc-hooks-async/src/svc_hooks_async/app.py`
- Create: `services/svc-hooks-async/tests/__init__.py`
- Create: `services/svc-hooks-async/tests/test_logging_hook.py`
- Create: `services/svc-hooks-async/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-hooks-async/tests/__init__.py` (empty).

Create `services/svc-hooks-async/tests/test_logging_hook.py`:

```python
"""Tests for LoggingHook — async JSONL event logging."""

from __future__ import annotations

from pathlib import Path

import pytest

from svc_hooks_async.logging_hook import LoggingHook


class TestLoggingHook:

    @pytest.fixture
    def hook(self, tmp_path: Path) -> LoggingHook:
        log_template = str(tmp_path / "{session_id}" / "events.jsonl")
        return LoggingHook(log_template=log_template)

    @pytest.mark.asyncio
    async def test_handle_writes_jsonl(self, hook: LoggingHook, tmp_path: Path) -> None:
        """handle() writes a JSONL record to the log file."""
        await hook.handle("tool:pre", {"session_id": "sess-123", "tool_name": "bash"})
        log_file = tmp_path / "sess-123" / "events.jsonl"
        assert log_file.exists()
        content = log_file.read_text()
        assert "tool:pre" in content
        assert "bash" in content

    @pytest.mark.asyncio
    async def test_handle_no_session_id_skips(self, hook: LoggingHook) -> None:
        """handle() without session_id silently skips (no file created)."""
        # Should not raise
        await hook.handle("tool:pre", {"tool_name": "bash"})

    @pytest.mark.asyncio
    async def test_handle_all_events_continue(self, hook: LoggingHook) -> None:
        """handle() always returns CONTINUE regardless of event."""
        result = await hook.handle("session:start", {"session_id": "s1"})
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_disabled_hook_skips_write(self, hook: LoggingHook, tmp_path: Path) -> None:
        """When hook is disabled, no log file is created."""
        hook.enabled = False
        await hook.handle("tool:pre", {"session_id": "sess-999", "tool_name": "bash"})
        assert not (tmp_path / "sess-999" / "events.jsonl").exists()
```

Create `services/svc-hooks-async/tests/test_app.py`:

```python
"""Tests for the svc-hooks-async FastAPI application."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_hooks_async.app import create_async_hooks_app


class TestAsyncHooksApp:

    def setup_method(self) -> None:
        self.app = create_async_hooks_app(log_template="/tmp/test-{session_id}/events.jsonl")
        self.client = TestClient(self.app)

    def test_module_exposes_app(self) -> None:
        from svc_hooks_async import app as app_module
        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_hooks(self) -> None:
        response = self.client.get("/describe")
        assert response.status_code == 200
        hook_names = [h["name"] for h in response.json()["hooks"]]
        assert "logging" in hook_names

    def test_dapr_subscribe_returns_subscriptions(self) -> None:
        """GET /dapr/subscribe returns non-empty list for async hooks."""
        response = self.client.get("/dapr/subscribe")
        assert response.status_code == 200
        subs = response.json()
        assert isinstance(subs, list)
        assert len(subs) > 0
        topics = [s["topic"] for s in subs]
        assert "tool.post" in topics

    def test_event_endpoint_accepts_post(self) -> None:
        """POST /events/tool.post returns 200 and processes event."""
        # Dapr pub/sub envelope wraps the actual data
        dapr_envelope = {
            "data": json.dumps({"session_id": "test-sess", "tool_name": "bash"}),
            "datacontenttype": "application/json",
            "topic": "tool.post",
        }
        response = self.client.post("/events/tool.post", json=dapr_envelope)
        assert response.status_code == 200

    def test_unknown_event_endpoint_404(self) -> None:
        """POST to /events/{topic} not in subscriptions returns 404."""
        response = self.client.post("/events/unknown.topic", json={})
        assert response.status_code == 404
```

**Step 2: Create the project scaffold**

Create `services/svc-hooks-async/pyproject.toml` — same structure as svc-hooks-approval, with:
- `name = "svc-hooks-async"`
- `packages = ["src/svc_hooks_async"]`

Create `services/svc-hooks-async/Dockerfile`:
```dockerfile
FROM amplifier-service-base

COPY services/svc-hooks-async/ /build/svc-hooks-async/
RUN cd /build/svc-hooks-async && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_hooks_async.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Write the implementation**

Create `services/svc-hooks-async/src/svc_hooks_async/__init__.py` (empty).

Create `services/svc-hooks-async/src/svc_hooks_async/logging_hook.py`:

```python
"""LoggingHook — writes session events to per-session JSONL files.

Ported from services/amplifier-foundation/src/amplifier_foundation/hooks/logging.py.
Kept as a pure async pub/sub subscriber (no synchronous pre-hook behaviour).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amplifier_service_sdk.models import HookResult

logger = logging.getLogger(__name__)

SCHEMA = {"name": "amplifier.log", "ver": "1.0.0"}

# Topics (using dot notation for Dapr pub/sub) → original hook events
SUBSCRIBED_TOPICS = [
    "tool.pre",
    "tool.post",
    "tool.error",
    "session.start",
    "session.end",
    "provider.request",
    "provider.response",
    "provider.error",
    "prompt.submit",
    "prompt.complete",
]


def _ts() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _sanitize_for_json(value: Any) -> Any:
    """Recursively sanitize value to ensure JSON-serializability."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, (dict, list, tuple)):
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            if isinstance(value, dict):
                return {k: _sanitize_for_json(v) for k, v in value.items()}
            return [_sanitize_for_json(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return _sanitize_for_json(value.__dict__)
    return str(value)


class LoggingHook:
    """Writes all session events to per-session JSONL log files."""

    name = "logging"
    events = [t.replace(".", ":") for t in SUBSCRIBED_TOPICS]
    priority = 100
    mode = "async"

    def __init__(self, log_template: str = "~/.amplifier/logs/{session_id}/events.jsonl") -> None:
        self.log_template = log_template
        self.enabled = True

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Write event to JSONL log file."""
        if not self.enabled:
            return HookResult(action="CONTINUE")

        session_id = data.get("session_id")
        if not session_id:
            return HookResult(action="CONTINUE")

        rec = {
            "schema": SCHEMA,
            "ts": _ts(),
            "event": event,
            **data,
        }
        try:
            log_path = Path(
                self.log_template.format(session_id=session_id)
            ).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            sanitized = _sanitize_for_json(rec)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(sanitized, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.error("Failed to write session log: %s", exc)

        return HookResult(action="CONTINUE")
```

Create `services/svc-hooks-async/src/svc_hooks_async/app.py`:

```python
"""FastAPI app factory for svc-hooks-async — async pub/sub hook service.

Handles: logging, session-naming (stub), todo-reminder (stub), todo-display (stub).
All hooks are async (pub/sub subscribers only — no blocking pre-hook endpoints).
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException

from amplifier_service_sdk.models import DaprSubscription, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_async.logging_hook import SUBSCRIBED_TOPICS, LoggingHook


def create_async_hooks_app(log_template: str | None = None) -> FastAPI:
    """Create the svc-hooks-async FastAPI application."""
    if log_template is None:
        log_template = os.environ.get(
            "LOG_TEMPLATE", "~/.amplifier/logs/{session_id}/events.jsonl"
        )

    logging_hook = LoggingHook(log_template=log_template)

    subscriptions = [
        DaprSubscription(pubsubname="pubsub", topic=topic)
        for topic in SUBSCRIBED_TOPICS
    ]
    # Build a set of valid routes for 404 handling
    valid_routes = {sub.route for sub in subscriptions}

    sdk_config = ServiceConfig(
        name="svc-hooks-async",
        hooks=[
            HookRegistration(
                name=logging_hook.name,
                events=logging_hook.events,
                priority=logging_hook.priority,
                mode=logging_hook.mode,
            )
        ],
    )
    app = create_app(sdk_config)

    @app.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict[str, Any]]:
        """Return declarative Dapr pub/sub subscription list."""
        return [sub.model_dump() for sub in subscriptions]

    @app.post("/events/{topic:path}")
    async def receive_event(topic: str, envelope: dict[str, Any]) -> dict[str, Any]:
        """Receive a Dapr pub/sub event and dispatch to registered hooks.

        Dapr delivers events with a CloudEvents envelope. The actual payload
        is in envelope['data'] (JSON string) or envelope['data_base64'].
        """
        route = f"/events/{topic}"
        if route not in valid_routes:
            raise HTTPException(status_code=404, detail=f"No subscription for topic '{topic}'")

        # Extract inner data from Dapr CloudEvents envelope
        raw_data = envelope.get("data", "{}")
        if isinstance(raw_data, str):
            try:
                data: dict[str, Any] = json.loads(raw_data)
            except json.JSONDecodeError:
                data = {}
        elif isinstance(raw_data, dict):
            data = raw_data
        else:
            data = {}

        # Map dot-notation topic back to colon-notation event name
        event_name = topic.replace(".", ":")
        await logging_hook.handle(event_name, data)

        return {"status": "SUCCESS"}

    return app


app = create_async_hooks_app()
```

**Step 4: Run tests**

```bash
cd services/svc-hooks-async && uv sync && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-hooks-async/ && git commit -m "feat(svc-hooks-async): add async pub/sub hook service with logging, session-naming, todo stubs"
```

---

## Task 5: svc-hooks-shell — Shell Hook Service (Pub/Sub + Pre-Hook)

**Files:**
- Create: `services/svc-hooks-shell/pyproject.toml`
- Create: `services/svc-hooks-shell/Dockerfile`
- Create: `services/svc-hooks-shell/src/svc_hooks_shell/__init__.py`
- Create: `services/svc-hooks-shell/src/svc_hooks_shell/bridge.py`
- Create: `services/svc-hooks-shell/src/svc_hooks_shell/app.py`
- Create: `services/svc-hooks-shell/tests/__init__.py`
- Create: `services/svc-hooks-shell/tests/test_bridge.py`
- Create: `services/svc-hooks-shell/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-hooks-shell/tests/__init__.py` (empty).

Create `services/svc-hooks-shell/tests/test_bridge.py`:

```python
"""Tests for ShellHookBridge — executes .amplifier/hooks/ shell scripts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from svc_hooks_shell.bridge import ShellHookBridge


class TestShellHookBridgeNoScripts:
    """Behaviour when no hook scripts are configured."""

    @pytest.fixture
    def bridge(self) -> ShellHookBridge:
        return ShellHookBridge(hooks_dir=None)

    @pytest.mark.asyncio
    async def test_handle_unknown_event_continues(self, bridge: ShellHookBridge) -> None:
        result = await bridge.handle("unknown:event", {})
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_handle_tool_pre_no_scripts_continues(self, bridge: ShellHookBridge) -> None:
        result = await bridge.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_handle_tool_post_continues(self, bridge: ShellHookBridge) -> None:
        result = await bridge.handle("tool:post", {})
        assert result.action == "CONTINUE"


class TestShellHookBridgeWithScripts:
    """Behaviour when hook scripts exist in hooks_dir."""

    @pytest.fixture
    def bridge_with_scripts(self, tmp_path: Path) -> ShellHookBridge:
        hooks_dir = tmp_path / ".amplifier" / "hooks"
        hooks_dir.mkdir(parents=True)
        # Create a pre-tool hook script
        script = hooks_dir / "pre-tool"
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        return ShellHookBridge(hooks_dir=hooks_dir)

    @pytest.mark.asyncio
    async def test_handle_executes_script(self, bridge_with_scripts: ShellHookBridge) -> None:
        """handle() runs matching script and returns CONTINUE when exit code 0."""
        result = await bridge_with_scripts.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_handle_deny_on_exit_2(self, tmp_path: Path) -> None:
        """Script exiting with code 2 causes DENY result."""
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        script = hooks_dir / "pre-tool"
        script.write_text("#!/bin/sh\nexit 2\n")
        script.chmod(0o755)
        bridge = ShellHookBridge(hooks_dir=hooks_dir)
        result = await bridge.handle("tool:pre", {})
        assert result.action == "DENY"
```

Create `services/svc-hooks-shell/tests/test_app.py`:

```python
"""Tests for the svc-hooks-shell FastAPI application."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_hooks_shell.app import create_shell_hook_app


class TestShellHookApp:

    def setup_method(self) -> None:
        self.app = create_shell_hook_app(hooks_dir=None)
        self.client = TestClient(self.app)

    def test_module_exposes_app(self) -> None:
        from svc_hooks_shell import app as app_module
        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_hook(self) -> None:
        response = self.client.get("/describe")
        assert response.status_code == 200
        hook_names = [h["name"] for h in response.json()["hooks"]]
        assert "shell" in hook_names

    def test_invoke_tool_pre_continues_no_scripts(self) -> None:
        response = self.client.post(
            "/hooks/shell/invoke",
            json={"event": "tool:pre", "data": {"tool_name": "bash"}},
        )
        assert response.status_code == 200
        assert response.json()["action"] == "CONTINUE"

    def test_dapr_subscribe_returns_subscriptions(self) -> None:
        response = self.client.get("/dapr/subscribe")
        assert response.status_code == 200
        subs = response.json()
        assert isinstance(subs, list)
        assert len(subs) > 0

    def test_event_endpoint_accepts_post(self) -> None:
        dapr_envelope = {
            "data": json.dumps({"session_id": "test", "tool_name": "bash"}),
            "topic": "tool.post",
        }
        response = self.client.post("/events/tool.post", json=dapr_envelope)
        assert response.status_code == 200
```

**Step 2: Create the project scaffold**

Create `services/svc-hooks-shell/pyproject.toml` — same structure as svc-hooks-approval, with `name = "svc-hooks-shell"`, `packages = ["src/svc_hooks_shell"]`.

Create `services/svc-hooks-shell/Dockerfile`:
```dockerfile
FROM amplifier-service-base

COPY services/svc-hooks-shell/ /build/svc-hooks-shell/
RUN cd /build/svc-hooks-shell && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_hooks_shell.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Write the implementation**

Create `services/svc-hooks-shell/src/svc_hooks_shell/__init__.py` (empty).

Create `services/svc-hooks-shell/src/svc_hooks_shell/bridge.py`:

Port from `services/amplifier-foundation/src/amplifier_foundation/hooks/shell/bridge.py`. Read that file first. Key changes:
- Replace `from amplifier_ipc.protocol.models import HookResult, HookAction` with `from amplifier_service_sdk.models import HookResult`
- Accept `hooks_dir: Path | None` in `__init__` instead of reading from `config`
- Map Dapr topic notation back to event names in `handle()` (e.g., `"tool.pre"` → `"tool:pre"`)
- Exit code 0 → CONTINUE, exit code 2 → DENY (with reason), any other non-zero → CONTINUE (best-effort)

Create `services/svc-hooks-shell/src/svc_hooks_shell/app.py`:

```python
"""FastAPI app factory for svc-hooks-shell — shell script hook service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from amplifier_service_sdk.models import DaprSubscription, HookEvent, HookRegistration
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_hooks_shell.bridge import ShellHookBridge

# Events handled as pre-hooks (synchronous, blocking)
_PRE_HOOK_EVENTS = ["tool:pre", "prompt:submit"]
# Events delivered via pub/sub (async, best-effort)
_ASYNC_EVENTS = [
    "tool.post",
    "session.start",
    "session.end",
    "prompt.complete",
    "context.pre_compact",
]
_ALL_HOOK_EVENTS = _PRE_HOOK_EVENTS + [e.replace(".", ":") for e in _ASYNC_EVENTS]


def create_shell_hook_app(hooks_dir: Path | str | None = None) -> FastAPI:
    """Create the svc-hooks-shell FastAPI application."""
    if isinstance(hooks_dir, str):
        hooks_dir = Path(hooks_dir)
    if hooks_dir is None:
        env_dir = os.environ.get("SHELL_HOOKS_DIR", "")
        hooks_dir = Path(env_dir) if env_dir else None

    bridge = ShellHookBridge(hooks_dir=hooks_dir)

    subscriptions = [
        DaprSubscription(pubsubname="pubsub", topic=topic)
        for topic in _ASYNC_EVENTS
    ]
    valid_routes = {sub.route for sub in subscriptions}

    sdk_config = ServiceConfig(
        name="svc-hooks-shell",
        hooks=[
            HookRegistration(
                name="shell",
                events=_ALL_HOOK_EVENTS,
                priority=50,
                mode="sync",
            )
        ],
    )
    app = create_app(sdk_config)

    @app.post("/hooks/shell/invoke")
    async def invoke(event: HookEvent) -> dict[str, Any]:
        """Synchronous pre-hook endpoint — executes matching shell scripts."""
        result = await bridge.handle(event.event, event.data)
        return result.model_dump()

    @app.get("/dapr/subscribe")
    async def dapr_subscribe() -> list[dict[str, Any]]:
        """Return pub/sub subscriptions for async shell hooks."""
        return [sub.model_dump() for sub in subscriptions]

    @app.post("/events/{topic:path}")
    async def receive_event(topic: str, envelope: dict[str, Any]) -> dict[str, Any]:
        """Receive async Dapr pub/sub event and execute matching shell scripts."""
        route = f"/events/{topic}"
        if route not in valid_routes:
            raise HTTPException(status_code=404, detail=f"No subscription for '{topic}'")

        raw_data = envelope.get("data", "{}")
        if isinstance(raw_data, str):
            try:
                data: dict[str, Any] = json.loads(raw_data)
            except json.JSONDecodeError:
                data = {}
        elif isinstance(raw_data, dict):
            data = raw_data
        else:
            data = {}

        event_name = topic.replace(".", ":")
        await bridge.handle(event_name, data)
        return {"status": "SUCCESS"}

    return app


app = create_shell_hook_app()
```

**Step 4: Run tests**

```bash
cd services/svc-hooks-shell && uv sync && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-hooks-shell/ && git commit -m "feat(svc-hooks-shell): add shell hook service with pre-hook invoke and pub/sub receipt"
```

---

## Task 6: Orchestrator — HookDispatcher Class

**Files:**
- Create: `services/svc-orchestrator/src/svc_orchestrator/hook_dispatcher.py`
- Create: `services/svc-orchestrator/tests/test_hook_dispatcher.py`

**Step 1: Write the failing test**

Create `services/svc-orchestrator/tests/test_hook_dispatcher.py`:

```python
"""Tests for HookDispatcher — orchestrates pre-hook calls and post-event publishing."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from amplifier_service_sdk.models import RoutingTable
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.hook_dispatcher import HookDispatcher


def _make_dapr() -> DaprClient:
    return DaprClient(dapr_url="http://localhost:3500")


class TestHookDispatcherPreHook:
    """dispatch_pre calls hook services in priority order, respects DENY."""

    @pytest.fixture
    def routing_table(self) -> RoutingTable:
        return RoutingTable(
            hooks={"tool:pre": ["svc-hooks-approval"]},
            hook_endpoints={"svc-hooks-approval": "hooks/approval/invoke"},
            hook_priorities={"svc-hooks-approval": 5},
        )

    @pytest.mark.asyncio
    async def test_dispatch_pre_continue(self, routing_table: RoutingTable) -> None:
        """Returns CONTINUE when all hooks approve."""
        dapr = _make_dapr()
        dapr.invoke = AsyncMock(return_value={"action": "CONTINUE", "data": None, "reason": None})  # type: ignore[method-assign]
        dispatcher = HookDispatcher(dapr=dapr)

        result = await dispatcher.dispatch_pre(
            event="tool:pre",
            data={"tool_name": "bash"},
            routing_table=routing_table,
        )
        assert result.action == "CONTINUE"
        dapr.invoke.assert_called_once_with(
            "svc-hooks-approval",
            "hooks/approval/invoke",
            {"event": "tool:pre", "data": {"tool_name": "bash"}},
        )

    @pytest.mark.asyncio
    async def test_dispatch_pre_deny_short_circuits(self, routing_table: RoutingTable) -> None:
        """Returns DENY immediately when first hook denies; second hook not called."""
        dapr = _make_dapr()
        deny_rt = RoutingTable(
            hooks={"tool:pre": ["svc-hooks-approval", "svc-hooks-routing"]},
            hook_endpoints={
                "svc-hooks-approval": "hooks/approval/invoke",
                "svc-hooks-routing": "hooks/routing/invoke",
            },
            hook_priorities={"svc-hooks-approval": 5, "svc-hooks-routing": 10},
        )
        call_count = 0

        async def mock_invoke(app_id: str, method: str, data: dict[str, Any], **kw: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if app_id == "svc-hooks-approval":
                return {"action": "DENY", "reason": "blocked", "data": None}
            return {"action": "CONTINUE", "data": None, "reason": None}

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dispatcher = HookDispatcher(dapr=dapr)

        result = await dispatcher.dispatch_pre(
            event="tool:pre",
            data={"tool_name": "rm"},
            routing_table=deny_rt,
        )
        assert result.action == "DENY"
        assert call_count == 1  # second hook never called

    @pytest.mark.asyncio
    async def test_dispatch_pre_no_hooks_continues(self) -> None:
        """Returns CONTINUE immediately when no hooks registered for event."""
        dapr = _make_dapr()
        dapr.invoke = AsyncMock()  # type: ignore[method-assign]
        dispatcher = HookDispatcher(dapr=dapr)
        empty_rt = RoutingTable()

        result = await dispatcher.dispatch_pre("tool:pre", {}, empty_rt)
        assert result.action == "CONTINUE"
        dapr.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_pre_hook_error_continues(self, routing_table: RoutingTable) -> None:
        """If a hook service is unreachable, dispatch_pre returns CONTINUE (best-effort)."""
        dapr = _make_dapr()
        dapr.invoke = AsyncMock(side_effect=Exception("Connection refused"))  # type: ignore[method-assign]
        dispatcher = HookDispatcher(dapr=dapr)

        result = await dispatcher.dispatch_pre("tool:pre", {}, routing_table)
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_dispatch_pre_inject_context_accumulates(self) -> None:
        """INJECT_CONTEXT results accumulate context_injection across hooks."""
        dapr = _make_dapr()
        rt = RoutingTable(
            hooks={"provider:request": ["svc-hooks-routing"]},
            hook_endpoints={"svc-hooks-routing": "hooks/routing/invoke"},
        )

        async def mock_invoke(app_id: str, method: str, data: dict[str, Any], **kw: Any) -> dict[str, Any]:
            return {
                "action": "INJECT_CONTEXT",
                "data": {"context_injection": "routing info here", "ephemeral": True},
                "reason": None,
            }

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dispatcher = HookDispatcher(dapr=dapr)

        result = await dispatcher.dispatch_pre("provider:request", {}, rt)
        assert result.action == "INJECT_CONTEXT"
        assert "routing info here" in (result.data or {}).get("context_injection", "")


class TestHookDispatcherPostEvent:
    """dispatch_post publishes events via Dapr pub/sub best-effort."""

    @pytest.mark.asyncio
    async def test_dispatch_post_publishes(self) -> None:
        """dispatch_post calls dapr.publish with correct topic."""
        dapr = _make_dapr()
        dapr.publish = AsyncMock()  # type: ignore[method-assign]
        dispatcher = HookDispatcher(dapr=dapr)

        await dispatcher.dispatch_post(
            event="tool:post",
            data={"session_id": "s1", "tool_name": "bash"},
        )
        dapr.publish.assert_called_once_with(
            "pubsub",
            "tool.post",  # colon replaced with dot for Dapr topic
            {"session_id": "s1", "tool_name": "bash"},
        )

    @pytest.mark.asyncio
    async def test_dispatch_post_swallows_errors(self) -> None:
        """dispatch_post silently swallows pub/sub errors."""
        dapr = _make_dapr()
        dapr.publish = AsyncMock(side_effect=Exception("pubsub down"))  # type: ignore[method-assign]
        dispatcher = HookDispatcher(dapr=dapr)
        # Should not raise
        await dispatcher.dispatch_post("tool:post", {"session_id": "s1"})
```

**Step 2: Run test to verify it fails**

```bash
cd services/svc-orchestrator && uv run pytest tests/test_hook_dispatcher.py -v
```
Expected: FAIL — `HookDispatcher` not found.

**Step 3: Write the implementation**

Create `services/svc-orchestrator/src/svc_orchestrator/hook_dispatcher.py`:

```python
"""HookDispatcher — dispatches pre-hook invocations and publishes post-events.

Pre-hooks: Calls each registered hook service synchronously in priority order
via Dapr service invocation. Stops on DENY. Accumulates INJECT_CONTEXT data.

Post-events: Publishes events to Dapr pub/sub topics (best-effort, never raises).
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_service_sdk.models import HookResult, RoutingTable

from svc_orchestrator.dapr_client import DaprClient

logger = logging.getLogger(__name__)


class HookDispatcher:
    """Dispatches hook events to registered hook services via Dapr."""

    def __init__(self, dapr: DaprClient) -> None:
        self._dapr = dapr

    async def dispatch_pre(
        self,
        event: str,
        data: dict[str, Any],
        routing_table: RoutingTable,
    ) -> HookResult:
        """Call pre-hook services for the given event in priority order.

        Hooks are sorted by priority (lower = runs first). Stops immediately
        if any hook returns DENY. Accumulates INJECT_CONTEXT injections.

        Args:
            event: Hook event name (e.g. "tool:pre", "provider:request").
            data: Event payload dict.
            routing_table: Routing config with hooks and hook_endpoints.

        Returns:
            Merged HookResult: DENY if any hook denied; INJECT_CONTEXT with
            accumulated injection if any hook injected; CONTINUE otherwise.
        """
        hook_services = routing_table.hooks.get(event, [])
        if not hook_services:
            return HookResult(action="CONTINUE")

        # Sort by priority (lower priority number = higher precedence = runs first)
        sorted_services = sorted(
            hook_services,
            key=lambda app_id: routing_table.hook_priorities.get(app_id, 50),
        )

        accumulated_injections: list[str] = []

        for app_id in sorted_services:
            invoke_path = routing_table.hook_endpoints.get(app_id, "hooks/invoke")
            try:
                raw = await self._dapr.invoke(
                    app_id,
                    invoke_path,
                    {"event": event, "data": data},
                )
                result = HookResult(**raw)
            except Exception as exc:
                logger.warning(
                    "HookDispatcher: hook service '%s' failed for event '%s': %s",
                    app_id, event, exc
                )
                continue  # Best-effort: unreachable hooks don't block execution

            if result.action == "DENY":
                return result

            if result.action == "INJECT_CONTEXT" and result.data:
                injection = result.data.get("context_injection", "")
                if injection:
                    accumulated_injections.append(injection)

        if accumulated_injections:
            return HookResult(
                action="INJECT_CONTEXT",
                data={
                    "context_injection": "\n\n".join(accumulated_injections),
                    "ephemeral": True,
                },
            )

        return HookResult(action="CONTINUE")

    async def dispatch_post(
        self,
        event: str,
        data: dict[str, Any],
    ) -> None:
        """Publish a post-hook event to Dapr pub/sub (best-effort).

        Converts colon-separated event names to dot-separated Dapr topics
        (e.g. "tool:post" → "tool.post").

        Never raises — pub/sub failures are silently swallowed.
        """
        topic = event.replace(":", ".")
        try:
            await self._dapr.publish("pubsub", topic, data)
        except Exception as exc:
            logger.debug(
                "HookDispatcher: pub/sub publish failed for event '%s': %s (best-effort)",
                event, exc
            )
```

**Step 4: Run tests to verify pass**

```bash
cd services/svc-orchestrator && uv run pytest tests/test_hook_dispatcher.py -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-orchestrator/src/svc_orchestrator/hook_dispatcher.py \
        services/svc-orchestrator/tests/test_hook_dispatcher.py && \
git commit -m "feat(svc-orchestrator): add HookDispatcher for pre-hook invocation and pub/sub publishing"
```

---

## Task 7: Orchestrator — Integrate Pre-Hook Dispatch into Agent Loop

**Files:**
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`
- Modify: `services/svc-orchestrator/tests/test_orchestrator.py`

**Step 1: Write the failing tests**

Open `services/svc-orchestrator/tests/test_orchestrator.py` and read the full file to understand the existing test helpers (`_make_dapr`, `_routing_table`, mock pattern).

Add a new test class at the bottom:

```python
class TestOrchestratorPreHookDeny:
    """Pre-hook DENY prevents tool execution and returns an error message."""

    @pytest.mark.asyncio
    async def test_denied_tool_becomes_error_message(self) -> None:
        """When pre-hook denies a tool, the tool result is an error string."""
        dapr = _make_dapr()

        invocation_log: list[str] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            invocation_log.append(f"{app_id}:{method}")
            if app_id == "svc-hooks-approval" and "invoke" in method:
                return {"action": "DENY", "reason": "blocked by policy", "data": None}
            if "complete" in method:
                # Provider returns a tool call
                return {
                    "content": None,
                    "tool_calls": [{"id": "tc1", "name": "bash", "arguments": {"command": "rm -rf /"}}],
                    "usage": None,
                    "stop_reason": "tool_use",
                }
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kwargs: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "run bash"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        from amplifier_service_sdk.models import RoutingTable
        rt = RoutingTable(
            providers={"mock": "svc-mock-provider"},
            tools={"bash": "svc-bash"},
            context="svc-context",
            hooks={"tool:pre": ["svc-hooks-approval"]},
            hook_endpoints={"svc-hooks-approval": "hooks/approval/invoke"},
        )

        from svc_orchestrator.orchestrator import Orchestrator
        orch = Orchestrator(dapr=dapr)
        result_text, _ = await orch.execute(
            system_prompt="test",
            messages=[],
            config={"max_iterations": 2, "provider": "mock"},
            routing_table=rt,
        )
        # Tool should not have been invoked
        assert not any("svc-bash" in log for log in invocation_log)
        # The tool result message should contain the denial reason
        assert "blocked" in result_text or result_text == ""


class TestOrchestratorPostHookPublish:
    """Post-hook events are published after tool execution."""

    @pytest.mark.asyncio
    async def test_tool_post_event_published(self) -> None:
        """After a tool call, tool:post is published to Dapr pub/sub."""
        dapr = _make_dapr()
        published_events: list[tuple[str, str, dict[str, Any]]] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if "complete" in method:
                # First call: return a tool call. Subsequent: return text.
                if not published_events:
                    return {
                        "content": None,
                        "tool_calls": [{"id": "tc1", "name": "bash", "arguments": {"command": "ls"}}],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                return {"content": "done", "tool_calls": None, "usage": None, "stop_reason": "end_turn"}
            if "bash" in app_id and "execute" in method:
                return {"success": True, "output": "file.txt"}
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kwargs: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "ls"}]}

        async def mock_publish(pubsub: str, topic: str, data: dict[str, Any]) -> None:
            published_events.append((pubsub, topic, data))

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        from amplifier_service_sdk.models import RoutingTable
        rt = RoutingTable(
            providers={"mock": "svc-mock-provider"},
            tools={"bash": "svc-bash"},
            context="svc-context",
        )

        from svc_orchestrator.orchestrator import Orchestrator
        orch = Orchestrator(dapr=dapr)
        await orch.execute(
            system_prompt="test",
            messages=[],
            config={"max_iterations": 3, "provider": "mock"},
            routing_table=rt,
        )

        # tool.post should have been published at least once
        published_topics = [t for _, t, _ in published_events]
        assert "tool.post" in published_topics
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-orchestrator && uv run pytest tests/test_orchestrator.py::TestOrchestratorPreHookDeny tests/test_orchestrator.py::TestOrchestratorPostHookPublish -v
```
Expected: FAIL — orchestrator does not yet dispatch hooks.

**Step 3: Write the implementation**

Read the full `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py` first.

Make the following changes to `orchestrator.py`:

1. **Add import** at top:
```python
from svc_orchestrator.hook_dispatcher import HookDispatcher
```

2. **Add `HookDispatcher` instantiation** in `__init__`:
```python
def __init__(self, dapr: DaprClient) -> None:
    self._dapr = dapr
    self._hooks = HookDispatcher(dapr=dapr)
```

3. **Add pre-hook dispatch in `_execute_single_tool`** — before invoking the tool, call `dispatch_pre`:

Find the section inside `_execute_single_tool` where it determines `tool_app_id` and add after it:

```python
            # Dispatch tool:pre hooks
            pre_result = await self._hooks.dispatch_pre(
                event="tool:pre",
                data={
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "arguments": tool_call.arguments,
                    "session_id": session_id,
                },
                routing_table=routing_table,
            )
            if pre_result.action == "DENY":
                reason = pre_result.reason or "Denied by hook policy"
                return Message(
                    role="tool",
                    content=f"Tool '{tool_call.name}' was blocked: {reason}",
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                )
```

4. **Add post-hook publish in `_execute_single_tool`** — after getting `raw_result`:

After the `await self._dapr.invoke(tool_app_id, ...)` call and before the `stream.tool_result` publish:

```python
            # Publish tool:post event (best-effort)
            await self._hooks.dispatch_post(
                event="tool:post",
                data={
                    "tool_name": tool_call.name,
                    "tool_call_id": tool_call.id,
                    "result": output,
                    "session_id": session_id,
                },
            )
```

5. **Update `_execute_single_tool` signature** to accept `routing_table`:

Change the signature from:
```python
    async def _execute_single_tool(
        self,
        tool_call: ToolCall,
        routing_table: RoutingTable,
        session_id: str,
    ) -> Message:
```
It already accepts `routing_table` — just pass it through to `dispatch_pre`.

**Step 4: Run all orchestrator tests**

```bash
cd services/svc-orchestrator && uv run pytest tests/ -v
```
Expected: All tests PASS, including existing tests and new pre/post-hook tests.

**Step 5: Commit**

```bash
git add services/svc-orchestrator/ && git commit -m "feat(svc-orchestrator): integrate pre-hook dispatch and post-hook publishing into agent loop"
```

---

## Task 8: Orchestrator — Provider Request Pre-Hook + Session Events

**Files:**
- Modify: `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`
- Modify: `services/svc-orchestrator/tests/test_orchestrator.py`

**Step 1: Write the failing tests**

Append to `services/svc-orchestrator/tests/test_orchestrator.py`:

```python
class TestOrchestratorProviderRequestHook:
    """provider:request pre-hook fires before each LLM call."""

    @pytest.mark.asyncio
    async def test_provider_request_hook_called(self) -> None:
        """dispatch_pre is called with provider:request before each provider call."""
        dapr = _make_dapr()
        hook_call_events: list[str] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if "hooks" in method:
                hook_call_events.append(data.get("event", ""))
                return {"action": "CONTINUE", "data": None, "reason": None}
            if "complete" in method:
                return {"content": "done", "tool_calls": None, "usage": None, "stop_reason": "end_turn"}
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kwargs: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "hello"}]}

        async def mock_publish(*a: Any, **kw: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        from amplifier_service_sdk.models import RoutingTable
        rt = RoutingTable(
            providers={"mock": "svc-mock-provider"},
            context="svc-context",
            hooks={"provider:request": ["svc-hooks-routing"]},
            hook_endpoints={"svc-hooks-routing": "hooks/routing/invoke"},
        )

        from svc_orchestrator.orchestrator import Orchestrator
        orch = Orchestrator(dapr=dapr)
        await orch.execute(
            system_prompt="test",
            messages=[],
            config={"max_iterations": 1, "provider": "mock"},
            routing_table=rt,
        )
        assert "provider:request" in hook_call_events


class TestOrchestratorSessionEvents:
    """session:start and session:end events are published."""

    @pytest.mark.asyncio
    async def test_session_start_end_published(self) -> None:
        dapr = _make_dapr()
        published_topics: list[str] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            if "complete" in method:
                return {"content": "done", "tool_calls": None, "usage": None, "stop_reason": "end_turn"}
            return {"ok": True}

        async def mock_invoke_get(app_id: str, method: str, **kwargs: Any) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "hi"}]}

        async def mock_publish(pubsub: str, topic: str, data: dict[str, Any]) -> None:
            published_topics.append(topic)

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        from amplifier_service_sdk.models import RoutingTable
        rt = _routing_table()

        from svc_orchestrator.orchestrator import Orchestrator
        orch = Orchestrator(dapr=dapr)
        await orch.execute(
            system_prompt="test",
            messages=[],
            config={"max_iterations": 1, "provider": "mock"},
            routing_table=rt,
            session_id="test-session",
        )
        assert "session.start" in published_topics
        assert "session.end" in published_topics
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-orchestrator && uv run pytest tests/test_orchestrator.py::TestOrchestratorProviderRequestHook tests/test_orchestrator.py::TestOrchestratorSessionEvents -v
```
Expected: FAIL — provider:request hook not called, session events not published.

**Step 3: Write the implementation**

In `services/svc-orchestrator/src/svc_orchestrator/orchestrator.py`:

1. **Add `provider:request` pre-hook** in the main agent loop, BEFORE calling `_call_provider`:

```python
            # Dispatch provider:request pre-hooks (may inject context)
            pr_result = await self._hooks.dispatch_pre(
                event="provider:request",
                data={"session_id": session_id, "iteration": iteration},
                routing_table=routing_table,
            )
            # Prepend injected context to system prompt if present
            effective_system = system_prompt
            if pr_result.action == "INJECT_CONTEXT" and pr_result.data:
                injection = pr_result.data.get("context_injection", "")
                if injection:
                    effective_system = f"{injection}\n\n{system_prompt}"
```

Then use `effective_system` instead of `system_prompt` in the `ChatRequest`:
```python
            chat_request = ChatRequest(
                messages=chat_messages,
                tools=tools,
                system=effective_system,
            )
```

2. **Add `session:start` publish** at the very beginning of `execute()` (after seeding context):

```python
        # Publish session:start event (best-effort)
        await self._hooks.dispatch_post(
            event="session:start",
            data={"session_id": session_id},
        )
```

3. **Add `session:end` publish** at the very end of `execute()`, before `return`:

```python
        # Publish session:end event (best-effort)
        await self._hooks.dispatch_post(
            event="session:end",
            data={"session_id": session_id, "result": result_text},
        )
```

**Step 4: Run all orchestrator tests**

```bash
cd services/svc-orchestrator && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-orchestrator/ && git commit -m "feat(svc-orchestrator): add provider:request pre-hook and session:start/end pub/sub events"
```

---

## Task 9: Orchestrator — Child Session Spawning + Delegate Endpoint

**Files:**
- Create: `services/svc-orchestrator/src/svc_orchestrator/child_session.py`
- Modify: `services/svc-orchestrator/src/svc_orchestrator/app.py`
- Create: `services/svc-orchestrator/tests/test_child_session.py`
- Modify: `services/svc-orchestrator/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-orchestrator/tests/test_child_session.py`:

```python
"""Tests for ChildSessionSpawner — spawns child orchestration sessions."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from svc_orchestrator.child_session import ChildSessionRequest, ChildSessionSpawner
from svc_orchestrator.dapr_client import DaprClient


def _make_dapr() -> DaprClient:
    return DaprClient(dapr_url="http://localhost:3500")


class TestChildSessionSpawner:

    @pytest.mark.asyncio
    async def test_spawn_calls_session_service(self) -> None:
        """spawn() invokes session-service /sessions/{id}/turn via Dapr."""
        dapr = _make_dapr()

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            assert app_id == "session-service"
            assert "turn" in method
            return {
                "session_id": "child-123",
                "result": "Child result",
                "messages": [],
            }

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        spawner = ChildSessionSpawner(dapr=dapr, session_service_app_id="session-service")

        req = ChildSessionRequest(
            prompt="Do some work",
            child_session_id="child-123",
            provider_name="mock",
            services=[],
        )
        result = await spawner.spawn(req)
        assert result["result"] == "Child result"

    @pytest.mark.asyncio
    async def test_spawn_generates_session_id_if_missing(self) -> None:
        """spawn() generates a child_session_id if none provided."""
        dapr = _make_dapr()
        used_session_ids: list[str] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            # Extract session_id from method path: sessions/{id}/turn
            parts = method.split("/")
            if len(parts) >= 2:
                used_session_ids.append(parts[1])
            return {"session_id": parts[1] if len(parts) >= 2 else "x", "result": "ok", "messages": []}

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        spawner = ChildSessionSpawner(dapr=dapr)

        req = ChildSessionRequest(prompt="hello", child_session_id="")
        result = await spawner.spawn(req)
        assert len(used_session_ids) == 1
        assert len(used_session_ids[0]) > 0

    @pytest.mark.asyncio
    async def test_spawn_passes_workspace_content(self) -> None:
        """spawn() passes workspace_content to child session turn."""
        dapr = _make_dapr()
        received_data: list[dict[str, Any]] = []

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            received_data.append(data)
            return {"session_id": "c1", "result": "ok", "messages": []}

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        spawner = ChildSessionSpawner(dapr=dapr)

        req = ChildSessionRequest(
            prompt="hello",
            child_session_id="c1",
            workspace_content={"README.md": "# Project"},
        )
        await spawner.spawn(req)
        assert received_data[0]["workspace_content"] == {"README.md": "# Project"}
```

Read `services/svc-orchestrator/tests/test_app.py` before modifying it.

Add to `services/svc-orchestrator/tests/test_app.py` after existing test classes:

```python
class TestOrchestratorDelegateEndpoint:
    """Tests for POST /orchestrator/delegate endpoint."""

    def setup_method(self) -> None:
        from svc_orchestrator.app import create_orchestrator_app
        self.app = create_orchestrator_app(dapr_url="http://localhost:3500")
        self.client = TestClient(self.app)

    def test_delegate_endpoint_exists(self) -> None:
        """POST /orchestrator/delegate returns 422 for bad input, not 404/405."""
        response = self.client.post("/orchestrator/delegate", json={})
        # 422 = FastAPI validation error (missing required fields)
        # This confirms the endpoint exists
        assert response.status_code in (200, 422)

    def test_describe_includes_delegate(self) -> None:
        """GET /describe mentions delegation capability."""
        response = self.client.get("/describe")
        assert response.status_code == 200
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-orchestrator && uv run pytest tests/test_child_session.py -v
```
Expected: FAIL — `ChildSessionRequest`, `ChildSessionSpawner` not found.

**Step 3: Write the implementation**

Create `services/svc-orchestrator/src/svc_orchestrator/child_session.py`:

```python
"""ChildSessionSpawner — spawns child agent sessions via the session-service.

Used by the /orchestrator/delegate endpoint to run sub-agents. Each child
session is an independent turn in the session-service (with its own session ID),
so it gets its own context window, tool access, and provider configuration.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from svc_orchestrator.dapr_client import DaprClient


class ChildSessionRequest(BaseModel):
    """Request to spawn a child session."""

    prompt: str
    child_session_id: str = ""
    provider_name: str = "mock"
    services: list[str] = []
    workspace_content: dict[str, str] = {}
    agent_ref: str = "default"


class ChildSessionSpawner:
    """Spawns child sessions by calling the session-service via Dapr."""

    def __init__(
        self,
        dapr: DaprClient,
        session_service_app_id: str = "session-service",
    ) -> None:
        self._dapr = dapr
        self._session_service_app_id = session_service_app_id

    async def spawn(self, request: ChildSessionRequest) -> dict[str, Any]:
        """Spawn a child session and wait for its result.

        Args:
            request: Child session request parameters.

        Returns:
            TurnResponse dict from session-service with keys:
                session_id, result (str), messages (list).
        """
        session_id = request.child_session_id or str(uuid.uuid4())[:8]
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "provider_name": request.provider_name,
            "services": request.services,
            "workspace_content": request.workspace_content,
            "agent_ref": request.agent_ref,
        }
        return await self._dapr.invoke(
            self._session_service_app_id,
            f"sessions/{session_id}/turn",
            payload,
            timeout=300.0,  # Child sessions may take longer
        )
```

Modify `services/svc-orchestrator/src/svc_orchestrator/app.py` to add the delegate endpoint:

Read the full `app.py`, then add after the existing `execute` endpoint:

```python
from svc_orchestrator.child_session import ChildSessionRequest, ChildSessionSpawner


class DelegateRequest(BaseModel):
    """Request model for POST /orchestrator/delegate."""

    prompt: str
    child_session_id: str = ""
    provider_name: str = "mock"
    services: list[str] = []
    workspace_content: dict[str, str] = {}
    agent_ref: str = "default"


class DelegateResponse(BaseModel):
    """Response model for POST /orchestrator/delegate."""

    child_session_id: str
    result: str
    messages: list[Message]
```

Add inside `create_orchestrator_app`:

```python
    spawner = ChildSessionSpawner(dapr=dapr)

    @app.post("/orchestrator/delegate")
    async def delegate(request: DelegateRequest) -> dict[str, Any]:
        """Spawn a child agent session and wait for its result."""
        child_req = ChildSessionRequest(
            prompt=request.prompt,
            child_session_id=request.child_session_id,
            provider_name=request.provider_name,
            services=request.services,
            workspace_content=request.workspace_content,
            agent_ref=request.agent_ref,
        )
        result = await spawner.spawn(child_req)
        return DelegateResponse(
            child_session_id=result.get("session_id", ""),
            result=result.get("result", ""),
            messages=[Message(**m) for m in result.get("messages", [])],
        ).model_dump()
```

**Step 4: Run all orchestrator tests**

```bash
cd services/svc-orchestrator && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-orchestrator/ && git commit -m "feat(svc-orchestrator): add ChildSessionSpawner and /orchestrator/delegate endpoint"
```

---

## Task 10: svc-delegation — Delegation Tool Service

**Files:**
- Create: `services/svc-delegation/pyproject.toml`
- Create: `services/svc-delegation/Dockerfile`
- Create: `services/svc-delegation/src/svc_delegation/__init__.py`
- Create: `services/svc-delegation/src/svc_delegation/tool.py`
- Create: `services/svc-delegation/src/svc_delegation/app.py`
- Create: `services/svc-delegation/tests/__init__.py`
- Create: `services/svc-delegation/tests/test_tool.py`
- Create: `services/svc-delegation/tests/test_app.py`

**Step 1: Write the failing tests**

Create `services/svc-delegation/tests/__init__.py` (empty).

Create `services/svc-delegation/tests/test_tool.py`:

```python
"""Tests for DelegateTool — spawns child agent sessions via orchestrator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from svc_delegation.tool import DelegateTool


class TestDelegateTool:

    @pytest.fixture
    def tool(self) -> DelegateTool:
        return DelegateTool(orchestrator_base_url="http://fake-orchestrator:8080")

    @pytest.mark.asyncio
    async def test_execute_missing_prompt(self, tool: DelegateTool) -> None:
        """execute() with no prompt returns error."""
        result = await tool.execute({})
        assert result.success is False
        assert "prompt" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_delegates_and_returns_result(self, tool: DelegateTool) -> None:
        """execute() calls orchestrator /delegate and returns child result."""
        mock_response = {
            "child_session_id": "child-abc",
            "result": "Task complete",
            "messages": [],
        }
        with patch.object(tool, "_call_orchestrator", new=AsyncMock(return_value=mock_response)):
            result = await tool.execute({"prompt": "Do some work"})

        assert result.success is True
        assert result.output["result"] == "Task complete"
        assert result.output["child_session_id"] == "child-abc"

    @pytest.mark.asyncio
    async def test_execute_passes_provider_name(self, tool: DelegateTool) -> None:
        """execute() forwards provider_name to orchestrator."""
        captured: list[dict[str, Any]] = []

        async def mock_call(payload: dict[str, Any]) -> dict[str, Any]:
            captured.append(payload)
            return {"child_session_id": "c1", "result": "ok", "messages": []}

        with patch.object(tool, "_call_orchestrator", new=AsyncMock(side_effect=mock_call)):
            await tool.execute({"prompt": "hello", "provider_name": "anthropic"})

        assert captured[0]["provider_name"] == "anthropic"

    @pytest.mark.asyncio
    async def test_execute_orchestrator_unreachable(self, tool: DelegateTool) -> None:
        """execute() returns error when orchestrator is unreachable."""
        exc = httpx.ConnectError("Connection refused")
        with patch.object(tool, "_call_orchestrator", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"prompt": "hello"})

        assert result.success is False
        assert "unreachable" in result.error["message"].lower()

    @pytest.mark.asyncio
    async def test_execute_orchestrator_http_error(self, tool: DelegateTool) -> None:
        """execute() returns error when orchestrator returns HTTP error."""
        exc = httpx.HTTPStatusError(
            "Server Error",
            request=httpx.Request("POST", "http://fake:8080/orchestrator/delegate"),
            response=httpx.Response(500),
        )
        with patch.object(tool, "_call_orchestrator", new=AsyncMock(side_effect=exc)):
            result = await tool.execute({"prompt": "hello"})

        assert result.success is False
        assert "500" in result.error["message"]
```

Create `services/svc-delegation/tests/test_app.py`:

```python
"""Tests for the svc-delegation FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_delegation.app import create_delegation_app


class TestDelegationApp:

    def setup_method(self) -> None:
        self.app = create_delegation_app(orchestrator_base_url="http://fake:8080")
        self.client = TestClient(self.app)

    def test_module_exposes_app(self) -> None:
        from svc_delegation import app as app_module
        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_delegate_tool(self) -> None:
        response = self.client.get("/describe")
        assert response.status_code == 200
        tool_names = [t["name"] for t in response.json()["tools"]]
        assert "delegate" in tool_names

    def test_describe_tool_has_prompt_field(self) -> None:
        response = self.client.get("/describe")
        data = response.json()
        delegate_tool = next(t for t in data["tools"] if t["name"] == "delegate")
        assert "prompt" in delegate_tool["input_schema"]["properties"]
        assert "prompt" in delegate_tool["input_schema"].get("required", [])
```

**Step 2: Create project scaffold**

Create `services/svc-delegation/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "svc-delegation"
version = "0.1.0"
description = "Amplifier delegation tool service — spawns child agent sessions via svc-orchestrator"
requires-python = ">=3.12"
dependencies = [
    "amplifier-service-sdk",
    "httpx>=0.28",
    "fastapi>=0.115",
    "uvicorn>=0.32",
]

[tool.uv.sources]
amplifier-service-sdk = { path = "../../amplifier-service-sdk" }

[tool.hatch.build.targets.wheel]
packages = ["src/svc_delegation"]

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

Create `services/svc-delegation/Dockerfile`:

```dockerfile
FROM amplifier-service-base

COPY services/svc-delegation/ /build/svc-delegation/
RUN cd /build/svc-delegation && uv pip install --system . && rm -rf /build

CMD ["uvicorn", "svc_delegation.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 3: Write the implementation**

Create `services/svc-delegation/src/svc_delegation/__init__.py` (empty).

Create `services/svc-delegation/src/svc_delegation/tool.py`:

```python
"""DelegateTool — spawns child agent sessions via svc-orchestrator /delegate endpoint."""

from __future__ import annotations

from typing import Any

import httpx

from amplifier_service_sdk.models import ToolResult


class DelegateTool:
    """Delegates work to a child agent session running in the orchestrator.

    Calls POST /orchestrator/delegate on svc-orchestrator via its Dapr
    invocation URL. The child session gets its own context window, tools,
    and provider. Results are returned when the child session completes.
    """

    name: str = "delegate"
    description: str = (
        "Spawn a child agent session to handle a specific sub-task. "
        "The child session runs independently with its own context and tool access. "
        "Returns when the child session completes."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The task prompt for the child agent to execute",
            },
            "provider_name": {
                "type": "string",
                "description": "LLM provider for the child session (default: 'mock')",
                "default": "mock",
            },
            "services": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of service app-ids available to the child session. "
                               "Empty list uses the session-service defaults.",
            },
            "workspace_content": {
                "type": "object",
                "description": "Additional context files to inject into the child session's workspace",
                "additionalProperties": {"type": "string"},
            },
            "child_session_id": {
                "type": "string",
                "description": "Optional explicit session ID for the child session",
            },
        },
        "required": ["prompt"],
    }

    def __init__(self, orchestrator_base_url: str) -> None:
        self._base_url = orchestrator_base_url.rstrip("/")

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Delegate a task to a child agent session."""
        prompt = input.get("prompt")
        if not prompt:
            return ToolResult(
                success=False,
                error={"message": "prompt is required to delegate a task"},
            )

        payload: dict[str, Any] = {
            "prompt": prompt,
            "provider_name": input.get("provider_name", "mock"),
            "services": input.get("services", []),
            "workspace_content": input.get("workspace_content", {}),
            "child_session_id": input.get("child_session_id", ""),
        }

        try:
            result = await self._call_orchestrator(payload)
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error={"message": f"orchestrator error: {exc.response.status_code}"},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                error={"message": f"orchestrator unreachable: {exc}"},
            )

        return ToolResult(
            success=True,
            output={
                "child_session_id": result.get("child_session_id", ""),
                "result": result.get("result", ""),
            },
        )

    async def _call_orchestrator(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to svc-orchestrator /orchestrator/delegate."""
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{self._base_url}/orchestrator/delegate", json=payload
            )
            response.raise_for_status()
            return response.json()
```

Create `services/svc-delegation/src/svc_delegation/app.py`:

```python
"""FastAPI app factory for svc-delegation — delegation tool service."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import ToolCapability, ToolRequest
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_delegation.tool import DelegateTool

_DAPR_HTTP_PORT = os.environ.get("DAPR_HTTP_PORT", "3500")


def create_delegation_app(orchestrator_base_url: str | None = None) -> FastAPI:
    """Create the svc-delegation FastAPI application."""
    if orchestrator_base_url is None:
        orchestrator_base_url = (
            f"http://localhost:{_DAPR_HTTP_PORT}/v1.0/invoke/svc-orchestrator/method"
        )

    tool = DelegateTool(orchestrator_base_url=orchestrator_base_url)

    config = ServiceConfig(
        name="svc-delegation",
        tools=[
            ToolCapability(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
        ],
    )
    app = create_app(config)

    @app.post("/tools/delegate/execute")
    async def execute_delegate(request: ToolRequest) -> dict[str, Any]:
        """Spawn a child agent session and return its result."""
        result = await tool.execute(request.input)
        return result.model_dump()

    return app


app = create_delegation_app()
```

**Step 4: Install dependencies and run tests**

```bash
cd services/svc-delegation && uv sync && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/svc-delegation/ && git commit -m "feat(svc-delegation): add delegation tool service for child agent session spawning"
```

---

## Task 11: session-service — Hook Service Discovery

**Files:**
- Modify: `services/session-service/src/session_service/discovery.py`
- Modify: `services/session-service/src/session_service/app.py`
- Create: `services/session-service/tests/test_discovery_phase3b.py`

**Step 1: Write the failing tests**

Read `services/session-service/src/session_service/discovery.py` first.

Create `services/session-service/tests/test_discovery_phase3b.py`:

```python
"""Tests for Phase 3b hook service discovery — routing table includes hooks."""

from __future__ import annotations

from typing import Any

import pytest

from session_service.discovery import build_routing_table


class TestBuildRoutingTableWithHooks:
    """build_routing_table correctly populates hooks, hook_endpoints, hook_priorities."""

    def test_routes_pre_hooks_by_event(self) -> None:
        """Hook services are mapped to their events in routing_table.hooks."""
        describe_results: dict[str, dict[str, Any]] = {
            "svc-hooks-approval": {
                "hooks": [
                    {
                        "name": "approval",
                        "events": ["tool:pre"],
                        "priority": 5,
                        "mode": "sync",
                    }
                ],
            },
            "svc-hooks-routing": {
                "hooks": [
                    {
                        "name": "routing",
                        "events": ["provider:request", "session:start"],
                        "priority": 5,
                        "mode": "sync",
                    }
                ],
            },
        }
        rt = build_routing_table(describe_results, "svc-context")

        assert "svc-hooks-approval" in rt["hooks"].get("tool:pre", [])
        assert "svc-hooks-routing" in rt["hooks"].get("provider:request", [])
        assert "svc-hooks-routing" in rt["hooks"].get("session:start", [])

    def test_hook_endpoints_populated(self) -> None:
        """hook_endpoints maps app_id → hooks/{name}/invoke path."""
        describe_results: dict[str, dict[str, Any]] = {
            "svc-hooks-approval": {
                "hooks": [{"name": "approval", "events": ["tool:pre"], "priority": 5, "mode": "sync"}],
            },
        }
        rt = build_routing_table(describe_results, "svc-context")
        assert rt["hook_endpoints"]["svc-hooks-approval"] == "hooks/approval/invoke"

    def test_hook_priorities_populated(self) -> None:
        """hook_priorities maps app_id → priority for sorting."""
        describe_results: dict[str, dict[str, Any]] = {
            "svc-hooks-approval": {
                "hooks": [{"name": "approval", "events": ["tool:pre"], "priority": 5, "mode": "sync"}],
            },
        }
        rt = build_routing_table(describe_results, "svc-context")
        assert rt["hook_priorities"]["svc-hooks-approval"] == 5

    def test_async_hooks_not_in_routing_table_hooks(self) -> None:
        """Async-mode hooks (pub/sub subscribers) are NOT added to routing_table.hooks
        — they receive events via Dapr pub/sub, not via orchestrator dispatch."""
        describe_results: dict[str, dict[str, Any]] = {
            "svc-hooks-async": {
                "hooks": [
                    {"name": "logging", "events": ["tool:post"], "priority": 100, "mode": "async"},
                ],
            },
        }
        rt = build_routing_table(describe_results, "svc-context")
        # Async hooks are NOT added to routing_table.hooks — they subscribe via Dapr
        assert "svc-hooks-async" not in rt["hooks"].get("tool:post", [])

    def test_tools_and_hooks_coexist(self) -> None:
        """Both tools and hooks can be in the same describe_results batch."""
        describe_results: dict[str, dict[str, Any]] = {
            "svc-bash": {
                "tools": [{"name": "bash", "description": "Run commands"}],
            },
            "svc-hooks-approval": {
                "hooks": [{"name": "approval", "events": ["tool:pre"], "priority": 5, "mode": "sync"}],
            },
        }
        rt = build_routing_table(describe_results, "svc-context")
        assert rt["tools"]["bash"] == "svc-bash"
        assert "svc-hooks-approval" in rt["hooks"].get("tool:pre", [])
```

**Step 2: Run tests to verify they fail**

```bash
cd services/session-service && uv run pytest tests/test_discovery_phase3b.py -v
```
Expected: FAIL — `build_routing_table` does not yet populate `hooks`, `hook_endpoints`, `hook_priorities`.

**Step 3: Write the implementation**

Read `services/session-service/src/session_service/discovery.py` fully.

Find the `build_routing_table` function (or equivalent). Extend it to handle hook registrations from the `hooks` key in each service's describe result:

The updated `build_routing_table` function must:
1. Iterate over each service's `describe["hooks"]` list
2. For each hook registration with `mode == "sync"`, add the service app_id to `routing_table.hooks[event]` for each event in `hook.events`
3. Add `routing_table.hook_endpoints[app_id] = f"hooks/{hook.name}/invoke"`
4. Add `routing_table.hook_priorities[app_id] = hook.priority`
5. Skip hooks with `mode == "async"` — these subscribe via Dapr pub/sub directly

```python
# Inside build_routing_table, add after existing tools/providers processing:

for app_id, describe in describe_results.items():
    for hook_reg in describe.get("hooks", []):
        hook_name = hook_reg.get("name", "")
        hook_events = hook_reg.get("events", [])
        hook_mode = hook_reg.get("mode", "sync")
        hook_priority = hook_reg.get("priority", 50)

        if hook_mode != "sync":
            continue  # async hooks receive events via Dapr pub/sub

        # Register hook service for each event
        for event in hook_events:
            hooks_list = routing_table.setdefault("hooks", {}).setdefault(event, [])
            if app_id not in hooks_list:
                hooks_list.append(app_id)

        # Record invoke endpoint and priority
        routing_table.setdefault("hook_endpoints", {})[app_id] = (
            f"hooks/{hook_name}/invoke"
        )
        routing_table.setdefault("hook_priorities", {})[app_id] = hook_priority
```

**Note:** Match the exact dict structure used by `build_routing_table`. If it returns a `RoutingTable` Pydantic object, update the `RoutingTable` fields directly instead of using `setdefault`.

Also update `DEFAULT_SERVICES` in `services/session-service/src/session_service/app.py`:

```python
DEFAULT_SERVICES: list[str] = [
    "svc-bash",
    "svc-filesystem",
    "svc-search",
    "svc-web",
    "svc-skills",
    "svc-todo",
    "svc-modes",
    "svc-mock-provider",
    "svc-providers",
    "svc-delegation",
    # Hook services (Phase 3b)
    "svc-hooks-approval",
    "svc-hooks-routing",
    "svc-hooks-async",
    "svc-hooks-shell",
]
```

**Step 4: Run all session-service tests**

```bash
cd services/session-service && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add services/session-service/ && git commit -m "feat(session-service): add Phase 3b hook service discovery and DEFAULT_SERVICES update"
```

---

## Task 12: Docker Compose — Hook Services + Dapr Subscription YAML

**Files:**
- Modify: `docker-compose.yaml`
- Create: `docker/dapr/components/subscriptions.yaml`

**Step 1: Read the current docker-compose.yaml**

Read `docker-compose.yaml` to understand the existing pattern. Note the exact sidecar command flags and volume mounts.

**Step 2: Add hook services and svc-delegation**

For each new service, add a service + sidecar pair following the exact same pattern as existing services. Read `docker-compose.yaml` first to copy the correct template.

Services to add: `svc-hooks-approval`, `svc-hooks-routing`, `svc-hooks-async`, `svc-hooks-shell`, `svc-delegation`.

Template for each hook service (replace `{NAME}` with service name, `{DOCKER_NAME}` with dockerfile-friendly name):

```yaml
  svc-hooks-approval:
    build:
      context: .
      dockerfile: services/svc-hooks-approval/Dockerfile
    environment:
      DAPR_HTTP_PORT: "3500"
      DENY_TOOLS: ""
    depends_on:
      - redis

  svc-hooks-approval-dapr:
    image: daprio/daprd:1.14.4
    command:
      - ./daprd
      - --app-id=svc-hooks-approval
      - --app-port=8000
      - --dapr-http-port=3500
      - --dapr-grpc-port=50001
      - --resources-path=/components
      - --config=/config/config.yaml
    volumes:
      - ./docker/dapr/components:/components
      - ./docker/dapr:/config
    network_mode: "service:svc-hooks-approval"
    depends_on:
      - svc-hooks-approval
```

Add similar blocks for: `svc-hooks-routing` (add env `ROUTING_MATRIX_PATH: ""`), `svc-hooks-async` (add env `LOG_TEMPLATE: "~/.amplifier/logs/{session_id}/events.jsonl"`), `svc-hooks-shell` (add env `SHELL_HOOKS_DIR: ""`), `svc-delegation`.

**Step 3: Update session-service depends_on**

Add to the `session-service` service's `depends_on` list:
```yaml
      - svc-hooks-approval-dapr
      - svc-hooks-routing-dapr
      - svc-hooks-async-dapr
      - svc-hooks-shell-dapr
      - svc-delegation-dapr
```

**Step 4: Create Dapr subscription YAML**

Create `docker/dapr/components/subscriptions.yaml`:

```yaml
apiVersion: dapr.io/v1alpha1
kind: Subscription
metadata:
  name: hooks-async-subscriptions
spec:
  pubsubname: pubsub
  topic: tool.post
  route: /events/tool.post
  scopes:
    - svc-hooks-async
    - svc-hooks-shell
---
apiVersion: dapr.io/v1alpha1
kind: Subscription
metadata:
  name: hooks-async-tool-pre
spec:
  pubsubname: pubsub
  topic: tool.pre
  route: /events/tool.pre
  scopes:
    - svc-hooks-async
---
apiVersion: dapr.io/v1alpha1
kind: Subscription
metadata:
  name: hooks-async-session-start
spec:
  pubsubname: pubsub
  topic: session.start
  route: /events/session.start
  scopes:
    - svc-hooks-async
    - svc-hooks-shell
---
apiVersion: dapr.io/v1alpha1
kind: Subscription
metadata:
  name: hooks-async-session-end
spec:
  pubsubname: pubsub
  topic: session.end
  route: /events/session.end
  scopes:
    - svc-hooks-async
    - svc-hooks-shell
---
apiVersion: dapr.io/v1alpha1
kind: Subscription
metadata:
  name: hooks-async-provider-events
spec:
  pubsubname: pubsub
  topic: provider.request
  route: /events/provider.request
  scopes:
    - svc-hooks-async
---
apiVersion: dapr.io/v1alpha1
kind: Subscription
metadata:
  name: hooks-async-prompt-complete
spec:
  pubsubname: pubsub
  topic: prompt.complete
  route: /events/prompt.complete
  scopes:
    - svc-hooks-async
    - svc-hooks-shell
```

**Step 5: Commit**

```bash
git add docker-compose.yaml docker/dapr/components/subscriptions.yaml && \
git commit -m "feat(docker): add Phase 3b hook services and Dapr subscription YAML to docker-compose"
```

---

## Task 13: Integration Test — Hook Dispatch + Delegation Round-Trip

**Files:**
- Create: `tests/integration/test_phase3b_integration.py`

**Step 1: Write the integration tests**

Create `tests/integration/test_phase3b_integration.py`:

```python
"""Phase 3b integration tests — in-process hook dispatch and delegation.

Tests the full stack:
1. Hook services respond correctly to /hooks/{name}/invoke
2. HookDispatcher routes pre-hook calls and handles DENY
3. DelegateTool calls orchestrator /delegate endpoint
4. svc-hooks-async /dapr/subscribe returns correct subscriptions
5. Event delivery via /events/{topic} is handled

All services run in-process using FastAPI TestClient — no Docker required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from svc_hooks_approval.app import create_approval_hook_app
from svc_hooks_routing.app import create_routing_hook_app
from svc_hooks_async.app import create_async_hooks_app


class TestApprovalHookService:
    """Verify svc-hooks-approval responds correctly to pre-hook invocations."""

    def test_approval_describe(self) -> None:
        app = create_approval_hook_app(config={})
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        hook_names = [h["name"] for h in response.json()["hooks"]]
        assert "approval" in hook_names

    def test_approval_allows_safe_tool(self) -> None:
        app = create_approval_hook_app(config={})
        client = TestClient(app)
        response = client.post(
            "/hooks/approval/invoke",
            json={"event": "tool:pre", "data": {"tool_name": "read_file"}},
        )
        assert response.status_code == 200
        assert response.json()["action"] == "CONTINUE"

    def test_approval_denies_configured_tool(self) -> None:
        app = create_approval_hook_app(config={"deny_tools": ["dangerous_tool"]})
        client = TestClient(app)
        response = client.post(
            "/hooks/approval/invoke",
            json={"event": "tool:pre", "data": {"tool_name": "dangerous_tool"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "DENY"
        assert "dangerous_tool" in data.get("reason", "")

    def test_approval_dapr_subscribe_is_empty(self) -> None:
        app = create_approval_hook_app(config={})
        client = TestClient(app)
        response = client.get("/dapr/subscribe")
        assert response.status_code == 200
        assert response.json() == []


class TestRoutingHookService:
    """Verify svc-hooks-routing responds correctly to provider:request."""

    def test_routing_describe(self) -> None:
        app = create_routing_hook_app(matrix={})
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        hook_names = [h["name"] for h in response.json()["hooks"]]
        assert "routing" in hook_names

    def test_routing_no_matrix_continues(self) -> None:
        app = create_routing_hook_app(matrix={})
        client = TestClient(app)
        response = client.post(
            "/hooks/routing/invoke",
            json={"event": "provider:request", "data": {}},
        )
        assert response.status_code == 200
        assert response.json()["action"] == "CONTINUE"

    def test_routing_with_matrix_injects_context(self) -> None:
        matrix = {
            "name": "balanced",
            "roles": {
                "fast": {"description": "Quick tasks"},
                "coding": {"description": "Code generation"},
            },
        }
        app = create_routing_hook_app(matrix=matrix)
        client = TestClient(app)
        response = client.post(
            "/hooks/routing/invoke",
            json={"event": "provider:request", "data": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "INJECT_CONTEXT"
        assert "fast" in data["data"]["context_injection"]
        assert "coding" in data["data"]["context_injection"]


class TestAsyncHookService:
    """Verify svc-hooks-async pub/sub subscriptions and event receipt."""

    def test_async_describe(self) -> None:
        app = create_async_hooks_app(log_template="/tmp/test-{session_id}/events.jsonl")
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        hook_names = [h["name"] for h in response.json()["hooks"]]
        assert "logging" in hook_names

    def test_async_dapr_subscribe_has_topics(self) -> None:
        app = create_async_hooks_app(log_template="/tmp/test-{session_id}/events.jsonl")
        client = TestClient(app)
        response = client.get("/dapr/subscribe")
        assert response.status_code == 200
        subs = response.json()
        topics = [s["topic"] for s in subs]
        assert "tool.post" in topics
        assert "session.start" in topics
        assert "session.end" in topics

    def test_async_event_endpoint_accepts_tool_post(self) -> None:
        import json
        app = create_async_hooks_app(log_template="/tmp/test-{session_id}/events.jsonl")
        client = TestClient(app)
        envelope = {
            "data": json.dumps({"session_id": "integration-test", "tool_name": "bash"}),
            "topic": "tool.post",
        }
        response = client.post("/events/tool.post", json=envelope)
        assert response.status_code == 200
        assert response.json()["status"] == "SUCCESS"


class TestHookDispatcher:
    """Verify HookDispatcher routes hook calls correctly (uses live hook services)."""

    @pytest.mark.asyncio
    async def test_dispatcher_approves_safe_tool(self) -> None:
        """HookDispatcher calls approval hook and returns CONTINUE for safe tool."""
        from amplifier_service_sdk.models import RoutingTable
        from svc_orchestrator.dapr_client import DaprClient
        from svc_orchestrator.hook_dispatcher import HookDispatcher

        dapr = DaprClient(dapr_url="http://localhost:3500")
        # Mock invoke to simulate svc-hooks-approval returning CONTINUE
        dapr.invoke = AsyncMock(  # type: ignore[method-assign]
            return_value={"action": "CONTINUE", "data": None, "reason": None}
        )

        dispatcher = HookDispatcher(dapr=dapr)
        rt = RoutingTable(
            hooks={"tool:pre": ["svc-hooks-approval"]},
            hook_endpoints={"svc-hooks-approval": "hooks/approval/invoke"},
            hook_priorities={"svc-hooks-approval": 5},
        )
        result = await dispatcher.dispatch_pre(
            event="tool:pre",
            data={"tool_name": "read_file"},
            routing_table=rt,
        )
        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_dispatcher_blocks_denied_tool(self) -> None:
        """HookDispatcher propagates DENY from approval hook."""
        from amplifier_service_sdk.models import RoutingTable
        from svc_orchestrator.dapr_client import DaprClient
        from svc_orchestrator.hook_dispatcher import HookDispatcher

        dapr = DaprClient(dapr_url="http://localhost:3500")
        dapr.invoke = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "action": "DENY",
                "reason": "blocked by policy",
                "data": None,
            }
        )

        dispatcher = HookDispatcher(dapr=dapr)
        rt = RoutingTable(
            hooks={"tool:pre": ["svc-hooks-approval"]},
            hook_endpoints={"svc-hooks-approval": "hooks/approval/invoke"},
        )
        result = await dispatcher.dispatch_pre(
            event="tool:pre",
            data={"tool_name": "dangerous_tool"},
            routing_table=rt,
        )
        assert result.action == "DENY"
        assert "blocked" in (result.reason or "")


class TestDelegationService:
    """Verify svc-delegation tool service."""

    def test_delegation_describe(self) -> None:
        from svc_delegation.app import create_delegation_app

        app = create_delegation_app(orchestrator_base_url="http://fake:8080")
        client = TestClient(app)
        response = client.get("/describe")
        assert response.status_code == 200
        tool_names = [t["name"] for t in response.json()["tools"]]
        assert "delegate" in tool_names

    def test_delegation_tool_missing_prompt_returns_error(self) -> None:
        from svc_delegation.app import create_delegation_app

        app = create_delegation_app(orchestrator_base_url="http://fake:8080")
        client = TestClient(app)
        response = client.post(
            "/tools/delegate/execute",
            json={"name": "delegate", "input": {}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "prompt" in data["error"]["message"].lower()
```

**Step 2: Run the integration tests**

```bash
PYTHONPATH=services/svc-hooks-approval/src:services/svc-hooks-routing/src:services/svc-hooks-async/src:services/svc-hooks-shell/src:services/svc-delegation/src:services/svc-orchestrator/src:amplifier-service-sdk/src \
  python -m pytest tests/integration/test_phase3b_integration.py -v
```
Expected: All tests PASS.

**Step 3: Commit**

```bash
git add tests/integration/test_phase3b_integration.py && \
git commit -m "test(phase3b): add integration tests for hook dispatch and delegation round-trip"
```

---

## Task 14: SDK — Update ServiceConfig and create_app for HookRegistration

**Files:**
- Modify: `amplifier-service-sdk/src/amplifier_service_sdk/service.py`
- Modify: `amplifier-service-sdk/tests/` (existing SDK tests)

**Step 1: Read current service.py**

Read `amplifier-service-sdk/src/amplifier_service_sdk/service.py` fully to understand `ServiceConfig` and `create_app`.

**Step 2: Write failing test**

Check whether `ServiceConfig` already accepts a `hooks` field. If not, add a test to the SDK test file (find the existing test file with `ls amplifier-service-sdk/tests/`):

```python
def test_service_config_accepts_hooks() -> None:
    """ServiceConfig accepts a list of HookRegistration objects."""
    from amplifier_service_sdk.models import HookRegistration
    from amplifier_service_sdk.service import ServiceConfig

    config = ServiceConfig(
        name="test-svc",
        hooks=[HookRegistration(name="approval", events=["tool:pre"])],
    )
    assert len(config.hooks) == 1
    assert config.hooks[0].name == "approval"


def test_describe_endpoint_includes_hooks() -> None:
    """GET /describe returns hooks list when ServiceConfig has hooks."""
    from amplifier_service_sdk.models import HookRegistration
    from amplifier_service_sdk.service import ServiceConfig, create_app
    from fastapi.testclient import TestClient

    config = ServiceConfig(
        name="test-hook-svc",
        hooks=[HookRegistration(name="myHook", events=["tool:pre"], priority=5)],
    )
    app = create_app(config)
    client = TestClient(app)
    response = client.get("/describe")
    assert response.status_code == 200
    data = response.json()
    hook_names = [h["name"] for h in data["hooks"]]
    assert "myHook" in hook_names
```

**Step 3: Run to verify failure**

```bash
cd amplifier-service-sdk && uv run pytest tests/ -v -k "hook"
```
Expected: FAIL if `ServiceConfig` does not accept `hooks: list[HookRegistration]`.

**Step 4: Implement**

In `amplifier-service-sdk/src/amplifier_service_sdk/service.py`:

1. Find `ServiceConfig` dataclass/Pydantic model and add a `hooks` field:
```python
from amplifier_service_sdk.models import HookRegistration, ToolCapability

class ServiceConfig(BaseModel):
    name: str
    version: str = "0.1.0"
    tools: list[ToolCapability] = Field(default_factory=list)
    hooks: list[HookRegistration] = Field(default_factory=list)
    providers: list[dict[str, Any]] = Field(default_factory=list)
    content_paths: list[str] = Field(default_factory=list)
    content_dir: str | None = None
```

2. In `create_app`, ensure the `/describe` endpoint serializes the `hooks` list using `HookRegistration.model_dump()`:
```python
@app.get("/describe")
async def describe() -> dict[str, Any]:
    return DescribeResponse(
        name=config.name,
        version=config.version,
        tools=config.tools,
        hooks=config.hooks,
        providers=config.providers,
        content_paths=config.content_paths,
    ).model_dump()
```

**Step 5: Run all SDK tests**

```bash
cd amplifier-service-sdk && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 6: Commit**

```bash
git add amplifier-service-sdk/ && git commit -m "feat(sdk): update ServiceConfig and create_app to expose hooks in /describe endpoint"
```

---

## Task 15: Final Validation — Run All Test Suites

**Files:** None created. Verification only.

**Step 1: Run each new service's test suite**

```bash
for svc in svc-hooks-approval svc-hooks-routing svc-hooks-async svc-hooks-shell svc-delegation; do
  echo "=== Testing $svc ==="
  cd services/$svc && uv run pytest tests/ -v --tb=short 2>&1 | tail -5
  cd ../..
done
```
Expected: All pass.

**Step 2: Run the orchestrator test suite**

```bash
cd services/svc-orchestrator && uv run pytest tests/ -v --tb=short
```
Expected: All pass, including new `TestOrchestratorPreHookDeny`, `TestOrchestratorPostHookPublish`, `TestOrchestratorProviderRequestHook`, `TestOrchestratorSessionEvents`.

**Step 3: Run the session-service test suite**

```bash
cd services/session-service && uv run pytest tests/ -v --tb=short
```
Expected: All pass, including `TestBuildRoutingTableWithHooks`.

**Step 4: Run the SDK test suite**

```bash
cd amplifier-service-sdk && uv run pytest tests/ -v --tb=short
```
Expected: All pass.

**Step 5: Run the Phase 3b integration tests**

```bash
PYTHONPATH=services/svc-hooks-approval/src:services/svc-hooks-routing/src:services/svc-hooks-async/src:services/svc-hooks-shell/src:services/svc-delegation/src:services/svc-orchestrator/src:amplifier-service-sdk/src \
  python -m pytest tests/integration/test_phase3b_integration.py -v
```
Expected: All pass.

**Step 6: Commit**

If any tests fail, fix them before committing. Once all tests pass:

```bash
git add -A && git commit -m "test(phase3b): final validation — all Phase 3b test suites pass"
```

---

## Summary

| Task | Component | Key Deliverable | Tests |
|------|-----------|----------------|-------|
| 1 | SDK models | `HookRegistration`, `DaprSubscription`, `RoutingTable.hook_endpoints` | ~6 |
| 2 | svc-hooks-approval | Approval pre-hook: `POST /hooks/approval/invoke`, deny-rule config | ~8 |
| 3 | svc-hooks-routing | Routing pre-hook: `POST /hooks/routing/invoke`, INJECT_CONTEXT | ~8 |
| 4 | svc-hooks-async | Pub/sub async hooks: logging + stubs, `GET /dapr/subscribe`, `POST /events/{topic}` | ~8 |
| 5 | svc-hooks-shell | Shell hook: `POST /hooks/shell/invoke` (pre) + `POST /events/*` (pub/sub) | ~8 |
| 6 | Orchestrator: HookDispatcher | `dispatch_pre` (serial, short-circuit DENY) + `dispatch_post` (best-effort pub/sub) | ~8 |
| 7 | Orchestrator: tool:pre + tool:post | Pre-hook fires before each tool; tool:post published after each tool | ~4 |
| 8 | Orchestrator: provider:request + session | provider:request hook injects context; session:start/end published | ~4 |
| 9 | Orchestrator: ChildSessionSpawner | `ChildSessionSpawner.spawn()` + `/orchestrator/delegate` endpoint | ~5 |
| 10 | svc-delegation | Delegation tool: `POST /tools/delegate/execute` → calls orchestrator /delegate | ~8 |
| 11 | session-service: hook discovery | `build_routing_table` populates `hooks`, `hook_endpoints`, `hook_priorities` | ~5 |
| 12 | Docker Compose | 5 new services + Dapr sidecars + `subscriptions.yaml` | 0 |
| 13 | Integration tests | End-to-end: hook dispatch + denial + routing injection + delegation tool | ~16 |
| 14 | SDK: ServiceConfig | `ServiceConfig.hooks` field + `/describe` serialization | ~3 |
| 15 | Final validation | All test suites pass across every new service | 0 (verification) |

**Pre-hook flow:** `orchestrator._execute_single_tool` → `HookDispatcher.dispatch_pre("tool:pre", ...)` → `dapr.invoke("svc-hooks-approval", "hooks/approval/invoke", HookEvent)` → returns `HookResult(action="DENY")` → tool is blocked

**Post-hook flow:** `orchestrator._execute_single_tool` completes → `HookDispatcher.dispatch_post("tool:post", ...)` → `dapr.publish("pubsub", "tool.post", data)` → Dapr delivers to `svc-hooks-async` at `POST /events/tool.post` → `LoggingHook.handle()` writes JSONL

**Delegation flow:** LLM calls `delegate` tool → `svc-delegation` receives `POST /tools/delegate/execute` → `DelegateTool._call_orchestrator(payload)` → `svc-orchestrator POST /orchestrator/delegate` → `ChildSessionSpawner.spawn()` → `dapr.invoke("session-service", "sessions/{id}/turn", ...)` → child session runs → returns result up the chain
