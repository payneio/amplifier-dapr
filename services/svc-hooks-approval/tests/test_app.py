import pytest
from fastapi.testclient import TestClient

from svc_hooks_approval.app import create_approval_hook_app


@pytest.fixture
def client():
    """Test client with default (empty) deny list."""
    app = create_approval_hook_app(config={"deny_tools": []})
    return TestClient(app)


@pytest.fixture
def client_with_deny():
    """Test client with 'bash' in deny list."""
    app = create_approval_hook_app(config={"deny_tools": ["bash"]})
    return TestClient(app)


# --- Test 1: healthz ---
def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


# --- Test 2: describe includes hook ---
def test_describe_includes_hook(client):
    response = client.get("/describe")
    assert response.status_code == 200
    data = response.json()
    hooks = data.get("hooks", [])
    assert len(hooks) >= 1
    hook = hooks[0]
    assert hook["name"] == "approval"
    assert "tool:pre" in hook["events"]


# --- Test 3: invoke returns CONTINUE for safe tool ---
def test_invoke_returns_continue(client):
    payload = {"event": "tool:pre", "data": {"tool_name": "web_search"}}
    response = client.post("/hooks/approval/invoke", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "CONTINUE"


# --- Test 4: invoke denies configured tool ---
def test_invoke_denies_configured_tool(client_with_deny):
    payload = {"event": "tool:pre", "data": {"tool_name": "bash"}}
    response = client_with_deny.post("/hooks/approval/invoke", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "DENY"
    assert data["reason"] is not None


# --- Test 5: dapr subscribe returns empty list ---
def test_dapr_subscribe_returns_empty_list(client):
    response = client.get("/dapr/subscribe")
    assert response.status_code == 200
    data = response.json()
    assert data == []


# --- Test 6: module exposes app ---
def test_module_exposes_app():
    from svc_hooks_approval import app as module

    assert hasattr(module, "app")
    from fastapi import FastAPI

    assert isinstance(module.app, FastAPI)
