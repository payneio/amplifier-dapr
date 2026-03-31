"""Integration tests for the svc-modes FastAPI app."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_modes.app import create_mode_app


class TestModuleLevelApp:
    def test_module_exposes_app(self) -> None:
        import svc_modes.app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)


class TestModeApp:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(create_mode_app())

    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe_includes_mode(self, client: TestClient) -> None:
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "mode" in tool_names

    def test_execute_list(self, client: TestClient) -> None:
        response = client.post(
            "/tools/mode/execute",
            json={"name": "mode", "input": {"operation": "list"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "modes" in data["output"]

    def test_execute_current_no_mode(self, client: TestClient) -> None:
        response = client.post(
            "/tools/mode/execute",
            json={"name": "mode", "input": {"operation": "current"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["output"]["active_mode"] is None

    def test_execute_invalid_operation(self, client: TestClient) -> None:
        response = client.post(
            "/tools/mode/execute",
            json={"name": "mode", "input": {"operation": "unknown"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "invalid_operation"
