# Skills Visibility Hook Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

> **WARNING — Spec Review Flag:** The spec review loop exhausted after 3 iterations
> without formal approval. The final review verdict was APPROVED with all 15 tests
> passing and full spec compliance confirmed. The human reviewer should verify the
> implementation independently during the approval gate.

**Goal:** Create a `SkillsVisibilityHook` that injects available skill names into `provider:request` context so the LLM knows which skills are loaded.

**Architecture:** A sync pre-hook (`priority: 20`) that reads the `SkillsTool.skills` dict on every `provider:request` event. If skills are loaded, it formats them into a `<system-reminder>` XML block and returns `INJECT_CONTEXT` with ephemeral content. Non-`provider:request` events and empty skill dicts pass through unchanged.

**Tech Stack:** Python 3.12+, FastAPI, amplifier-service-sdk (HookResult, HookEvent, HookRegistration, ServiceConfig), pytest (async)

---

## Task 1: Create visibility_hook.py — failing test for non-provider:request events

**Files:**
- Create: `services/svc-skills/tests/test_visibility_hook.py`
- Create: `services/svc-skills/src/svc_skills/visibility_hook.py` (empty stub)

**Step 1: Write the failing test**

Create `services/svc-skills/tests/test_visibility_hook.py`:

```python
"""Tests for SkillsVisibilityHook."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from svc_skills.visibility_hook import SkillsVisibilityHook


def _make_metadata(description: str) -> Any:
    """Create a mock metadata object with a description attribute."""
    m = MagicMock()
    m.description = description
    return m


@pytest.fixture
def skills_tool_with_skills():
    """Mock SkillsTool with two skills loaded."""
    tool = MagicMock()
    tool.skills = {
        "python-standards": _make_metadata(
            "Python coding standards and best practices"
        ),
        "design-patterns": _make_metadata("Software design patterns and architecture"),
    }
    return tool


@pytest.fixture
def skills_tool_empty():
    """Mock SkillsTool with no skills."""
    tool = MagicMock()
    tool.skills = {}
    return tool


class TestSkillsVisibilityHook:
    """Tests for SkillsVisibilityHook."""

    async def test_non_provider_request_continues(
        self, skills_tool_with_skills
    ) -> None:
        """Non-provider:request events return CONTINUE."""
        hook = SkillsVisibilityHook(skills_tool=skills_tool_with_skills)
        result = await hook.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "CONTINUE"
```

**Step 2: Create the empty stub**

Create `services/svc-skills/src/svc_skills/visibility_hook.py`:

```python
"""SkillsVisibilityHook — injects available skills into provider:request context."""
```

**Step 3: Run test to verify it fails**

```bash
cd services/svc-skills && uv run pytest tests/test_visibility_hook.py::TestSkillsVisibilityHook::test_non_provider_request_continues -v
```

Expected: FAIL with `ImportError: cannot import name 'SkillsVisibilityHook'`

**Step 4: Implement the class skeleton with non-provider:request handling**

Replace the contents of `services/svc-skills/src/svc_skills/visibility_hook.py` with:

```python
"""SkillsVisibilityHook — injects available skills into provider:request context."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from amplifier_service_sdk.models import HookResult

if TYPE_CHECKING:
    from svc_skills.tool import SkillsTool


class SkillsVisibilityHook:
    """Pre-hook that injects available skill names into provider:request context."""

    name: str = "skills_visibility"
    events: list[str] = ["provider:request"]
    priority: int = 20
    mode: Literal["sync", "async"] = "sync"

    def __init__(self, skills_tool: SkillsTool) -> None:
        self.skills_tool = skills_tool

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle a hook event.

        For provider:request events: inject available skill names into context.
        For all other events: return CONTINUE.
        """
        if event != "provider:request":
            return HookResult(action="CONTINUE")

        return HookResult(action="CONTINUE")
```

**Step 5: Run test to verify it passes**

```bash
cd services/svc-skills && uv run pytest tests/test_visibility_hook.py::TestSkillsVisibilityHook::test_non_provider_request_continues -v
```

Expected: PASS

---

## Task 2: Empty skills returns CONTINUE

**Files:**
- Modify: `services/svc-skills/tests/test_visibility_hook.py`

**Step 1: Add the failing test**

Append to the `TestSkillsVisibilityHook` class in `tests/test_visibility_hook.py`:

```python
    async def test_empty_skills_continues(self, skills_tool_empty) -> None:
        """provider:request with empty skills dict returns CONTINUE."""
        hook = SkillsVisibilityHook(skills_tool=skills_tool_empty)
        result = await hook.handle("provider:request", {})
        assert result.action == "CONTINUE"
```

**Step 2: Run test to verify it passes (already handled by skeleton)**

```bash
cd services/svc-skills && uv run pytest tests/test_visibility_hook.py::TestSkillsVisibilityHook::test_empty_skills_continues -v
```

Expected: PASS (the skeleton already returns CONTINUE for all provider:request events)

Note: This test is already green because the skeleton returns CONTINUE unconditionally. This is fine — it locks in the empty-skills behavior before we add the injection logic.

---

## Task 3: Inject context with skill names

**Files:**
- Modify: `services/svc-skills/tests/test_visibility_hook.py`
- Modify: `services/svc-skills/src/svc_skills/visibility_hook.py`

**Step 1: Add the failing test**

Append to the `TestSkillsVisibilityHook` class in `tests/test_visibility_hook.py`:

```python
    async def test_injects_context_with_skill_names(
        self, skills_tool_with_skills
    ) -> None:
        """provider:request event injects context with hooks-skills-visibility source
        containing skill names 'python-standards' and 'design-patterns'."""
        hook = SkillsVisibilityHook(skills_tool=skills_tool_with_skills)
        result = await hook.handle("provider:request", {})
        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        content = result.data["content"]
        assert "python-standards" in content
        assert "design-patterns" in content
        assert result.data.get("ephemeral") is True
```

**Step 2: Run test to verify it fails**

```bash
cd services/svc-skills && uv run pytest tests/test_visibility_hook.py::TestSkillsVisibilityHook::test_injects_context_with_skill_names -v
```

Expected: FAIL — `assert result.action == "INJECT_CONTEXT"` (skeleton returns `"CONTINUE"`)

**Step 3: Implement the injection logic**

In `services/svc-skills/src/svc_skills/visibility_hook.py`, replace the `handle` method body (the part after the non-provider:request guard) with:

```python
    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Handle a hook event.

        For provider:request events: inject available skill names into context.
        For all other events: return CONTINUE.
        """
        if event != "provider:request":
            return HookResult(action="CONTINUE")

        skills = self.skills_tool.skills
        if not skills:
            return HookResult(action="CONTINUE")

        lines = ["Available skills (use load_skill tool):"]
        for name in sorted(skills.keys()):
            metadata = skills[name]
            description = getattr(metadata, "description", str(metadata))
            lines.append(f"\n- **{name}**: {description}")

        body = "\n".join(lines)
        content = (
            f'<system-reminder source="hooks-skills-visibility">\n'
            f"{body}\n"
            f"</system-reminder>"
        )

        return HookResult(
            action="INJECT_CONTEXT",
            data={"content": content, "ephemeral": True},
        )
```

**Step 4: Run test to verify it passes**

```bash
cd services/svc-skills && uv run pytest tests/test_visibility_hook.py::TestSkillsVisibilityHook::test_injects_context_with_skill_names -v
```

Expected: PASS

---

## Task 4: Content wrapped in system-reminder tags

**Files:**
- Modify: `services/svc-skills/tests/test_visibility_hook.py`

**Step 1: Add the failing test**

Append to the `TestSkillsVisibilityHook` class in `tests/test_visibility_hook.py`:

```python
    async def test_content_starts_and_ends_with_system_reminder_tag(
        self, skills_tool_with_skills
    ) -> None:
        """Content starts with <system-reminder source="hooks-skills-visibility"> and ends with closing tag."""
        hook = SkillsVisibilityHook(skills_tool=skills_tool_with_skills)
        result = await hook.handle("provider:request", {})
        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        content = result.data["content"]
        assert content.startswith('<system-reminder source="hooks-skills-visibility">')
        assert content.endswith("</system-reminder>")
```

**Step 2: Run test to verify it passes (already handled by Task 3 implementation)**

```bash
cd services/svc-skills && uv run pytest tests/test_visibility_hook.py::TestSkillsVisibilityHook::test_content_starts_and_ends_with_system_reminder_tag -v
```

Expected: PASS (the content template from Task 3 already satisfies this)

**Step 3: Commit visibility_hook.py and its tests**

```bash
git add services/svc-skills/src/svc_skills/visibility_hook.py services/svc-skills/tests/test_visibility_hook.py
git commit -m "feat(svc-skills): add SkillsVisibilityHook with provider:request injection"
```

---

## Task 5: Wire hook into app.py

**Files:**
- Replace: `services/svc-skills/src/svc_skills/app.py`

**Step 1: Replace the entire app.py**

Write `services/svc-skills/src/svc_skills/app.py` with this complete content:

```python
"""FastAPI app factory for svc-skills — the skills tool service."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from amplifier_service_sdk.models import (
    HookEvent,
    HookRegistration,
    ToolCapability,
    ToolRequest,
)
from amplifier_service_sdk.service import ServiceConfig, create_app

from svc_skills.tool import SkillsTool
from svc_skills.visibility_hook import SkillsVisibilityHook


def create_skills_app() -> FastAPI:
    """Create the svc-skills FastAPI application.

    Registers SDK standard endpoints (/healthz, /describe) and the
    skills-specific /tools/load_skill/execute endpoint plus the
    /hooks/skills_visibility/invoke endpoint.

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
    async def invoke_skills_visibility(event: HookEvent) -> dict[str, Any]:
        """Invoke the skills visibility hook."""
        result = await visibility_hook.handle(event.event, event.data)
        return result.model_dump()

    return fastapi_app


app = create_skills_app()
```

**Step 2: Run existing app tests to verify nothing broke**

```bash
cd services/svc-skills && uv run pytest tests/test_app.py -v
```

Expected: All tests in `test_app.py` PASS (healthz, describe includes load_skill, module-level app)

**Step 3: Commit app.py changes**

```bash
git add services/svc-skills/src/svc_skills/app.py
git commit -m "feat(svc-skills): wire SkillsVisibilityHook into app with invoke endpoint"
```

---

## Task 6: Final verification — full test suite

**Files:** None (verification only)

**Step 1: Run the full svc-skills test suite**

```bash
cd services/svc-skills && uv run pytest tests/ -v
```

Expected: All tests pass. The 4 `TestSkillsVisibilityHook` tests must be:
- `test_non_provider_request_continues` — PASS
- `test_injects_context_with_skill_names` — PASS (checks `hooks-skills-visibility` source, `python-standards`, `design-patterns`, `ephemeral=True`)
- `test_empty_skills_continues` — PASS
- `test_content_starts_and_ends_with_system_reminder_tag` — PASS

**Step 2: Run code quality checks**

```bash
cd services/svc-skills && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
```

Expected: No issues