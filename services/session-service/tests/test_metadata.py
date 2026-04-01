"""Tests for the session-service metadata endpoints (tools, modes, clear)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from session_service.app import create_session_app


@pytest.fixture
def client() -> TestClient:
    """Create a TestClient for the session-service app."""
    app = create_session_app(dapr_url="http://localhost:3500")
    return TestClient(app)


def test_get_tools_returns_empty_before_turn(client: TestClient) -> None:
    """GET /sessions/{id}/tools returns {tools: []} when no turn has been run."""
    response = client.get("/sessions/test-session/tools")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert data["tools"] == []


def test_get_tools_returns_empty_for_unknown_session(client: TestClient) -> None:
    """GET /sessions/{id}/tools returns {tools: []} for an unknown session."""
    response = client.get("/sessions/nonexistent-session/tools")
    assert response.status_code == 200
    data = response.json()
    assert data["tools"] == []


def test_get_modes_returns_empty(client: TestClient) -> None:
    """GET /sessions/{id}/modes returns {modes: []} as a placeholder."""
    response = client.get("/sessions/test-session/modes")
    assert response.status_code == 200
    data = response.json()
    assert "modes" in data
    assert data["modes"] == []


def test_clear_session_returns_ok(client: TestClient) -> None:
    """POST /sessions/{id}/clear resets session and returns {status: 'cleared'}."""
    # First, ensure session exists by injecting it
    session_id = "test-clear-session"

    # Clear a session that doesn't exist yet - should still work
    response = client.post(f"/sessions/{session_id}/clear")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cleared"


def test_clear_session_resets_turn_count(client: TestClient) -> None:
    """POST /sessions/{id}/clear resets turn_count to 0 and status to 'active'."""
    from session_service.app import _sessions  # noqa: PLC0415

    session_id = "test-reset-session"
    # Manually put a session with some state
    _sessions[session_id] = {"turn_count": 5, "status": "active"}

    response = client.post(f"/sessions/{session_id}/clear")
    assert response.status_code == 200
    assert response.json()["status"] == "cleared"

    # Verify session state was reset
    assert _sessions[session_id]["turn_count"] == 0
    assert _sessions[session_id]["status"] == "active"
