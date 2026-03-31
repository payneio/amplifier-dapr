"""Tests for svc-delegation FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_delegation.app import create_delegation_app


class TestModuleLevelApp:
    """Tests for the module-level app object in svc_delegation.app."""

    def test_module_exposes_app(self) -> None:
        """svc_delegation.app must expose a module-level FastAPI 'app' object."""
        from svc_delegation import app as app_module  # noqa: PLC0415

        assert hasattr(app_module, "app"), "app.py must define a module-level 'app'"
        assert isinstance(app_module.app, FastAPI)


class TestDelegationApp:
    """Tests for the svc-delegation FastAPI application endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the delegation app with a test orchestrator URL."""
        app = create_delegation_app(
            orchestrator_base_url="http://test-orchestrator:8080"
        )
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe_includes_delegate_tool(self, client: TestClient) -> None:
        """GET /describe returns tools list containing the 'delegate' tool."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "delegate" in tool_names

    def test_describe_tool_has_prompt_in_required(self, client: TestClient) -> None:
        """GET /describe returns delegate tool schema with 'prompt' in required."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        delegate_tool = next(t for t in data["tools"] if t["name"] == "delegate")
        assert "prompt" in delegate_tool["input_schema"]["required"]
