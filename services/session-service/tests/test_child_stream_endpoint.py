"""Tests for the streaming child turn endpoint in session-service."""

from __future__ import annotations

from fastapi.testclient import TestClient

from session_service.app import create_session_app


class TestChildStreamEndpoint:
    """Tests for the POST /sessions/{id}/turn/stream child endpoint."""

    def test_endpoint_registered(self) -> None:
        """POST /sessions/{id}/turn/stream returns non-404 (endpoint is registered)."""
        app = create_session_app(dapr_url="http://localhost:3500")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/sessions/test-child-123/turn/stream",
            json={"prompt": "hello from child"},
        )
        assert response.status_code != 404
