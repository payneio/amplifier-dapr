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


def test_get_tools_returns_specs_from_discovered_routing_table(client: TestClient) -> None:
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


def test_get_tools_caches_routing_table_for_subsequent_calls(client: TestClient) -> None:
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

    assert mock_discover.await_count == 1, "Discovery should only run once; second call uses cache"


# ---------------------------------------------------------------------------
# /modes
# ---------------------------------------------------------------------------


def test_get_modes_returns_data_from_svc_modes(client: TestClient) -> None:
    """/modes returns mode data by invoking svc-modes via Dapr."""
    svc_modes_response = {
        "success": True,
        "output": {
            "modes": [
                {"name": "plan", "description": "Think and discuss", "shortcut": None},
                {"name": "review", "description": "Code review mode", "shortcut": None},
            ]
        },
    }

    import httpx
    from unittest.mock import MagicMock

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = svc_modes_response

    mock_post = AsyncMock(return_value=mock_response)

    with patch("session_service.app.httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.post = mock_post
        mock_client_cls.return_value = mock_http

        response = client.get("/sessions/test-session/modes")

    assert response.status_code == 200
    data = response.json()
    assert len(data["modes"]) == 2
    assert data["modes"][0]["name"] == "plan"
    assert data["modes"][1]["name"] == "review"


def test_get_modes_falls_back_to_empty_when_svc_modes_unavailable(client: TestClient) -> None:
    """/modes falls back to {modes: []} when svc-modes cannot be reached."""
    import httpx

    with patch("session_service.app.httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client_cls.return_value = mock_http

        response = client.get("/sessions/test-session/modes")

    assert response.status_code == 200
    assert response.json() == {"modes": []}


def test_get_modes_falls_back_when_svc_modes_returns_error(client: TestClient) -> None:
    """/modes falls back to {modes: []} when svc-modes returns a non-2xx status."""
    import httpx
    from unittest.mock import MagicMock

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )

    with patch("session_service.app.httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_http

        response = client.get("/sessions/test-session/modes")

    assert response.status_code == 200
    assert response.json() == {"modes": []}


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
