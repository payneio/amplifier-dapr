"""Tests verifying Phase 3b hook service discovery and routing-table construction.

Phase 3b introduces:
  svc-hooks-approval  — sync hook on 'tool:pre_invoke'
  svc-hooks-routing   — sync hook on 'session:start', 'session:end'
  svc-hooks-async     — async hook (pub/sub) — must NOT appear in routing_table['hooks']
  svc-hooks-shell     — sync hook on 'tool:pre_invoke' with higher priority
  svc-delegation      — delegation tool service

This file also verifies:
  - hook_endpoints dict is populated with hooks/{name}/invoke
  - hook_priorities dict is populated with priority values
  - async hooks are excluded from routing_table['hooks']
  - tools and hooks coexist in the same routing table batch
  - DEFAULT_SERVICES includes all new Phase 3b service app-ids
"""

from __future__ import annotations

from session_service.discovery import build_routing_table
from session_service.app import DEFAULT_SERVICES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _describe_hooks_approval() -> dict:
    """Minimal /describe response for svc-hooks-approval (sync hook)."""
    return {
        "name": "svc-hooks-approval",
        "version": "0.1.0",
        "tools": [],
        "providers": [],
        "hooks": [
            {
                "name": "approval",
                "mode": "sync",
                "events": ["tool:pre_invoke"],
                "priority": 10,
            }
        ],
        "content_paths": [],
    }


def _describe_hooks_routing() -> dict:
    """Minimal /describe response for svc-hooks-routing (sync hook, multiple events)."""
    return {
        "name": "svc-hooks-routing",
        "version": "0.1.0",
        "tools": [],
        "providers": [],
        "hooks": [
            {
                "name": "routing",
                "mode": "sync",
                "events": ["session:start", "session:end"],
                "priority": 5,
            }
        ],
        "content_paths": [],
    }


def _describe_hooks_async() -> dict:
    """Minimal /describe response for svc-hooks-async (async hook, pub/sub)."""
    return {
        "name": "svc-hooks-async",
        "version": "0.1.0",
        "tools": [],
        "providers": [],
        "hooks": [
            {
                "name": "async-logger",
                "mode": "async",
                "events": ["tool:post_invoke", "session:end"],
                "priority": 0,
            }
        ],
        "content_paths": [],
    }


def _describe_hooks_shell() -> dict:
    """Minimal /describe response for svc-hooks-shell (sync hook, high priority)."""
    return {
        "name": "svc-hooks-shell",
        "version": "0.1.0",
        "tools": [],
        "providers": [],
        "hooks": [
            {
                "name": "shell-gate",
                "mode": "sync",
                "events": ["tool:pre_invoke"],
                "priority": 20,
            }
        ],
        "content_paths": [],
    }


def _describe_with_tools_and_hook() -> dict:
    """Service that has both tools and a sync hook."""
    return {
        "name": "svc-mixed",
        "version": "0.1.0",
        "tools": [
            {"name": "run_bash", "description": "Run bash command", "input_schema": {}},
        ],
        "providers": [],
        "hooks": [
            {
                "name": "bash-gate",
                "mode": "sync",
                "events": ["tool:pre_invoke"],
                "priority": 15,
            }
        ],
        "content_paths": [],
    }


# ---------------------------------------------------------------------------
# Test 1 — sync hooks are mapped to the correct events
# ---------------------------------------------------------------------------


class TestSyncHookRouting:
    """Sync hooks are registered in routing_table['hooks'] by event."""

    def test_routes_pre_hooks_by_event(self) -> None:
        """Sync hooks with mode='sync' are added to routing_table['hooks'] for each event."""
        describe_results = {
            "svc-hooks-approval": _describe_hooks_approval(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert "tool:pre_invoke" in routing["hooks"]
        assert "svc-hooks-approval" in routing["hooks"]["tool:pre_invoke"]

    def test_multiple_sync_services_share_event(self) -> None:
        """Multiple sync services subscribing to the same event are all listed."""
        describe_results = {
            "svc-hooks-approval": _describe_hooks_approval(),
            "svc-hooks-shell": _describe_hooks_shell(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        subscribers = routing["hooks"]["tool:pre_invoke"]
        assert "svc-hooks-approval" in subscribers
        assert "svc-hooks-shell" in subscribers

    def test_sync_hook_multiple_events(self) -> None:
        """A sync hook registering multiple events maps to each individually."""
        describe_results = {
            "svc-hooks-routing": _describe_hooks_routing(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert "svc-hooks-routing" in routing["hooks"]["session:start"]
        assert "svc-hooks-routing" in routing["hooks"]["session:end"]


# ---------------------------------------------------------------------------
# Test 2 — hook_endpoints populated
# ---------------------------------------------------------------------------


class TestHookEndpoints:
    """routing_table['hook_endpoints'] is populated with hooks/{name}/invoke paths."""

    def test_hook_endpoints_populated(self) -> None:
        """hook_endpoints maps app_id to hooks/{hook_name}/invoke."""
        describe_results = {
            "svc-hooks-approval": _describe_hooks_approval(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert "hook_endpoints" in routing
        assert (
            routing["hook_endpoints"]["svc-hooks-approval"] == "hooks/approval/invoke"
        )

    def test_hook_endpoints_multiple_services(self) -> None:
        """hook_endpoints contains entries for each sync hook service."""
        describe_results = {
            "svc-hooks-approval": _describe_hooks_approval(),
            "svc-hooks-shell": _describe_hooks_shell(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert (
            routing["hook_endpoints"]["svc-hooks-approval"] == "hooks/approval/invoke"
        )
        assert routing["hook_endpoints"]["svc-hooks-shell"] == "hooks/shell-gate/invoke"


# ---------------------------------------------------------------------------
# Test 3 — hook_priorities populated
# ---------------------------------------------------------------------------


class TestHookPriorities:
    """routing_table['hook_priorities'] is populated with integer priority values."""

    def test_hook_priorities_populated(self) -> None:
        """hook_priorities maps app_id to the hook's priority value."""
        describe_results = {
            "svc-hooks-approval": _describe_hooks_approval(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert "hook_priorities" in routing
        assert routing["hook_priorities"]["svc-hooks-approval"] == 10

    def test_hook_priorities_multiple_services(self) -> None:
        """hook_priorities contains entries for all sync hook services."""
        describe_results = {
            "svc-hooks-approval": _describe_hooks_approval(),
            "svc-hooks-shell": _describe_hooks_shell(),
            "svc-hooks-routing": _describe_hooks_routing(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert routing["hook_priorities"]["svc-hooks-approval"] == 10
        assert routing["hook_priorities"]["svc-hooks-shell"] == 20
        assert routing["hook_priorities"]["svc-hooks-routing"] == 5

    def test_hook_missing_priority_defaults_to_sdk_default(self) -> None:
        """A hook that omits 'priority' must default to 50, matching HookRegistration.priority."""
        describe_no_priority = {
            "name": "svc-no-priority",
            "version": "0.1.0",
            "tools": [],
            "providers": [],
            "hooks": [
                {
                    "name": "noprio",
                    "mode": "sync",
                    "events": ["tool:pre"],
                    # 'priority' key intentionally absent
                }
            ],
            "content_paths": [],
        }
        routing = build_routing_table(
            {"svc-no-priority": describe_no_priority}, context_app_id="svc-context"
        )
        assert routing["hook_priorities"]["svc-no-priority"] == 50, (
            "Missing priority should default to 50 (SDK HookRegistration default), not 0"
        )


# ---------------------------------------------------------------------------
# Test 4 — async hooks are excluded from routing_table['hooks']
# ---------------------------------------------------------------------------


class TestAsyncHookExclusion:
    """Hooks with mode='async' are NOT added to routing_table['hooks']."""

    def test_async_hooks_not_in_routing_table_hooks(self) -> None:
        """Async hooks (mode='async') must not appear in routing_table['hooks']."""
        describe_results = {
            "svc-hooks-async": _describe_hooks_async(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        # The events this async hook would subscribe to must not have svc-hooks-async
        assert "svc-hooks-async" not in routing["hooks"].get("tool:post_invoke", [])
        assert "svc-hooks-async" not in routing["hooks"].get("session:end", [])

    def test_async_hook_not_in_endpoints(self) -> None:
        """Async hooks should not appear in hook_endpoints."""
        describe_results = {
            "svc-hooks-async": _describe_hooks_async(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert "svc-hooks-async" not in routing.get("hook_endpoints", {})

    def test_mixed_sync_and_async_only_sync_in_hooks(self) -> None:
        """When both sync and async hooks exist, only sync ones appear in hooks."""
        describe_results = {
            "svc-hooks-routing": _describe_hooks_routing(),  # sync: session:start, session:end
            "svc-hooks-async": _describe_hooks_async(),  # async: tool:post_invoke, session:end
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        # session:end: routing (sync) should be there, async (async) should not
        session_end_subscribers = routing["hooks"].get("session:end", [])
        assert "svc-hooks-routing" in session_end_subscribers
        assert "svc-hooks-async" not in session_end_subscribers

        # tool:post_invoke: only async hook subscribes — should be empty or missing
        assert "svc-hooks-async" not in routing["hooks"].get("tool:post_invoke", [])


# ---------------------------------------------------------------------------
# Test 5 — tools and hooks coexist in same batch
# ---------------------------------------------------------------------------


class TestToolsAndHooksCoexist:
    """Tools and hooks can be registered by different services in the same routing table."""

    def test_tools_and_hooks_coexist(self) -> None:
        """A routing table with both tool services and hook services works correctly."""
        describe_results = {
            "svc-hooks-approval": _describe_hooks_approval(),
            "svc-hooks-routing": _describe_hooks_routing(),
            "svc-hooks-async": _describe_hooks_async(),
            "svc-mixed": _describe_with_tools_and_hook(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        # Tool from svc-mixed
        assert routing["tools"]["run_bash"] == "svc-mixed"

        # Sync hooks
        pre_invoke_subscribers = routing["hooks"]["tool:pre_invoke"]
        assert "svc-hooks-approval" in pre_invoke_subscribers
        assert "svc-mixed" in pre_invoke_subscribers  # mixed service also has sync hook

        # Async hooks excluded
        assert "svc-hooks-async" not in routing["hooks"].get("tool:post_invoke", [])

        # hook_endpoints
        assert (
            routing["hook_endpoints"]["svc-hooks-approval"] == "hooks/approval/invoke"
        )
        assert routing["hook_endpoints"]["svc-mixed"] == "hooks/bash-gate/invoke"

        # hook_priorities
        assert routing["hook_priorities"]["svc-hooks-approval"] == 10
        assert routing["hook_priorities"]["svc-mixed"] == 15


# ---------------------------------------------------------------------------
# Test 6 — build_routing_table populates hooks, hook_endpoints, hook_priorities
# ---------------------------------------------------------------------------


class TestBuildRoutingTableWithHooks:
    """build_routing_table correctly populates hook keys for Phase 3b services."""

    def test_hooks_key_populated_for_sync_hooks(self) -> None:
        """build_routing_table adds sync hooks to routing_table['hooks'] by event."""
        describe_results = {
            "svc-hooks-approval": _describe_hooks_approval(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert "hooks" in routing
        assert "tool:pre_invoke" in routing["hooks"]
        assert "svc-hooks-approval" in routing["hooks"]["tool:pre_invoke"]

    def test_hook_endpoints_key_populated(self) -> None:
        """build_routing_table populates routing_table['hook_endpoints'] for sync hooks."""
        describe_results = {
            "svc-hooks-routing": _describe_hooks_routing(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert "hook_endpoints" in routing
        assert "svc-hooks-routing" in routing["hook_endpoints"]
        assert routing["hook_endpoints"]["svc-hooks-routing"] == "hooks/routing/invoke"

    def test_hook_priorities_key_populated(self) -> None:
        """build_routing_table populates routing_table['hook_priorities'] for sync hooks."""
        describe_results = {
            "svc-hooks-shell": _describe_hooks_shell(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert "hook_priorities" in routing
        assert routing["hook_priorities"]["svc-hooks-shell"] == 20

    def test_async_hooks_excluded_from_routing_table(self) -> None:
        """build_routing_table excludes async hooks from routing_table['hooks']."""
        describe_results = {
            "svc-hooks-async": _describe_hooks_async(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert "svc-hooks-async" not in routing["hooks"].get("tool:post_invoke", [])
        assert "svc-hooks-async" not in routing["hooks"].get("session:end", [])
        assert "svc-hooks-async" not in routing.get("hook_endpoints", {})

    def test_full_phase3b_routing_table(self) -> None:
        """build_routing_table correctly handles all Phase 3b hook services together."""
        describe_results = {
            "svc-hooks-approval": _describe_hooks_approval(),
            "svc-hooks-routing": _describe_hooks_routing(),
            "svc-hooks-async": _describe_hooks_async(),
            "svc-hooks-shell": _describe_hooks_shell(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        # Sync hooks mapped by event
        assert "svc-hooks-approval" in routing["hooks"]["tool:pre_invoke"]
        assert "svc-hooks-shell" in routing["hooks"]["tool:pre_invoke"]
        assert "svc-hooks-routing" in routing["hooks"]["session:start"]
        assert "svc-hooks-routing" in routing["hooks"]["session:end"]

        # Async hook excluded
        assert "svc-hooks-async" not in routing["hooks"].get("tool:post_invoke", [])

        # hook_endpoints for sync services
        assert (
            routing["hook_endpoints"]["svc-hooks-approval"] == "hooks/approval/invoke"
        )
        assert routing["hook_endpoints"]["svc-hooks-shell"] == "hooks/shell-gate/invoke"
        assert routing["hook_endpoints"]["svc-hooks-routing"] == "hooks/routing/invoke"
        assert "svc-hooks-async" not in routing["hook_endpoints"]

        # hook_priorities
        assert routing["hook_priorities"]["svc-hooks-approval"] == 10
        assert routing["hook_priorities"]["svc-hooks-shell"] == 20
        assert routing["hook_priorities"]["svc-hooks-routing"] == 5


# ---------------------------------------------------------------------------
# Test 7 — DEFAULT_SERVICES contains Phase 3b services
# ---------------------------------------------------------------------------


class TestDefaultServicesPhase3b:
    """DEFAULT_SERVICES contains all Phase 3b service app-ids."""

    def test_default_services_contains_phase3b_services(self) -> None:
        """DEFAULT_SERVICES must include all Phase 3b service app-ids."""
        required = {
            "svc-delegation",
            "svc-hooks-approval",
            "svc-hooks-routing",
            "svc-hooks-async",
            "svc-hooks-shell",
        }
        assert required.issubset(set(DEFAULT_SERVICES)), (
            f"Missing from DEFAULT_SERVICES: {required - set(DEFAULT_SERVICES)}"
        )
