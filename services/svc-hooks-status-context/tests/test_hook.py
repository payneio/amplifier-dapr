"""Tests for StatusContextHook — environmental context injection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from svc_hooks_status_context.hook import StatusContextHook


@pytest.fixture
def hook() -> StatusContextHook:
    return StatusContextHook()


class TestStatusContextHook:
    """Covers StatusContextHook behaviour for provider:request events."""

    async def test_non_provider_request_continues(
        self, hook: StatusContextHook
    ) -> None:
        """Returns CONTINUE for events that are not provider:request."""
        result = await hook.handle("tool:pre", {})
        assert result.action == "CONTINUE"

    async def test_injects_context_with_hooks_status_context_source(
        self, hook: StatusContextHook
    ) -> None:
        """provider:request injects context with branch, status, and platform info."""
        fake_info = {
            "working_dir": "/workspace",
            "git_branch": "main",
            "git_status": "clean",
            "platform": "Linux x86_64",
        }
        with patch.object(
            hook, "_gather_info", new_callable=AsyncMock, return_value=fake_info
        ):
            result = await hook.handle("provider:request", {})

        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        assert result.data["ephemeral"] is True
        content = result.data["content"]
        assert 'source="hooks-status-context"' in content
        assert "main" in content
        assert "clean" in content
        assert "Linux x86_64" in content

    async def test_content_wraps_in_system_reminder_tags(
        self, hook: StatusContextHook
    ) -> None:
        """Injected content is wrapped in <system-reminder> tags."""
        fake_info = {
            "working_dir": "/workspace",
            "git_branch": "feature-branch",
            "git_status": "3 modified",
            "platform": "Darwin arm64",
        }
        with patch.object(
            hook, "_gather_info", new_callable=AsyncMock, return_value=fake_info
        ):
            result = await hook.handle("provider:request", {})

        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        content = result.data["content"]
        assert content.startswith('<system-reminder source="hooks-status-context">')
        assert content.strip().endswith("</system-reminder>")

    async def test_includes_datetime_with_202_year_prefix(
        self, hook: StatusContextHook
    ) -> None:
        """Injected content includes current UTC datetime starting with '202'."""
        fake_info = {
            "working_dir": "/workspace",
            "git_branch": "main",
            "git_status": "clean",
            "platform": "Linux x86_64",
        }
        with patch.object(
            hook, "_gather_info", new_callable=AsyncMock, return_value=fake_info
        ):
            result = await hook.handle("provider:request", {})

        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        content = result.data["content"]
        # Datetime should be present and start with "202" (e.g. "2024-01-01 ...")
        assert "202" in content

    async def test_gather_info_failure_returns_continue(
        self, hook: StatusContextHook
    ) -> None:
        """Returns CONTINUE without blocking when _gather_info raises an exception."""
        with patch.object(
            hook,
            "_gather_info",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Dapr unavailable"),
        ):
            result = await hook.handle("provider:request", {})

        assert result.action == "CONTINUE"
