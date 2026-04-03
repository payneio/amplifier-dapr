"""Tests for the GET /sessions/{session_id}/messages endpoint."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from amplifier_service_sdk.models import Message
from session_service.app import _sessions, create_session_app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Create a TestClient for the session-service app with isolated session state."""
    _sessions.clear()
    app = create_session_app(dapr_url="http://localhost:3500")
    yield TestClient(app)
    _sessions.clear()


def test_returns_transcript_from_state_store(client: TestClient) -> None:
    """GET /sessions/{id}/messages returns messages from the Dapr state store."""
    messages = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi there"),
    ]
    with patch(
        "session_service.app.load_transcript",
        new=AsyncMock(return_value=messages),
    ):
        response = client.get("/sessions/test-session/messages")

    assert response.status_code == 200
    data = response.json()
    assert data["messages"] == [m.model_dump() for m in messages]


def test_returns_empty_for_unknown_session(client: TestClient) -> None:
    """GET /sessions/{id}/messages returns empty messages list for unknown sessions."""
    with patch(
        "session_service.app.load_transcript",
        new=AsyncMock(return_value=[]),
    ):
        response = client.get("/sessions/unknown-session/messages")

    assert response.status_code == 200
    data = response.json()
    assert data["messages"] == []


def test_returns_session_id_in_response(client: TestClient) -> None:
    """GET /sessions/{id}/messages includes session_id in the response body."""
    with patch(
        "session_service.app.load_transcript",
        new=AsyncMock(return_value=[]),
    ):
        response = client.get("/sessions/my-session-123/messages")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "my-session-123"
