"""Tests for CreateSessionRequest and CreateSessionResponse models."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from session_service.app import (
    CreateSessionRequest,
    CreateSessionResponse,
    create_session_app,
)


class TestCreateSessionModels:
    """Tests for session creation Pydantic models."""

    def test_create_session_request_defaults(self) -> None:
        """CreateSessionRequest with agent_ref='foundation' has machine_config=None."""
        req = CreateSessionRequest(agent_ref="foundation")
        assert req.agent_ref == "foundation"
        assert req.machine_config is None

    def test_create_session_request_with_machine_config(self) -> None:
        """CreateSessionRequest accepts a machine_config dict with type/host/working_dir."""
        config = {
            "type": "ssh",
            "host": "example.com",
            "working_dir": "/workspace",
        }
        req = CreateSessionRequest(agent_ref="default", machine_config=config)
        assert req.agent_ref == "default"
        assert req.machine_config is not None
        assert req.machine_config == config
        assert req.machine_config["type"] == "ssh"
        assert req.machine_config["host"] == "example.com"
        assert req.machine_config["working_dir"] == "/workspace"

    def test_create_session_response_fields(self) -> None:
        """CreateSessionResponse stores session_id and machine_instance_id."""
        resp = CreateSessionResponse(
            session_id="sess-abc123",
            machine_instance_id="machine-xyz",
        )
        assert resp.session_id == "sess-abc123"
        assert resp.machine_instance_id == "machine-xyz"

    def test_create_session_response_no_machine(self) -> None:
        """CreateSessionResponse machine_instance_id defaults to None."""
        resp = CreateSessionResponse(session_id="sess-def456")
        assert resp.session_id == "sess-def456"
        assert resp.machine_instance_id is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(dapr_url: str) -> TestClient:
    """Create a TestClient wrapping create_session_app with the given dapr_url."""
    return TestClient(create_session_app(dapr_url=dapr_url))


# ---------------------------------------------------------------------------
# Tests: POST /sessions/create endpoint
# ---------------------------------------------------------------------------

_EMPTY_ROUTING_TABLE: dict[str, Any] = {
    "tools": {},
    "providers": {},
    "_behaviors": {},
    "_tool_specs": [],
    "context": "svc-context",
    "hook_endpoints": {},
    "hook_priorities": {},
}


class TestCreateSessionEndpoint:
    """Tests for the POST /sessions/create endpoint."""

    @pytest.fixture(autouse=True)
    def isolate_from_yaml(self):
        """Force get_agent_config to use hardcoded AGENTS dict (no YAML loading).

        Ensures tests are environment-agnostic regardless of whether YAML agent
        definitions are present on the local machine.
        """
        with patch(
            "session_service.agents._load_from_yaml",
            return_value=None,
        ):
            yield

    @pytest.fixture()
    def mock_discover(self):
        """Patch discover_services to return an empty routing table without Dapr I/O."""
        with patch(
            "session_service.app.discover_services",
            new_callable=AsyncMock,
            return_value=_EMPTY_ROUTING_TABLE,
        ) as m:
            yield m

    def test_create_session_returns_session_id(self, mock_discover) -> None:
        """POST /sessions/create returns 200 with a non-empty session_id."""
        client = _make_client("http://localhost:3500")
        response = client.post("/sessions/create", json={"agent_ref": "default"})
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert len(data["session_id"]) > 0

    def test_create_session_without_machine_config(self, mock_discover) -> None:
        """machine_instance_id is null when no machine_config is provided."""
        client = _make_client("http://localhost:3500")
        response = client.post("/sessions/create", json={"agent_ref": "default"})
        assert response.status_code == 200
        data = response.json()
        assert data["machine_instance_id"] is None

    def test_create_session_with_machine_config_provisions_instance(self) -> None:
        """When machine_config is provided and machine behavior exists, Dapr POST is made and instance_id returned."""
        machine_config = {
            "type": "ssh",
            "host": "example.com",
            "working_dir": "/workspace",
        }
        routing_with_machine = {
            **_EMPTY_ROUTING_TABLE,
            "_behaviors": {"machine": "svc-machine"},
        }

        # Mock Dapr HTTP call to machine service
        mock_response = MagicMock()
        mock_response.json.return_value = {"instance_id": "machine-abc123"}
        mock_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "session_service.app.discover_services",
                new_callable=AsyncMock,
                return_value=routing_with_machine,
            ),
            patch(
                "session_service.app.httpx.AsyncClient", return_value=mock_http_client
            ),
        ):
            client = _make_client("http://localhost:3500")
            response = client.post(
                "/sessions/create",
                json={"agent_ref": "default", "machine_config": machine_config},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["machine_instance_id"] == "machine-abc123"
        mock_http_client.post.assert_called_once_with(
            "http://localhost:3500/v1.0/invoke/svc-machine/method/instances",
            json={"driver_type": "ssh", "config": machine_config},
            timeout=30.0,
        )

    def test_create_session_stores_session_state(self, mock_discover) -> None:
        """After POST /sessions/create, GET /sessions/{id} returns status=active, turn_count=0."""
        client = _make_client("http://localhost:3500")
        response = client.post("/sessions/create", json={"agent_ref": "default"})
        assert response.status_code == 200
        session_id = response.json()["session_id"]

        get_response = client.get(f"/sessions/{session_id}")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["status"] == "active"
        assert data["turn_count"] == 0


# ---------------------------------------------------------------------------
# Tests: machine_instance_id in turn payload
# ---------------------------------------------------------------------------


class TestTurnPayloadIncludesMachineInstanceId:
    """Verify that machine_instance_id from the session is forwarded in the turn payload."""

    @pytest.fixture(autouse=True)
    def isolate_from_yaml(self):
        """Force get_agent_config to use hardcoded AGENTS dict (no YAML loading)."""
        with patch(
            "session_service.agents._load_from_yaml",
            return_value=None,
        ):
            yield

    @pytest.fixture()
    def mock_discover(self):
        """Patch discover_services to return an empty routing table without Dapr I/O."""
        with patch(
            "session_service.app.discover_services",
            new_callable=AsyncMock,
            return_value=_EMPTY_ROUTING_TABLE,
        ) as m:
            yield m

    @pytest.fixture()
    def mock_transcript(self):
        """Patch load/save transcript so no Dapr I/O occurs."""
        with (
            patch(
                "session_service.app.load_transcript",
                new_callable=AsyncMock,
                return_value=[],
            ) as load,
            patch(
                "session_service.app.save_transcript", new_callable=AsyncMock
            ) as save,
        ):
            yield load, save

    @pytest.fixture()
    def mock_orchestrator(self):
        """Patch httpx.AsyncClient to capture turn POST calls without real I/O."""
        from unittest.mock import MagicMock

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

    def test_turn_payload_includes_machine_instance_id(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """When session has machine_instance_id, it is included in the orchestrator payload."""
        from session_service.app import _sessions

        session_id = "test-session-with-machine"
        _sessions[session_id] = {
            "turn_count": 0,
            "status": "active",
            "machine_instance_id": "inst-abc123",
        }
        try:
            client = _make_client("http://localhost:3500")
            response = client.post(
                f"/sessions/{session_id}/turn",
                json={"prompt": "hello", "agent_ref": "default"},
            )
            assert response.status_code == 200

            # Verify the payload sent to orchestrator contained machine_instance_id
            call_args = mock_orchestrator.post.call_args
            payload = call_args.kwargs.get("json") or call_args.args[1]
            assert payload["machine_instance_id"] == "inst-abc123"
        finally:
            _sessions.pop(session_id, None)

    def test_turn_payload_machine_instance_id_none_when_absent(
        self, mock_discover, mock_transcript, mock_orchestrator
    ) -> None:
        """When session has no machine_instance_id, the field is None in the orchestrator payload."""
        from session_service.app import _sessions

        session_id = "test-session-no-machine"
        # Ensure the session exists but has no machine_instance_id
        _sessions.pop(session_id, None)
        try:
            client = _make_client("http://localhost:3500")
            response = client.post(
                f"/sessions/{session_id}/turn",
                json={"prompt": "hello", "agent_ref": "default"},
            )
            assert response.status_code == 200

            # Verify the payload sent to orchestrator has machine_instance_id=None
            call_args = mock_orchestrator.post.call_args
            payload = call_args.kwargs.get("json") or call_args.args[1]
            assert payload.get("machine_instance_id") is None
        finally:
            _sessions.pop(session_id, None)
