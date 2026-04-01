"""Tests for agent_ref handling in the session-service turn handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from session_service.agents import AGENTS
from session_service.app import create_session_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(dapr_url: str = "http://localhost:3500") -> TestClient:
    return TestClient(create_session_app(dapr_url=dapr_url))


# ---------------------------------------------------------------------------
# Tests: agent_ref resolves service list
# ---------------------------------------------------------------------------


class TestTurnAgentResolution:
    """Verify that agent_ref drives service discovery and provider selection."""

    @pytest.fixture
    def mock_discover(self):
        """Patch discover_services to record calls and return an empty table."""
        with patch(
            "session_service.app.discover_services",
            new_callable=AsyncMock,
            return_value={"tools": {}, "providers": {}, "hooks": {}, "_tool_specs": [], "context": "svc-context", "hook_endpoints": {}, "hook_priorities": {}},
        ) as m:
            yield m

    @pytest.fixture
    def mock_transcript(self):
        """Patch load/save transcript so no Dapr I/O occurs."""
        with (
            patch("session_service.app.load_transcript", new_callable=AsyncMock, return_value=[]) as load,
            patch("session_service.app.save_transcript", new_callable=AsyncMock) as save,
        ):
            yield load, save

    @pytest.fixture
    def mock_orchestrator(self):
        """Patch httpx.AsyncClient so the orchestrator POST succeeds without I/O.

        Note: httpx response.raise_for_status() and response.json() are both
        synchronous, so they must be regular MagicMock (not AsyncMock).
        """
        from unittest.mock import MagicMock

        # Synchronous response object (httpx Response methods are not coroutines)
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"result": "ok", "messages": []})

        with patch("session_service.app.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_http
            yield mock_http

    def test_foundation_agent_uses_foundation_services(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """Sending agent_ref='foundation' discovers the foundation service list."""
        client = _make_client()
        client.post(
            "/sessions/s1/turn",
            json={"prompt": "hello", "agent_ref": "foundation"},
        )
        called_services = mock_discover.call_args[0][0]
        assert "svc-mock-provider" not in called_services, (
            "foundation agent must not include svc-mock-provider"
        )
        assert "svc-providers" in called_services

    def test_default_agent_includes_mock_provider(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """Default agent (no agent_ref) discovers the default service list including svc-mock-provider."""
        client = _make_client()
        client.post(
            "/sessions/s2/turn",
            json={"prompt": "hello"},  # agent_ref defaults to 'default'
        )
        called_services = mock_discover.call_args[0][0]
        assert "svc-mock-provider" in called_services

    def test_foundation_agent_overrides_mock_provider_to_anthropic(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """When agent='foundation' and provider_name='mock', the orchestrator gets 'anthropic'."""
        client = _make_client()
        client.post(
            "/sessions/s3/turn",
            json={"prompt": "hello", "agent_ref": "foundation", "provider_name": "mock"},
        )
        payload = mock_orchestrator.post.call_args[1]["json"]
        assert payload["config"]["provider"] == "anthropic", (
            "foundation agent must upgrade 'mock' provider to 'anthropic'"
        )

    def test_explicit_provider_is_not_overridden(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """An explicit provider_name other than 'mock' is passed through unchanged."""
        client = _make_client()
        client.post(
            "/sessions/s4/turn",
            json={"prompt": "hello", "agent_ref": "foundation", "provider_name": "openai"},
        )
        payload = mock_orchestrator.post.call_args[1]["json"]
        assert payload["config"]["provider"] == "openai"

    def test_foundation_system_prompt_prepended(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """The foundation agent's system_prompt is prepended to the assembled prompt."""
        client = _make_client()
        client.post(
            "/sessions/s5/turn",
            json={"prompt": "hello", "agent_ref": "foundation"},
        )
        payload = mock_orchestrator.post.call_args[1]["json"]
        foundation_prefix = AGENTS["foundation"]["system_prompt"]
        assert payload["system_prompt"].startswith(foundation_prefix), (
            "foundation system_prompt must appear at the start of the assembled system prompt"
        )

    def test_default_agent_has_no_system_prompt_prefix(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """The default agent adds no custom prefix to the assembled system prompt."""
        client = _make_client()
        client.post(
            "/sessions/s6/turn",
            json={"prompt": "hello", "agent_ref": "default"},
        )
        payload = mock_orchestrator.post.call_args[1]["json"]
        # default agent has no system_prompt key, so assembled prompt is unchanged
        assert "You are Amplifier" not in payload["system_prompt"]

    def test_caller_supplied_services_take_priority(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """When the caller supplies an explicit services list it overrides the agent default."""
        client = _make_client()
        custom_services = ["svc-bash", "svc-filesystem"]
        client.post(
            "/sessions/s7/turn",
            json={"prompt": "hello", "agent_ref": "foundation", "services": custom_services},
        )
        called_services = mock_discover.call_args[0][0]
        assert called_services == custom_services
