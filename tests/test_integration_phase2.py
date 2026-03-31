"""End-to-end in-process integration tests for Phase 2 stack.

Tests the full flow: svc-context <-> svc-mock-provider without Docker.
All service interactions happen in-process via FastAPI TestClient.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from svc_context.app import create_context_app
from svc_mock_provider.app import create_mock_provider_app


# ---------------------------------------------------------------------------
# Module-level fixtures — shared by all test classes
# ---------------------------------------------------------------------------


@pytest.fixture
def context_client() -> TestClient:
    """Fresh svc-context TestClient with empty message store."""
    return TestClient(create_context_app())


@pytest.fixture
def provider_client() -> TestClient:
    """Fresh svc-mock-provider TestClient."""
    return TestClient(create_mock_provider_app())


# ---------------------------------------------------------------------------
# TestEndToEndFlow
# ---------------------------------------------------------------------------


class TestEndToEndFlow:
    """End-to-end tests verifying message flow through context and provider."""

    # ------------------------------------------------------------------
    # test_text_response_flow
    # ------------------------------------------------------------------

    def test_text_response_flow(
        self,
        context_client: TestClient,
        provider_client: TestClient,
    ) -> None:
        """Full text flow: system + user -> provider -> assistant stored in context."""

        # Step 1: Add system message to context
        resp = context_client.post(
            "/context/messages",
            json={"role": "system", "content": "You are a helpful assistant."},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Step 2: Add user message to context
        resp = context_client.post(
            "/context/messages",
            json={"role": "user", "content": "Hello, how are you?"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Step 3: Get messages, verify 2 messages stored
        resp = context_client.get("/context/messages")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 2

        # Step 4: Call provider /mock/complete with the messages, verify text + end_turn
        resp = provider_client.post(
            "/providers/mock/complete",
            json={"messages": messages},
        )
        assert resp.status_code == 200
        provider_data = resp.json()
        assert provider_data["stop_reason"] == "end_turn"
        assert isinstance(provider_data["content"], str)
        assert len(provider_data["content"]) > 0
        assert provider_data["tool_calls"] is None or provider_data["tool_calls"] == []

        # Step 5: Add assistant response to context
        assistant_content = provider_data["content"]
        resp = context_client.post(
            "/context/messages",
            json={"role": "assistant", "content": assistant_content},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Step 6 & 7: Verify 3 messages with correct roles
        resp = context_client.get("/context/messages")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 3
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user", "assistant"]

    # ------------------------------------------------------------------
    # test_tool_call_flow
    # ------------------------------------------------------------------

    def test_tool_call_flow(
        self,
        context_client: TestClient,
        provider_client: TestClient,
    ) -> None:
        """Tool call flow: provider returns tool_call, then text after tool result."""

        bash_tool_spec = {
            "name": "bash",
            "description": "Execute a bash command",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run"},
                },
                "required": ["command"],
            },
        }

        # Step 1: Add system and user messages mentioning bash
        resp = context_client.post(
            "/context/messages",
            json={"role": "system", "content": "You have access to bash."},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        resp = context_client.post(
            "/context/messages",
            json={"role": "user", "content": "Please run bash to check disk space."},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Step 2: Get messages from context
        resp = context_client.get("/context/messages")
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 2

        # Step 3: Call provider with bash tool spec, verify tool_calls returned
        resp = provider_client.post(
            "/providers/mock/complete",
            json={"messages": messages, "tools": [bash_tool_spec]},
        )
        assert resp.status_code == 200
        tool_call_data = resp.json()
        assert tool_call_data["tool_calls"] is not None
        assert len(tool_call_data["tool_calls"]) >= 1
        tool_call = tool_call_data["tool_calls"][0]
        assert tool_call["name"] == "bash"

        # Step 4: Add assistant message with tool_call to context
        resp = context_client.post(
            "/context/messages",
            json={
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call],
            },
        )
        assert resp.status_code == 200

        # Step 5: Add simulated tool result to context
        tool_result_content = "Filesystem: /dev/sda1  Size: 100G  Used: 50G"
        resp = context_client.post(
            "/context/messages",
            json={
                "role": "tool",
                "content": tool_result_content,
                "tool_call_id": tool_call["id"],
            },
        )
        assert resp.status_code == 200

        # Step 6: Call provider again with all messages, verify text + end_turn
        resp = context_client.get("/context/messages")
        assert resp.status_code == 200
        all_messages = resp.json()["messages"]

        resp = provider_client.post(
            "/providers/mock/complete",
            json={"messages": all_messages, "tools": [bash_tool_spec]},
        )
        assert resp.status_code == 200
        final_data = resp.json()
        assert final_data["stop_reason"] == "end_turn"
        assert isinstance(final_data["content"], str)
        # Content must echo back the actual tool result data
        assert tool_result_content in final_data["content"]

        # Step 7: Verify roles in context = [system, user, assistant, tool]
        resp = context_client.get("/context/messages")
        assert resp.status_code == 200
        messages_final = resp.json()["messages"]
        roles = [m["role"] for m in messages_final]
        assert roles == ["system", "user", "assistant", "tool"]


# ---------------------------------------------------------------------------
# TestServiceDescribeContracts
# ---------------------------------------------------------------------------


class TestServiceDescribeContracts:
    """Verify that svc-context and svc-mock-provider honour /describe and /healthz."""

    # ------------------------------------------------------------------
    # svc-context contracts
    # ------------------------------------------------------------------

    def test_context_healthz(self, context_client: TestClient) -> None:
        """svc-context GET /healthz returns 200 with status=healthy."""
        resp = context_client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service_name"] == "svc-context"

    def test_context_describe(self, context_client: TestClient) -> None:
        """svc-context GET /describe returns 200 with name=svc-context."""
        resp = context_client.get("/describe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "svc-context"
        assert "version" in data
        # Describe response must include the standard contract fields
        assert "tools" in data
        assert "hooks" in data
        assert "providers" in data
        assert "content_paths" in data

    # ------------------------------------------------------------------
    # svc-mock-provider contracts
    # ------------------------------------------------------------------

    def test_provider_healthz(self, provider_client: TestClient) -> None:
        """svc-mock-provider GET /healthz returns 200 with status=healthy."""
        resp = provider_client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service_name"] == "svc-mock-provider"

    def test_provider_describe(self, provider_client: TestClient) -> None:
        """svc-mock-provider GET /describe returns 200 with mock provider listed."""
        resp = provider_client.get("/describe")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "svc-mock-provider"
        assert "version" in data
        # Must expose the mock provider in providers list
        assert "providers" in data
        provider_names = [p["name"] for p in data["providers"]]
        assert "mock" in provider_names
        # Standard contract fields
        assert "tools" in data
        assert "hooks" in data
        assert "content_paths" in data
