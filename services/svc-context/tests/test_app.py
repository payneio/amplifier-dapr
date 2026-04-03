"""Tests for the svc-context FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_context.app import create_context_app

SESSION_ID = "test-session"


class TestModuleLevelApp:
    """Tests for the module-level app object in svc_context.app."""

    def test_module_exposes_app(self) -> None:
        """svc_context.app must expose a module-level FastAPI 'app' object."""
        from svc_context import app as app_module  # noqa: PLC0415

        assert hasattr(app_module, "app"), "app.py must define a module-level 'app'"
        assert isinstance(app_module.app, FastAPI)


class TestContextApp:
    """Tests for the context FastAPI application endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the context app."""
        app = create_context_app()
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe(self, client: TestClient) -> None:
        """GET /describe returns 200 with name svc-context."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-context"

    def test_add_and_get(self, client: TestClient) -> None:
        """POST /context/{session_id}/messages adds a message; GET returns it."""
        # Add a message
        message = {"role": "user", "content": "Hello!"}
        post_response = client.post(f"/context/{SESSION_ID}/messages", json=message)
        assert post_response.status_code == 200
        assert post_response.json() == {"success": True}

        # Retrieve messages
        get_response = client.get(f"/context/{SESSION_ID}/messages")
        assert get_response.status_code == 200
        data = get_response.json()
        assert "messages" in data
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Hello!"

    def test_clear(self, client: TestClient) -> None:
        """POST /context/{session_id}/clear removes all messages."""
        # Add a message first
        client.post(
            f"/context/{SESSION_ID}/messages", json={"role": "user", "content": "msg1"}
        )

        # Clear
        clear_response = client.post(f"/context/{SESSION_ID}/clear")
        assert clear_response.status_code == 200
        assert clear_response.json() == {"success": True}

        # Verify empty
        get_response = client.get(f"/context/{SESSION_ID}/messages")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["messages"] == []

    def test_bulk_set(self, client: TestClient) -> None:
        """PUT /context/{session_id}/messages/bulk replaces all messages."""
        # Add some initial messages
        client.post(
            f"/context/{SESSION_ID}/messages", json={"role": "user", "content": "old"}
        )

        # Bulk replace
        bulk_messages = [
            {"role": "user", "content": "new1"},
            {"role": "assistant", "content": "new2"},
        ]
        put_response = client.put(
            f"/context/{SESSION_ID}/messages/bulk",
            json={"messages": bulk_messages},
        )
        assert put_response.status_code == 200

        # Verify replacement
        get_response = client.get(f"/context/{SESSION_ID}/messages")
        assert get_response.status_code == 200
        data = get_response.json()
        assert len(data["messages"]) == 2
        assert data["messages"][0]["content"] == "new1"
        assert data["messages"][1]["content"] == "new2"

    def test_get_with_query_params(self, client: TestClient) -> None:
        """GET /context/{session_id}/messages accepts context_window and max_output_tokens query params."""
        # Add a message
        client.post(
            f"/context/{SESSION_ID}/messages",
            json={"role": "user", "content": "Hello!"},
        )

        # Query with params
        response = client.get(
            f"/context/{SESSION_ID}/messages",
            params={"context_window": 200000, "max_output_tokens": 8192},
        )
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert len(data["messages"]) == 1

    def test_set_system_prompt(self, client: TestClient) -> None:
        """POST /context/{session_id}/system-prompt sets or replaces the system message."""
        # Set the system prompt
        prompt_response = client.post(
            f"/context/{SESSION_ID}/system-prompt",
            json={"content": "You are a helpful assistant."},
        )
        assert prompt_response.status_code == 200
        assert prompt_response.json() == {"success": True}

        # Verify the system message appears at position 0
        get_response = client.get(f"/context/{SESSION_ID}/messages")
        assert get_response.status_code == 200
        data = get_response.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "system"
        assert data["messages"][0]["content"] == "You are a helpful assistant."

    def test_set_system_prompt_replaces_existing(self, client: TestClient) -> None:
        """POST system-prompt twice replaces the first system message, not appends."""
        r1 = client.post(
            f"/context/{SESSION_ID}/system-prompt", json={"content": "First prompt."}
        )
        assert r1.status_code == 200
        r2 = client.post(
            f"/context/{SESSION_ID}/system-prompt", json={"content": "Second prompt."}
        )
        assert r2.status_code == 200

        data = client.get(f"/context/{SESSION_ID}/messages").json()
        # Should still be exactly one system message
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "system"
        assert data["messages"][0]["content"] == "Second prompt."
