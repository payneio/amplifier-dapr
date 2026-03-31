"""Tests for the svc-mock-provider FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_mock_provider.app import create_mock_provider_app


class TestModuleLevelApp:
    """Tests for the module-level app object in svc_mock_provider.app."""

    def test_module_exposes_app(self) -> None:
        """svc_mock_provider.app must expose a module-level FastAPI 'app' object."""
        from svc_mock_provider import app as app_module  # noqa: PLC0415

        assert hasattr(app_module, "app"), "app.py must define a module-level 'app'"
        assert isinstance(app_module.app, FastAPI)


class TestMockProviderApp:
    """Tests for the mock provider FastAPI application endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the mock provider app."""
        app = create_mock_provider_app()
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe_lists_provider(self, client: TestClient) -> None:
        """GET /describe returns providers list containing {name: mock}."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        providers = data["providers"]
        assert isinstance(providers, list)
        assert len(providers) >= 1
        provider_names = [p["name"] for p in providers]
        assert "mock" in provider_names

    def test_complete_returns_text(self, client: TestClient) -> None:
        """POST /providers/mock/complete returns text response with end_turn for plain messages."""
        payload = {
            "messages": [{"role": "user", "content": "Hello, world"}],
        }
        response = client.post("/providers/mock/complete", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Mock response to: Hello, world"
        assert data["stop_reason"] == "end_turn"
        assert data["usage"] is not None
        assert data["usage"]["input_tokens"] > 0
        assert data["usage"]["output_tokens"] > 0

    def test_complete_returns_tool_call(self, client: TestClient) -> None:
        """POST /providers/mock/complete returns tool_calls with tool_use when message mentions tool name."""
        payload = {
            "messages": [{"role": "user", "content": "Please use search to find cats"}],
            "tools": [
                {
                    "name": "search",
                    "description": "Search for things",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                        },
                    },
                }
            ],
        }
        response = client.post("/providers/mock/complete", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["stop_reason"] == "tool_use"
        assert data["tool_calls"] is not None
        assert len(data["tool_calls"]) == 1
        tc = data["tool_calls"][0]
        assert tc["name"] == "search"
        assert data["usage"] is not None
