"""Tests for streaming-aware delegate tool dispatch in execute_stream."""

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


def _routing_table_with_delegate(
    provider_app_id: str = "svc-provider-mock",
    context: str = "svc-context",
) -> RoutingTable:
    return RoutingTable(
        providers={"mock": provider_app_id},
        tools={"delegate": "svc-delegation"},
        context=context,
        hooks={},
    )


# ---------------------------------------------------------------------------
# TestDelegateToolStreamingEvents
# ---------------------------------------------------------------------------


class TestDelegateToolStreamingEvents:
    """stream.delegate:agent_spawned and stream.delegate:agent_completed events."""

    @pytest.mark.asyncio
    async def test_delegate_tool_emits_spawned_event(self) -> None:
        """Mock provider calls 'delegate' tool; verify delegate streaming events emitted."""
        dapr = _make_dapr()
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    # First call: return delegate tool call
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-delegate-1",
                                "name": "delegate",
                                "arguments": {
                                    "instruction": "Write tests",
                                    "agent": "test-writer",
                                },
                            }
                        ],
                        "usage": None,
                        "stop_reason": "tool_use",
                    }
                else:
                    # Second call: end_turn
                    return {
                        "content": "Delegation complete!",
                        "tool_calls": None,
                        "usage": None,
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-delegation" and "tools/delegate/execute" in method:
                # svc-delegation returns success with output
                return {
                    "success": True,
                    "output": {
                        "result": "Tests written successfully",
                        "session_id": "child-session-123",
                    },
                }

            # context add messages
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Delegate some work"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="You are a helpful assistant.",
            messages=[Message(role="user", content="Delegate some work")],
            config={"provider": "mock"},
            routing_table=_routing_table_with_delegate(),
            session_id="session-delegate-stream-1",
        ):
            events.append(event)

        event_names = [e["event"] for e in events]

        # Verify standard streaming events are present
        assert "stream.tool_call_start" in event_names, (
            f"Expected stream.tool_call_start in events. Got: {event_names}"
        )
        assert "stream.tool_result" in event_names, (
            f"Expected stream.tool_result in events. Got: {event_names}"
        )
        assert "stream.complete" in event_names, (
            f"Expected stream.complete in events. Got: {event_names}"
        )

        # Verify delegate-specific spawned event is emitted before dispatch
        assert "stream.delegate:agent_spawned" in event_names, (
            f"Expected stream.delegate:agent_spawned in events. Got: {event_names}"
        )

        # Verify delegate-specific completed event is emitted after dispatch
        assert "stream.delegate:agent_completed" in event_names, (
            f"Expected stream.delegate:agent_completed in events. Got: {event_names}"
        )

        # Verify spawned event data
        spawned_events = [
            e for e in events if e["event"] == "stream.delegate:agent_spawned"
        ]
        assert len(spawned_events) == 1, (
            f"Expected exactly 1 stream.delegate:agent_spawned event, got {len(spawned_events)}"
        )
        spawned_data = json.loads(spawned_events[0]["data"])
        assert spawned_data["agent"] == "test-writer", (
            f"Expected agent='test-writer' in spawned event, got: {spawned_data}"
        )
        assert spawned_data["instruction"] == "Write tests", (
            f"Expected instruction='Write tests' in spawned event, got: {spawned_data}"
        )
        assert spawned_data["depth"] == 1, (
            f"Expected depth=1 in spawned event, got: {spawned_data}"
        )

        # Verify completed event data
        completed_events = [
            e for e in events if e["event"] == "stream.delegate:agent_completed"
        ]
        assert len(completed_events) == 1, (
            f"Expected exactly 1 stream.delegate:agent_completed event, got {len(completed_events)}"
        )
        completed_data = json.loads(completed_events[0]["data"])
        assert completed_data["agent"] == "test-writer", (
            f"Expected agent='test-writer' in completed event, got: {completed_data}"
        )
        assert completed_data["success"] is True, (
            f"Expected success=True in completed event, got: {completed_data}"
        )
        assert "result_preview" in completed_data, (
            f"Expected result_preview in completed event, got: {completed_data}"
        )

        # Verify ordering: spawned before tool_call_start, completed after tool_result
        spawned_idx = event_names.index("stream.delegate:agent_spawned")
        tool_call_start_idx = event_names.index("stream.tool_call_start")
        tool_result_idx = event_names.index("stream.tool_result")
        completed_idx = event_names.index("stream.delegate:agent_completed")

        assert spawned_idx < tool_call_start_idx, (
            f"stream.delegate:agent_spawned (idx {spawned_idx}) should appear before "
            f"stream.tool_call_start (idx {tool_call_start_idx})"
        )
        assert completed_idx > tool_result_idx, (
            f"stream.delegate:agent_completed (idx {completed_idx}) should appear after "
            f"stream.tool_result (idx {tool_result_idx})"
        )
