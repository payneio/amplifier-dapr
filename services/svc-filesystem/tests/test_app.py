"""Tests for the filesystem FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_filesystem.app import create_filesystem_app


class TestModuleLevelApp:
    """Tests for the module-level app object in svc_filesystem.app."""

    def test_module_exposes_app(self) -> None:
        """svc_filesystem.app must expose a module-level FastAPI 'app' object."""
        from svc_filesystem import app as app_module  # noqa: PLC0415

        assert hasattr(app_module, "app"), "app.py must define a module-level 'app'"
        assert isinstance(app_module.app, FastAPI)


class TestFilesystemApp:
    """Tests for the filesystem FastAPI application endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the filesystem app with a fake machine URL."""
        app = create_filesystem_app(machine_base_url="http://fake-machine:8080")
        return TestClient(app)

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns 200 with healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_describe_includes_all_tools(self, client: TestClient) -> None:
        """GET /describe returns tools list containing read_file, write_file, edit_file."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "edit_file" in tool_names
