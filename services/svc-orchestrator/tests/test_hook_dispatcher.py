"""Tests for HookDispatcher."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from amplifier_service_sdk.models import RoutingTable
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.hook_dispatcher import HookDispatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dapr() -> DaprClient:
    """Return a DaprClient instance with mocked methods."""
    dapr = DaprClient(dapr_url="http://localhost:3500")
    dapr.invoke = AsyncMock()  # type: ignore[method-assign]
    dapr.publish = AsyncMock()  # type: ignore[method-assign]
    return dapr


def _routing_table(
    hooks: dict[str, list[str]] | None = None,
    hook_priorities: dict[str, int] | None = None,
    hook_endpoints: dict[str, str] | None = None,
) -> RoutingTable:
    return RoutingTable(
        hooks=hooks or {},
        hook_priorities=hook_priorities or {},
        hook_endpoints=hook_endpoints or {},
    )


# ---------------------------------------------------------------------------
# TestHookDispatcherPreHook
# ---------------------------------------------------------------------------


class TestHookDispatcherPreHook:
    """Tests for dispatch_pre() covering all hook chain behaviors."""

    @pytest.mark.asyncio
    async def test_dispatch_pre_continue_when_all_hooks_approve(self) -> None:
        """All hooks return CONTINUE; final result is CONTINUE."""
        dapr = _make_dapr()
        dapr.invoke.return_value = {"action": "CONTINUE", "data": None, "reason": None}  # type: ignore[union-attr]

        routing = _routing_table(hooks={"request:pre": ["hook-a", "hook-b"]})
        dispatcher = HookDispatcher(dapr)

        result = await dispatcher.dispatch_pre("request:pre", {"msg": "hello"}, routing)

        assert result.action == "CONTINUE"
        assert dapr.invoke.call_count == 2  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_dispatch_pre_deny_short_circuits(self) -> None:
        """First hook returns DENY; second hook is never called."""
        dapr = _make_dapr()

        # First call returns DENY; any second call would return CONTINUE
        dapr.invoke.side_effect = [  # type: ignore[union-attr]
            {"action": "DENY", "data": None, "reason": "blocked"},
            {"action": "CONTINUE", "data": None, "reason": None},
        ]

        routing = _routing_table(hooks={"request:pre": ["hook-a", "hook-b"]})
        dispatcher = HookDispatcher(dapr)

        result = await dispatcher.dispatch_pre("request:pre", {}, routing)

        assert result.action == "DENY"
        # Second hook must never have been called
        assert dapr.invoke.call_count == 1  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_dispatch_pre_no_hooks_returns_continue(self) -> None:
        """No hooks registered for the event; invoke is never called."""
        dapr = _make_dapr()

        routing = _routing_table(hooks={})  # no hooks for any event
        dispatcher = HookDispatcher(dapr)

        result = await dispatcher.dispatch_pre("request:pre", {}, routing)

        assert result.action == "CONTINUE"
        dapr.invoke.assert_not_called()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_dispatch_pre_hook_error_returns_continue(self) -> None:
        """Hook raises an exception; treated as best-effort, result is CONTINUE."""
        dapr = _make_dapr()
        dapr.invoke.side_effect = Exception("connection refused")  # type: ignore[union-attr]

        routing = _routing_table(hooks={"request:pre": ["hook-unreachable"]})
        dispatcher = HookDispatcher(dapr)

        result = await dispatcher.dispatch_pre("request:pre", {}, routing)

        assert result.action == "CONTINUE"

    @pytest.mark.asyncio
    async def test_dispatch_pre_inject_context_accumulates(self) -> None:
        """Multiple INJECT_CONTEXT hooks; context_injection strings are joined."""
        dapr = _make_dapr()

        dapr.invoke.side_effect = [  # type: ignore[union-attr]
            {
                "action": "INJECT_CONTEXT",
                "data": {"context_injection": "first context"},
                "reason": None,
            },
            {
                "action": "INJECT_CONTEXT",
                "data": {"context_injection": "second context"},
                "reason": None,
            },
        ]

        routing = _routing_table(hooks={"request:pre": ["hook-a", "hook-b"]})
        dispatcher = HookDispatcher(dapr)

        result = await dispatcher.dispatch_pre("request:pre", {}, routing)

        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        assert result.data["context_injection"] == "first context\n\nsecond context"
        assert result.data["ephemeral"] is True


# ---------------------------------------------------------------------------
# TestHookDispatcherPostEvent
# ---------------------------------------------------------------------------


class TestHookDispatcherPostEvent:
    """Tests for dispatch_post() covering pub/sub topic publishing."""

    @pytest.mark.asyncio
    async def test_dispatch_post_publishes_with_correct_topic(self) -> None:
        """Event name colons are converted to dots for the Dapr topic."""
        dapr = _make_dapr()

        dispatcher = HookDispatcher(dapr)
        await dispatcher.dispatch_post("request:complete", {"result": "ok"})

        dapr.publish.assert_called_once_with(  # type: ignore[union-attr]
            "pubsub", "request.complete", {"result": "ok"}
        )

    @pytest.mark.asyncio
    async def test_dispatch_post_swallows_errors_silently(self) -> None:
        """Pub/sub errors are swallowed; dispatch_post never raises."""
        dapr = _make_dapr()
        dapr.publish.side_effect = Exception("pubsub unavailable")  # type: ignore[union-attr]

        dispatcher = HookDispatcher(dapr)

        # Must not raise
        await dispatcher.dispatch_post("stream:token", {"text": "hello"})
