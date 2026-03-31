"""Tests for the search FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_search.app import create_search_app


class TestModuleLevelApp:
    """Tests for the module-level app object in svc_search.app."""

    def test_module_exposes_app(self) -> None:
        """svc_search.app must expose a module-level FastAPI 'app' object."""
        from svc_search import app as app_module  # noqa: PLC0415

        assert hasattr(app_module, "app"), "app.py must define a module-level 'app'"
        assert isinstance(app_module.app, FastAPI)


class TestSearchApp:
    """Tests for the search FastAPI application endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the search app with a fake machine URL."""
        app = create_search_app(machine_base_url="http://fake-machine:8080")
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe_includes_all_tools(self, client: TestClient) -> None:
        """GET /describe returns tools list containing grep and glob."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "grep" in tool_names
        assert "glob" in tool_names
