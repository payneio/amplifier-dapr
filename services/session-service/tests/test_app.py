"""Tests for the session-service FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from session_service.app import create_session_app


class TestModuleLevelApp:
    """Tests for the module-level app object in session_service.app."""

    def test_module_exposes_app(self) -> None:
        """session_service.app must expose a module-level FastAPI 'app' object."""
        from session_service import app as app_module  # noqa: PLC0415

        assert hasattr(app_module, "app"), "app.py must define a module-level 'app'"
        assert isinstance(app_module.app, FastAPI)


class TestSessionServiceApp:
    """Tests for the session-service FastAPI application endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the session-service app."""
        app = create_session_app(dapr_url="http://localhost:3500")
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe(self, client: TestClient) -> None:
        """GET /describe returns session-service name."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "session-service"

    def test_turn_endpoint_exists(self, client: TestClient) -> None:
        """POST /sessions/{id}/turn returns 422 on empty body (endpoint exists)."""
        response = client.post("/sessions/test-session-id/turn", json={})
        assert response.status_code == 422

    def test_session_info_returns_404(self, client: TestClient) -> None:
        """GET /sessions/nonexistent returns 404 for unknown session."""
        response = client.get("/sessions/nonexistent-session-id")
        assert response.status_code == 404
