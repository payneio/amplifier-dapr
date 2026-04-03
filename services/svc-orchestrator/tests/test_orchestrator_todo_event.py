"""Tests for todo_update SSE event emission from execute_stream."""

from __future__ import annotations

import json
from typing import Any

import pytest

from amplifier_service_sdk.models import Message, RoutingTable
from svc_orchestrator.dapr_client import DaprClient
from svc_orchestrator.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dapr() -> DaprClient:
    """Return a DaprClient instance (HTTP calls will be mocked in each test)."""
    return DaprClient(dapr_url="http://localhost:3500")


def _routing_table_with_todo(
    provider_app_id: str = "svc-provider-mock",
    context: str = "svc-context",
) -> RoutingTable:
    return RoutingTable(
        providers={"mock": provider_app_id},
        tools={"todo": "svc-todo"},
        context=context,
        hooks={},
    )


# ---------------------------------------------------------------------------
# TestTodoUpdateEvent
# ---------------------------------------------------------------------------


class TestTodoUpdateEvent:
    """stream.todo_update event is emitted after the 'todo' tool returns todos."""

    @pytest.mark.asyncio
    async def test_todo_tool_result_emits_todo_update(self) -> None:
        """Mock provider calls 'todo' tool; verify stream.todo_update emitted with todos."""
        dapr = _make_dapr()
        provider_call_count = 0

        todos = [
            {
                "content": "Write tests",
                "status": "in_progress",
                "activeForm": "Writing tests",
            },
            {
                "content": "Implement feature",
                "status": "pending",
                "activeForm": "Implementing feature",
            },
        ]

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    # First call: return tool_call for 'todo'
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-todo-1",
                                "name": "todo",
                                "arguments": {
                                    "action": "create",
                                    "todos": todos,
                                },
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    # Second call: end_turn
                    return {
                        "content": "Done!",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-todo" and "tools/todo/execute" in method:
                # svc-todo returns {"success": True, "output": json_with_todos}
                # Return the todo payload directly so the top-level parsed dict
                # contains "todos" (the format execute_stream checks for).
                return {"todos": todos, "status": "created"}

            # context add messages
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            # Returns the same seed message on every call; intentionally
            # simplified — this test only checks event shape, not context growth.
            return {"messages": [{"role": "user", "content": "Plan my work"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="You are a helpful assistant.",
            messages=[Message(role="user", content="Plan my work")],
            config={"provider": "mock"},
            routing_table=_routing_table_with_todo(),
            session_id="session-todo-stream-1",
        ):
            events.append(event)

        # Extract stream.todo_update events
        todo_update_events = [e for e in events if e["event"] == "stream.todo_update"]

        assert len(todo_update_events) == 1, (
            f"Expected exactly 1 stream.todo_update event, got {len(todo_update_events)}. "
            f"All events: {[e['event'] for e in events]}"
        )

        event_data = json.loads(todo_update_events[0]["data"])
        assert "todos" in event_data, (
            f"Expected 'todos' key in stream.todo_update data, got: {event_data}"
        )
        assert "status" in event_data, (
            f"Expected 'status' key in stream.todo_update data, got: {event_data}"
        )
        assert event_data["todos"] == todos, (
            f"Expected todos to match, got: {event_data['todos']}"
        )
        assert event_data["status"] == "created", (
            f"Expected status='created', got: {event_data['status']}"
        )
