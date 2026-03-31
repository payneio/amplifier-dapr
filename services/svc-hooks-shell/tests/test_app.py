"""Tests for the svc-hooks-shell FastAPI application."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from svc_hooks_shell.app import create_shell_hook_app


@pytest.fixture
def client(tmp_path):
    """Test client with no hooks directory (tmp_path has no scripts)."""
    app = create_shell_hook_app(hooks_dir=tmp_path)
    return TestClient(app)


# --- Test 1: healthz ---
def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


# --- Test 2: describe includes 'shell' hook ---
def test_describe_includes_shell(client):
    response = client.get("/describe")
    assert response.status_code == 200
    data = response.json()
    hooks = data.get("hooks", [])
    assert len(hooks) >= 1
    hook_names = [h["name"] for h in hooks]
    assert any("shell" in name for name in hook_names), (
        f"No 'shell' hook found in {hook_names}"
    )


# --- Test 3: invoke tool:pre with no scripts returns CONTINUE ---
def test_invoke_tool_pre_continues_no_scripts(client):
    payload = {"event": "tool:pre", "data": {"tool_name": "bash"}}
    response = client.post("/hooks/shell/invoke", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "CONTINUE"


# --- Test 4: dapr subscribe returns subscriptions with async events ---
def test_dapr_subscribe_returns_subscriptions(client):
    response = client.get("/dapr/subscribe")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0, "Subscription list must be non-empty"
    topics = [sub["topic"] for sub in data]
    assert "tool.post" in topics, f"Expected 'tool.post' in {topics}"


# --- Test 4b: dapr subscribe uses correct pubsub component name ---
def test_dapr_subscribe_pubsubname_matches_component(client):
    """pubsubname must match the Dapr pubsub component name ('pubsub'), not 'amplifier'."""
    response = client.get("/dapr/subscribe")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    for sub in data:
        assert sub["pubsubname"] == "pubsub", (
            f"pubsubname must be 'pubsub' (the Dapr component name), got {sub['pubsubname']!r}"
        )


# --- Test 5: event endpoint accepts POST for tool.post ---
def test_event_endpoint_accepts_tool_post(client):
    envelope = {
        "specversion": "1.0",
        "type": "tool.post",
        "source": "amplifier",
        "id": "abc-123",
        "datacontenttype": "application/json",
        "data": {"session_id": "test-session", "tool": "bash"},
    }
    response = client.post("/events/tool.post", json=envelope)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"


# --- Test 6: unknown event endpoint returns 404 ---
def test_unknown_event_endpoint_returns_404(client):
    envelope = {
        "specversion": "1.0",
        "type": "unknown.topic",
        "source": "amplifier",
        "id": "xyz-999",
        "datacontenttype": "application/json",
        "data": {"session_id": "test-session"},
    }
    response = client.post("/events/unknown.topic", json=envelope)
    assert response.status_code == 404
