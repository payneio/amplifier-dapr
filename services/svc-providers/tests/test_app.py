"""Tests for svc-providers FastAPI application endpoints and module exposure."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_providers.app import create_providers_app


class TestModuleLevelApp:
    """Tests for the module-level app object in svc_providers.app."""

    def test_module_exposes_app(self) -> None:
        """svc_providers.app must expose a module-level FastAPI 'app' object."""
        from svc_providers import app as app_module  # noqa: PLC0415

        assert hasattr(app_module, "app"), "app.py must define a module-level 'app'"
        assert isinstance(app_module.app, FastAPI)


class TestModuleExposure:
    """Tests that svc_providers __init__.py exposes key classes."""

    def test_init_exposes_anthropic_provider(self) -> None:
        """svc_providers.__init__ exposes AnthropicProvider."""
        from svc_providers import AnthropicProvider  # noqa: PLC0415

        assert AnthropicProvider is not None

    def test_init_exposes_base_provider(self) -> None:
        """svc_providers.__init__ exposes BaseProvider."""
        from svc_providers import BaseProvider  # noqa: PLC0415

        assert BaseProvider is not None


class TestProvidersApp:
    """Tests for the svc-providers FastAPI application endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the providers app."""
        app = create_providers_app()
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe_lists_anthropic_provider(self, client: TestClient) -> None:
        """GET /describe returns providers list containing {name: anthropic}."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        providers = data["providers"]
        assert isinstance(providers, list)
        assert len(providers) >= 1
        provider_names = [p["name"] for p in providers]
        assert "anthropic" in provider_names
