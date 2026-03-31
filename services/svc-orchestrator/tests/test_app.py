"""Tests for the svc-orchestrator FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_orchestrator.app import create_orchestrator_app


class TestModuleLevelApp:
    """Tests for the module-level app object in svc_orchestrator.app."""

    def test_module_exposes_app(self) -> None:
        """svc_orchestrator.app must expose a module-level FastAPI 'app' object."""
        from svc_orchestrator import app as app_module  # noqa: PLC0415

        assert hasattr(app_module, "app"), "app.py must define a module-level 'app'"
        assert isinstance(app_module.app, FastAPI)


class TestOrchestratorApp:
    """Tests for the orchestrator FastAPI application endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the orchestrator app."""
        app = create_orchestrator_app(dapr_url="http://localhost:3500")
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe(self, client: TestClient) -> None:
        """GET /describe returns svc-orchestrator name."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-orchestrator"

    def test_execute_endpoint_exists(self, client: TestClient) -> None:
        """POST /orchestrator/execute returns 422 on empty body (endpoint exists)."""
        response = client.post("/orchestrator/execute", json={})
        assert response.status_code == 422

    def test_delegate_endpoint_exists(self, client: TestClient) -> None:
        """POST /orchestrator/delegate returns 422 on empty body (endpoint exists)."""
        response = client.post("/orchestrator/delegate", json={})
        assert response.status_code == 422

    def test_describe_includes_delegation_capability(self, client: TestClient) -> None:
        """GET /describe includes delegation in the tools list."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [tool["name"] for tool in data.get("tools", [])]
        assert "delegation" in tool_names
