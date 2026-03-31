"""Tests for the web FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_web.app import create_web_app


class TestModuleLevelApp:
    """Tests for the module-level app object in svc_web.app."""

    def test_module_exposes_app(self) -> None:
        """svc_web.app must expose a module-level FastAPI 'app' object."""
        from svc_web import app as app_module  # noqa: PLC0415

        assert hasattr(app_module, "app"), "app.py must define a module-level 'app'"
        assert isinstance(app_module.app, FastAPI)


class TestWebApp:
    """Tests for the web FastAPI application endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the web app."""
        app = create_web_app()
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe_includes_all_tools(self, client: TestClient) -> None:
        """GET /describe returns tools list containing web_search and web_fetch."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "web_search" in tool_names
        assert "web_fetch" in tool_names
