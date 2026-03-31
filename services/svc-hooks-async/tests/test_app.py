"""Tests for the svc-hooks-async FastAPI application."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from svc_hooks_async.app import create_async_hooks_app


@pytest.fixture
def client(tmp_path):
    """Test client with temp log directory."""
    template = str(tmp_path / "{session_id}" / "events.jsonl")
    app = create_async_hooks_app(log_template=template)
    return TestClient(app)


# --- Test 1: healthz ---
def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


# --- Test 2: describe includes 'logging' hook ---
def test_describe_includes_logging(client):
    response = client.get("/describe")
    assert response.status_code == 200
    data = response.json()
    hooks = data.get("hooks", [])
    assert len(hooks) >= 1
    hook_names = [h["name"] for h in hooks]
    assert "logging" in hook_names


# --- Test 3: dapr subscribe returns subscriptions with tool.post topic ---
def test_dapr_subscribe_returns_subscriptions(client):
    response = client.get("/dapr/subscribe")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0, "Subscription list must be non-empty"
    topics = [sub["topic"] for sub in data]
    assert "tool.post" in topics, f"Expected 'tool.post' in {topics}"


# --- Test 3b: dapr subscribe uses correct pubsub component name ---
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


# --- Test 4: event endpoint accepts POST for tool.post ---
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


# --- Test 5: unknown event endpoint returns 404 ---
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


# --- Test 6: module exposes app ---
def test_module_exposes_app():
    from svc_hooks_async import app as module

    assert hasattr(module, "app")
    from fastapi import FastAPI

    assert isinstance(module.app, FastAPI)
