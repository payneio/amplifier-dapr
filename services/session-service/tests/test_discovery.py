"""Tests for the discovery module — service discovery and routing table construction."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from session_service.discovery import (
    build_routing_table,
    discover_services,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_describe(
    *,
    tools: list[dict] | None = None,
    providers: list[dict] | None = None,
    hooks: list[dict] | None = None,
) -> dict:
    """Build a minimal describe response dict."""
    return {
        "name": "test-service",
        "version": "0.1.0",
        "tools": tools or [],
        "providers": providers or [],
        "hooks": hooks or [],
        "content_paths": [],
    }


# ---------------------------------------------------------------------------
# TestBuildRoutingTable
# ---------------------------------------------------------------------------


class TestBuildRoutingTable:
    """Tests for build_routing_table()."""

    def test_builds_tool_mapping(self) -> None:
        """Tools from describe results are mapped to their app_ids."""
        describe_results = {
            "svc-tools": _make_describe(
                tools=[
                    {
                        "name": "read_file",
                        "description": "Reads a file",
                        "input_schema": {},
                    },
                    {
                        "name": "write_file",
                        "description": "Writes a file",
                        "input_schema": {},
                    },
                ]
            )
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert routing["tools"]["read_file"] == "svc-tools"
        assert routing["tools"]["write_file"] == "svc-tools"

    def test_builds_provider_mapping(self) -> None:
        """Providers from describe results are mapped to their app_ids."""
        describe_results = {
            "svc-providers": _make_describe(
                providers=[
                    {"name": "openai"},
                    {"name": "anthropic"},
                ]
            )
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert routing["providers"]["openai"] == "svc-providers"
        assert routing["providers"]["anthropic"] == "svc-providers"

    def test_builds_hook_mapping(self) -> None:
        """Hook events list is expanded: each event maps to a list containing the app_id."""
        describe_results = {
            "svc-hooks": _make_describe(
                hooks=[
                    {"name": "my-hook", "events": ["before_turn", "after_turn"]},
                ]
            )
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert routing["hooks"]["before_turn"] == ["svc-hooks"]
        assert routing["hooks"]["after_turn"] == ["svc-hooks"]

    def test_collects_tool_specs(self) -> None:
        """Tool capability specs are collected in _tool_specs."""
        tool_spec = {
            "name": "search",
            "description": "Searches the web",
            "input_schema": {"type": "object"},
        }
        describe_results = {"svc-tools": _make_describe(tools=[tool_spec])}
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert len(routing["_tool_specs"]) == 1
        assert routing["_tool_specs"][0] == tool_spec

    def test_multiple_services(self) -> None:
        """Tools, providers, and hooks from multiple services are all merged."""
        describe_results = {
            "svc-a": _make_describe(
                tools=[{"name": "tool_a", "description": "", "input_schema": {}}],
                providers=[{"name": "provider_a"}],
                hooks=[{"name": "hook-a", "events": ["before_turn"]}],
            ),
            "svc-b": _make_describe(
                tools=[{"name": "tool_b", "description": "", "input_schema": {}}],
                providers=[{"name": "provider_b"}],
                hooks=[{"name": "hook-b", "events": ["before_turn", "after_turn"]}],
            ),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        # Tools
        assert routing["tools"]["tool_a"] == "svc-a"
        assert routing["tools"]["tool_b"] == "svc-b"

        # Providers
        assert routing["providers"]["provider_a"] == "svc-a"
        assert routing["providers"]["provider_b"] == "svc-b"

        # Hooks — both services subscribe to before_turn; only svc-b to after_turn
        assert set(routing["hooks"]["before_turn"]) == {"svc-a", "svc-b"}
        assert routing["hooks"]["after_turn"] == ["svc-b"]

        # Tool specs — both collected
        spec_names = {s["name"] for s in routing["_tool_specs"]}
        assert spec_names == {"tool_a", "tool_b"}


# ---------------------------------------------------------------------------
# TestDiscoverServices
# ---------------------------------------------------------------------------


class TestDiscoverServices:
    """Tests for discover_services()."""

    async def test_calls_describe_for_each_service_and_builds_routing_table(
        self,
    ) -> None:
        """discover_services calls _call_describe for each app_id and returns routing table."""
        fake_describe = {
            "name": "fake-service",
            "version": "0.1.0",
            "tools": [{"name": "fake_tool", "description": "", "input_schema": {}}],
            "providers": [],
            "hooks": [],
            "content_paths": [],
        }

        with patch(
            "session_service.discovery._call_describe",
            new_callable=AsyncMock,
            return_value=fake_describe,
        ) as mock_call:
            routing = await discover_services(
                service_app_ids=["svc-a", "svc-b"],
                dapr_url="http://localhost:3500",
                context_app_id="svc-context",
            )

        # _call_describe was called once per service
        assert mock_call.call_count == 2
        called_app_ids = {call.args[0] for call in mock_call.call_args_list}
        assert called_app_ids == {"svc-a", "svc-b"}

        # Routing table contains tools from both
        assert "fake_tool" in routing["tools"]
