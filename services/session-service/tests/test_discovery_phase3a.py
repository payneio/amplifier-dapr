"""Tests verifying Phase 3a service discovery and routing-table construction.

Phase 3a introduces:
  svc-filesystem  — tools: read_file, write_file, edit_file
  svc-search      — tools: grep, glob
  svc-providers   — providers: anthropic, openai
  svc-context     — stored as routing_table['context']

This file also verifies the DEFAULT_SERVICES constant and the turn-handler
fallback that uses it when TurnRequest.services is empty.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from session_service.discovery import build_routing_table
from session_service.app import DEFAULT_SERVICES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _describe_filesystem() -> dict:
    """Minimal /describe response for svc-filesystem."""
    return {
        "name": "svc-filesystem",
        "version": "0.1.0",
        "tools": [
            {"name": "read_file", "description": "Read a file", "input_schema": {}},
            {"name": "write_file", "description": "Write a file", "input_schema": {}},
            {"name": "edit_file", "description": "Edit a file", "input_schema": {}},
        ],
        "providers": [],
        "hooks": [],
        "content_paths": [],
    }


def _describe_search() -> dict:
    """Minimal /describe response for svc-search."""
    return {
        "name": "svc-search",
        "version": "0.1.0",
        "tools": [
            {"name": "grep", "description": "Search file contents", "input_schema": {}},
            {
                "name": "glob",
                "description": "Find files by pattern",
                "input_schema": {},
            },
        ],
        "providers": [],
        "hooks": [],
        "content_paths": [],
    }


def _describe_providers() -> dict:
    """Minimal /describe response for svc-providers."""
    return {
        "name": "svc-providers",
        "version": "0.1.0",
        "tools": [],
        "providers": [
            {"name": "anthropic"},
            {"name": "openai"},
        ],
        "hooks": [],
        "content_paths": [],
    }


# ---------------------------------------------------------------------------
# Test 1 – routing table for svc-filesystem and svc-search
# ---------------------------------------------------------------------------


class TestPhase3aToolRouting:
    """build_routing_table correctly maps Phase 3a tool services."""

    def test_filesystem_tools_route_to_svc_filesystem(self) -> None:
        """read_file, write_file, edit_file must all map to svc-filesystem."""
        describe_results = {"svc-filesystem": _describe_filesystem()}
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert routing["tools"]["read_file"] == "svc-filesystem"
        assert routing["tools"]["write_file"] == "svc-filesystem"
        assert routing["tools"]["edit_file"] == "svc-filesystem"

    def test_search_tools_route_to_svc_search(self) -> None:
        """grep and glob must both map to svc-search."""
        describe_results = {"svc-search": _describe_search()}
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert routing["tools"]["grep"] == "svc-search"
        assert routing["tools"]["glob"] == "svc-search"


# ---------------------------------------------------------------------------
# Test 2 – routing table for svc-providers and context
# ---------------------------------------------------------------------------


class TestPhase3aProviderRouting:
    """build_routing_table correctly maps Phase 3a provider service and context."""

    def test_providers_route_to_svc_providers(self) -> None:
        """anthropic and openai providers must map to svc-providers."""
        describe_results = {"svc-providers": _describe_providers()}
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert routing["providers"]["anthropic"] == "svc-providers"
        assert routing["providers"]["openai"] == "svc-providers"

    def test_context_app_id_is_stored(self) -> None:
        """The context_app_id passed to build_routing_table is stored in the result."""
        describe_results: dict = {}
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        assert routing["context"] == "svc-context"


# ---------------------------------------------------------------------------
# Test 3 – full Phase 3a routing table (all services combined)
# ---------------------------------------------------------------------------


class TestPhase3aFullRouting:
    """build_routing_table handles all Phase 3a services combined."""

    def test_full_phase3a_routing_table(self) -> None:
        """All Phase 3a tools and providers resolve correctly when all services are included."""
        describe_results = {
            "svc-filesystem": _describe_filesystem(),
            "svc-search": _describe_search(),
            "svc-providers": _describe_providers(),
        }
        routing = build_routing_table(describe_results, context_app_id="svc-context")

        # Tools
        assert routing["tools"]["read_file"] == "svc-filesystem"
        assert routing["tools"]["write_file"] == "svc-filesystem"
        assert routing["tools"]["edit_file"] == "svc-filesystem"
        assert routing["tools"]["grep"] == "svc-search"
        assert routing["tools"]["glob"] == "svc-search"

        # Providers
        assert routing["providers"]["anthropic"] == "svc-providers"
        assert routing["providers"]["openai"] == "svc-providers"

        # Context
        assert routing["context"] == "svc-context"

        # Tool specs collected (5 tools from filesystem + search)
        tool_names = {s["name"] for s in routing["_tool_specs"]}
        assert tool_names == {"read_file", "write_file", "edit_file", "grep", "glob"}


# ---------------------------------------------------------------------------
# Test 4 – DEFAULT_SERVICES constant
# ---------------------------------------------------------------------------


class TestDefaultServicesList:
    """DEFAULT_SERVICES constant contains all Phase 3a services."""

    def test_default_services_contains_phase3a_services(self) -> None:
        """DEFAULT_SERVICES must include all required service app-ids."""
        required = {
            "svc-machine",
            "svc-web",
            "svc-skills",
            "svc-todo",
            "svc-modes",
            "svc-mock-provider",
            "svc-providers",
        }
        assert required.issubset(set(DEFAULT_SERVICES)), (
            f"Missing from DEFAULT_SERVICES: {required - set(DEFAULT_SERVICES)}"
        )


# ---------------------------------------------------------------------------
# Test 5 – turn handler uses DEFAULT_SERVICES when services list is empty
# ---------------------------------------------------------------------------


class TestTurnHandlerDefaultServices:
    """Turn handler uses DEFAULT_SERVICES when TurnRequest.services is empty."""

    @pytest.fixture(autouse=True)
    def isolate_from_yaml(self):
        """Force get_agent_config to use the hardcoded AGENTS dict (no YAML loading)."""
        with patch(
            "session_service.agents._load_from_yaml",
            return_value=None,
        ):
            yield

    def test_empty_services_triggers_default_list(self) -> None:
        """discover_services is called with DEFAULT_SERVICES when request.services == []."""
        import httpx  # noqa: PLC0415
        from unittest.mock import MagicMock  # noqa: PLC0415

        from session_service.app import create_session_app  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        captured_app_ids: list[list[str]] = []

        async def fake_discover(
            service_app_ids: list[str], dapr_url: str, **kwargs: object
        ) -> dict:
            captured_app_ids.append(list(service_app_ids))
            return {
                "tools": {},
                "providers": {},
                "hooks": {},
                "_tool_specs": [],
                "context": "svc-context",
            }

        # Build a minimal real httpx.Response so raise_for_status() works
        orch_response = httpx.Response(
            200,
            json={"result": "ok", "messages": []},
            request=httpx.Request(
                "POST",
                "http://localhost:3500/v1.0/invoke/svc-orchestrator/method/orchestrator/execute",
            ),
        )

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
        mock_async_client.__aexit__ = AsyncMock(return_value=None)
        mock_async_client.post = AsyncMock(return_value=orch_response)

        with (
            patch("session_service.app.discover_services", side_effect=fake_discover),
            patch(
                "session_service.app.load_transcript",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "session_service.app.save_transcript",
                new_callable=AsyncMock,
            ),
            patch(
                "session_service.app.httpx.AsyncClient", return_value=mock_async_client
            ),
        ):
            app = create_session_app(dapr_url="http://localhost:3500")
            client = TestClient(app)
            # services is omitted → defaults to []
            client.post(
                "/sessions/test-sess/turn",
                json={"prompt": "hello"},
            )
            # Verify discover_services was called with the DEFAULT_SERVICES
            assert len(captured_app_ids) == 1, "discover_services was not called"
            called_with = set(captured_app_ids[0])
            required = {
                "svc-machine",
                "svc-providers",
            }
            assert required.issubset(called_with), (
                f"Default services missing from discover call: {required - called_with}"
            )
