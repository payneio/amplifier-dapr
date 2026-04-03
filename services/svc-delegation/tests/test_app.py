"""Tests for svc-delegation FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_delegation.app import create_delegation_app
from svc_delegation.tool import DelegateTool


class TestDefaultURLs:
    """Tests for the default service URLs used when no URLs are injected."""

    def test_default_session_service_url_uses_correct_dapr_app_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default session_service_base_url must use Dapr app-id 'session-service', not 'svc-session'."""
        captured: dict[str, str] = {}

        original_init = DelegateTool.__init__

        def capturing_init(
            self: DelegateTool,
            orchestrator_base_url: str,
            session_service_base_url: str | None = None,
            parent_session_id: str = "",
            delegation_depth: int = 0,
        ) -> None:
            captured["session_url"] = session_service_base_url or ""
            original_init(
                self,
                orchestrator_base_url,
                session_service_base_url,
                parent_session_id,
                delegation_depth,
            )

        monkeypatch.setattr(DelegateTool, "__init__", capturing_init)
        create_delegation_app()

        assert "session-service" in captured["session_url"], (
            f"Expected Dapr app-id 'session-service' in URL, got: {captured['session_url']}"
        )
        assert "svc-session" not in captured["session_url"], (
            f"Stale Dapr app-id 'svc-session' found in URL: {captured['session_url']}"
        )


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
        """Create a TestClient for the delegation app with test URLs."""
        app = create_delegation_app(
            orchestrator_base_url="http://test-orchestrator:8080",
            session_service_base_url="http://test-session-service:8080",
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

    def test_describe_tool_has_instruction_in_required(
        self, client: TestClient
    ) -> None:
        """GET /describe returns delegate tool schema with 'instruction' in required."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        delegate_tool = next(t for t in data["tools"] if t["name"] == "delegate")
        assert "instruction" in delegate_tool["input_schema"]["required"]
