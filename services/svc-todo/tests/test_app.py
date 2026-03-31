"""Tests for the todo FastAPI application."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc_todo.app import create_todo_app


class TestModuleLevelApp:
    def test_module_exposes_app(self) -> None:
        """svc_todo.app must expose a module-level FastAPI 'app' object."""
        from svc_todo import app as app_module

        assert hasattr(app_module, "app")
        assert isinstance(app_module.app, FastAPI)


class TestTodoApp:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(create_todo_app())

    def test_healthz(self, client: TestClient) -> None:
        """GET /healthz returns healthy status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_describe_includes_todo(self, client: TestClient) -> None:
        """GET /describe returns tools containing 'todo'."""
        response = client.get("/describe")
        assert response.status_code == 200
        tool_names = [t["name"] for t in response.json()["tools"]]
        assert "todo" in tool_names

    def test_execute_create(self, client: TestClient) -> None:
        """POST /tools/todo/execute with create action works correctly."""
        payload = {
            "name": "todo",
            "input": {
                "action": "create",
                "todos": [
                    {
                        "content": "Write tests",
                        "activeForm": "Writing tests",
                        "status": "pending",
                    }
                ],
            },
        }
        response = client.post("/tools/todo/execute", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["output"]["status"] == "created"
        assert data["output"]["count"] == 1

    def test_execute_list(self, client: TestClient) -> None:
        """POST /tools/todo/execute with list action returns todos."""
        payload = {"name": "todo", "input": {"action": "list"}}
        response = client.post("/tools/todo/execute", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "todos" in data["output"]

    def test_execute_invalid_action(self, client: TestClient) -> None:
        """POST /tools/todo/execute with invalid action returns error."""
        payload = {"name": "todo", "input": {"action": "delete"}}
        response = client.post("/tools/todo/execute", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["error"] is not None
