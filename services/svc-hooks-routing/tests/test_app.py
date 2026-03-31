import pytest
from fastapi.testclient import TestClient

from svc_hooks_routing.app import create_routing_hook_app


SAMPLE_MATRIX = {
    "name": "balanced",
    "roles": {
        "general": {"description": "General purpose tasks"},
        "fast": {"description": "Quick utility tasks"},
    },
}


@pytest.fixture
def client():
    """Test client with no matrix (empty)."""
    app = create_routing_hook_app(matrix={})
    return TestClient(app)


@pytest.fixture
def client_with_matrix():
    """Test client with a populated routing matrix."""
    app = create_routing_hook_app(matrix=SAMPLE_MATRIX)
    return TestClient(app)


# --- Test 1: healthz ---
def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


# --- Test 2: describe includes 'routing' hook ---
def test_describe_includes_routing(client):
    response = client.get("/describe")
    assert response.status_code == 200
    data = response.json()
    hooks = data.get("hooks", [])
    assert len(hooks) >= 1
    hook = hooks[0]
    assert hook["name"] == "routing"


# --- Test 3: invoke no matrix continues ---
def test_invoke_no_matrix_continues(client):
    payload = {"event": "provider:request", "data": {}}
    response = client.post("/hooks/routing/invoke", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "CONTINUE"


# --- Test 4: invoke with matrix injects context ---
def test_invoke_with_matrix_injects_context(client_with_matrix):
    payload = {"event": "provider:request", "data": {}}
    response = client_with_matrix.post("/hooks/routing/invoke", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "INJECT_CONTEXT"
    assert data["data"] is not None
    assert "context_injection" in data["data"]


# --- Test 5: dapr subscribe returns empty list ---
def test_dapr_subscribe_returns_empty_list(client):
    response = client.get("/dapr/subscribe")
    assert response.status_code == 200
    data = response.json()
    assert data == []


# --- Test 6: module exposes app ---
def test_module_exposes_app():
    from svc_hooks_routing import app as module

    assert hasattr(module, "app")
    from fastapi import FastAPI

    assert isinstance(module.app, FastAPI)
