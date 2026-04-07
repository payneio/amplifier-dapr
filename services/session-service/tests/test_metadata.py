"""Tests for the session-service metadata endpoints (tools, modes, clear)."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from session_service.app import _sessions, create_session_app

_EMPTY_ROUTING_TABLE: dict[str, Any] = {
    "tools": {},
    "providers": {},
    "hooks": {},
    "hook_endpoints": {},
    "hook_priorities": {},
    "_tool_specs": [],
    "_modes": [],
    "_agents": [],
    "_content_services": {},
    "context": "svc-context",
}

_SAMPLE_ROUTING_TABLE: dict[str, Any] = {
    "tools": {"bash": "svc-bash", "read_file": "svc-filesystem"},
    "providers": {},
    "hooks": {},
    "hook_endpoints": {},
    "hook_priorities": {},
    "_tool_specs": [
        {"name": "bash", "description": "Run shell commands"},
        {"name": "read_file", "description": "Read a file"},
    ],
    "_modes": [
        {"name": "plan", "description": "Think and discuss"},
        {"name": "review", "description": "Code review mode"},
    ],
    "_agents": [
        {"name": "zen-architect", "description": "Designs module specs"},
        {"name": "modular-builder", "description": "Builds modules"},
    ],
    "_content_services": {},
    "context": "svc-context",
}


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Create a TestClient for the session-service app with isolated session state."""
    _sessions.clear()
    app = create_session_app(dapr_url="http://localhost:3500")
    yield TestClient(app)
    _sessions.clear()


# ---------------------------------------------------------------------------
# /tools
# ---------------------------------------------------------------------------


def test_get_tools_runs_discovery_when_no_routing_table(client: TestClient) -> None:
    """/tools runs service discovery when no routing table is cached yet."""
    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_EMPTY_ROUTING_TABLE),
    ) as mock_discover:
        response = client.get("/sessions/test-session/tools")

    assert response.status_code == 200
    assert response.json() == {"tools": []}
    mock_discover.assert_awaited_once()


def test_get_tools_returns_specs_from_discovered_routing_table(
    client: TestClient,
) -> None:
    """/tools returns tool specs populated by on-demand discovery."""
    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_SAMPLE_ROUTING_TABLE),
    ):
        response = client.get("/sessions/test-session/tools")

    assert response.status_code == 200
    data = response.json()
    assert len(data["tools"]) == 2
    names = {t["name"] for t in data["tools"]}
    assert names == {"bash", "read_file"}


def test_get_tools_returns_specs_from_cached_routing_table(client: TestClient) -> None:
    """/tools reads tool specs from the session's stored routing table (no re-discovery)."""
    session_id = "cached-session"
    _sessions[session_id] = {
        "turn_count": 1,
        "status": "active",
        "routing_table": _SAMPLE_ROUTING_TABLE,
    }

    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_EMPTY_ROUTING_TABLE),
    ) as mock_discover:
        response = client.get(f"/sessions/{session_id}/tools")

    assert response.status_code == 200
    data = response.json()
    assert len(data["tools"]) == 2
    # Discovery should NOT have been called because we had a cached table.
    mock_discover.assert_not_awaited()


def test_get_tools_caches_routing_table_for_subsequent_calls(
    client: TestClient,
) -> None:
    """/tools stores the discovered routing table so repeat calls skip re-discovery."""
    session_id = "new-session"

    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_SAMPLE_ROUTING_TABLE),
    ) as mock_discover:
        # First call — triggers discovery
        client.get(f"/sessions/{session_id}/tools")
        # Second call — should use cached routing table
        client.get(f"/sessions/{session_id}/tools")

    assert mock_discover.await_count == 1, (
        "Discovery should only run once; second call uses cache"
    )


# ---------------------------------------------------------------------------
# /modes
# ---------------------------------------------------------------------------


def test_get_modes_runs_discovery_when_no_routing_table(client: TestClient) -> None:
    """/modes runs service discovery when no routing table is cached yet."""
    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_EMPTY_ROUTING_TABLE),
    ) as mock_discover:
        response = client.get("/sessions/test-session/modes")

    assert response.status_code == 200
    assert response.json() == {"modes": []}
    mock_discover.assert_awaited_once()


def test_get_modes_returns_modes_from_discovered_routing_table(
    client: TestClient,
) -> None:
    """/modes returns mode specs populated by on-demand discovery."""
    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_SAMPLE_ROUTING_TABLE),
    ):
        response = client.get("/sessions/test-session/modes")

    assert response.status_code == 200
    data = response.json()
    assert len(data["modes"]) == 2
    names = {m["name"] for m in data["modes"]}
    assert names == {"plan", "review"}


def test_get_modes_returns_modes_from_cached_routing_table(client: TestClient) -> None:
    """/modes reads mode specs from the session's stored routing table (no re-discovery)."""
    session_id = "cached-modes-session"
    _sessions[session_id] = {
        "turn_count": 1,
        "status": "active",
        "routing_table": _SAMPLE_ROUTING_TABLE,
    }

    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_EMPTY_ROUTING_TABLE),
    ) as mock_discover:
        response = client.get(f"/sessions/{session_id}/modes")

    assert response.status_code == 200
    data = response.json()
    assert len(data["modes"]) == 2
    # Discovery should NOT have been called because we had a cached table.
    mock_discover.assert_not_awaited()


def test_get_modes_caches_routing_table_for_subsequent_calls(
    client: TestClient,
) -> None:
    """/modes stores the discovered routing table so repeat calls skip re-discovery."""
    session_id = "new-modes-session"

    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_SAMPLE_ROUTING_TABLE),
    ) as mock_discover:
        # First call — triggers discovery
        client.get(f"/sessions/{session_id}/modes")
        # Second call — should use cached routing table
        client.get(f"/sessions/{session_id}/modes")

    assert mock_discover.await_count == 1, (
        "Discovery should only run once; second call uses cache"
    )


def test_get_modes_does_not_call_svc_modes_directly(client: TestClient) -> None:
    """/modes must NOT call svc-modes directly via Dapr; modes come from the routing table."""
    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_SAMPLE_ROUTING_TABLE),
    ):
        # If the endpoint were still calling svc-modes directly, this would fail
        # because httpx.AsyncClient is NOT patched here.
        response = client.get("/sessions/test-session/modes")

    assert response.status_code == 200
    # Modes should come from the routing table, not a direct svc-modes call
    data = response.json()
    assert "modes" in data


# ---------------------------------------------------------------------------
# /clear
# ---------------------------------------------------------------------------


def test_clear_session_returns_ok(client: TestClient) -> None:
    """POST /sessions/{id}/clear resets session and returns {status: 'cleared'}."""
    session_id = "test-clear-session"

    # Clear a session that doesn't exist yet - should still work
    response = client.post(f"/sessions/{session_id}/clear")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cleared"


def test_clear_session_resets_turn_count(client: TestClient) -> None:
    """POST /sessions/{id}/clear resets turn_count to 0 and status to 'active'."""
    session_id = "test-reset-session"
    # Manually put a session with some state
    _sessions[session_id] = {"turn_count": 5, "status": "active"}

    response = client.post(f"/sessions/{session_id}/clear")
    assert response.status_code == 200
    assert response.json()["status"] == "cleared"

    # Verify session state was reset
    assert _sessions[session_id]["turn_count"] == 0
    assert _sessions[session_id]["status"] == "active"


# ---------------------------------------------------------------------------
# /agents
# ---------------------------------------------------------------------------


def test_get_agents_runs_discovery_when_no_routing_table(client: TestClient) -> None:
    """/agents runs service discovery when no routing table is cached yet."""
    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_EMPTY_ROUTING_TABLE),
    ) as mock_discover:
        response = client.get("/sessions/test-session/agents")

    assert response.status_code == 200
    assert response.json() == {"agents": []}
    mock_discover.assert_awaited_once()


def test_get_agents_returns_agents_from_discovered_routing_table(
    client: TestClient,
) -> None:
    """/agents returns agent specs populated by on-demand discovery."""
    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_SAMPLE_ROUTING_TABLE),
    ):
        response = client.get("/sessions/test-session/agents")

    assert response.status_code == 200
    data = response.json()
    assert len(data["agents"]) == 2
    names = {a["name"] for a in data["agents"]}
    assert names == {"zen-architect", "modular-builder"}


def test_get_agents_returns_agents_from_cached_routing_table(
    client: TestClient,
) -> None:
    """/agents reads agent specs from the session's stored routing table (no re-discovery)."""
    session_id = "cached-agents-session"
    _sessions[session_id] = {
        "turn_count": 1,
        "status": "active",
        "routing_table": _SAMPLE_ROUTING_TABLE,
    }

    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_EMPTY_ROUTING_TABLE),
    ) as mock_discover:
        response = client.get(f"/sessions/{session_id}/agents")

    assert response.status_code == 200
    data = response.json()
    assert len(data["agents"]) == 2
    # Discovery should NOT have been called because we had a cached table.
    mock_discover.assert_not_awaited()


def test_get_agents_caches_routing_table_for_subsequent_calls(
    client: TestClient,
) -> None:
    """/agents stores the discovered routing table so repeat calls skip re-discovery."""
    session_id = "new-agents-session"

    with patch(
        "session_service.app.discover_services",
        new=AsyncMock(return_value=_SAMPLE_ROUTING_TABLE),
    ) as mock_discover:
        # First call — triggers discovery
        client.get(f"/sessions/{session_id}/agents")
        # Second call — should use cached routing table
        client.get(f"/sessions/{session_id}/agents")

    assert mock_discover.await_count == 1, (
        "Discovery should only run once; second call uses cache"
    )
