"""Integration test — full delegation event sequence end-to-end.

Verifies the complete event sequence for a delegation:
spawned → child events → completed, with accumulated token usage.
"""

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
# TestFullDelegationEventSequence
# ---------------------------------------------------------------------------


class TestFullDelegationEventSequence:
    """End-to-end verification of the complete delegation event sequence."""

    @pytest.mark.asyncio
    async def test_full_delegation_event_order(self) -> None:
        """Full delegation event sequence: spawned → child events → completed.

        Mock provider:
        - First call: delegate tool_calls (instruction: "Write unit tests",
          agent: "test-writer") + usage {input: 50, output: 20}
        - Second call: end_turn content + usage {input: 100, output: 30}

        svc-delegation returns {success: True, output: json({result, session_id})}.

        Verifies:
        - All expected events are present: tool_call_start, tool_call,
          delegate:agent_spawned, tool_result, delegate:agent_completed, complete
        - Correct ordering: agent_spawned index < agent_completed index
        - Correct delegate:agent_spawned payload (agent, instruction)
        - Accumulated usage in stream.complete: input=150 (50+100), output=50 (20+30)
        """
        dapr = _make_dapr()
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count

            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    # First call: return delegate tool call with usage
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-delegate-seq-1",
                                "name": "delegate",
                                "arguments": {
                                    "instruction": "Write unit tests",
                                    "agent": "test-writer",
                                },
                            }
                        ],
                        "usage": {"input_tokens": 50, "output_tokens": 20},
                        "stop_reason": "tool_use",
                    }
                else:
                    # Second call: end_turn with usage
                    return {
                        "content": "Delegation complete. Tests were written.",
                        "tool_calls": None,
                        "usage": {"input_tokens": 100, "output_tokens": 30},
                        "stop_reason": "end_turn",
                    }

            if app_id == "svc-delegation" and "tools/delegate/execute" in method:
                # svc-delegation returns success with JSON-encoded output
                return {
                    "success": True,
                    "output": json.dumps(
                        {
                            "result": "Unit tests written successfully",
                            "session_id": "child-session-delegate-seq-1",
                        }
                    ),
                }

            # context add messages
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Write unit tests"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="You are a helpful assistant.",
            messages=[Message(role="user", content="Write unit tests")],
            config={"provider": "mock"},
            routing_table=_routing_table_with_delegate(),
            session_id="session-delegation-seq-1",
        ):
            events.append(event)

        event_names = [e["event"] for e in events]

        # ------------------------------------------------------------------
        # Verify all expected events are present
        # ------------------------------------------------------------------
        assert "stream.tool_call_start" in event_names, (
            f"Expected stream.tool_call_start in events. Got: {event_names}"
        )
        assert "stream.tool_call" in event_names, (
            f"Expected stream.tool_call in events. Got: {event_names}"
        )
        assert "stream.delegate:agent_spawned" in event_names, (
            f"Expected stream.delegate:agent_spawned in events. Got: {event_names}"
        )
        assert "stream.tool_result" in event_names, (
            f"Expected stream.tool_result in events. Got: {event_names}"
        )
        assert "stream.delegate:agent_completed" in event_names, (
            f"Expected stream.delegate:agent_completed in events. Got: {event_names}"
        )
        assert "stream.complete" in event_names, (
            f"Expected stream.complete in events. Got: {event_names}"
        )

        # ------------------------------------------------------------------
        # Verify ordering: agent_spawned before agent_completed
        # ------------------------------------------------------------------
        spawned_idx = event_names.index("stream.delegate:agent_spawned")
        completed_idx = event_names.index("stream.delegate:agent_completed")
        assert spawned_idx < completed_idx, (
            f"stream.delegate:agent_spawned (idx {spawned_idx}) should appear before "
            f"stream.delegate:agent_completed (idx {completed_idx})"
        )

        # ------------------------------------------------------------------
        # Verify delegate:agent_spawned payload
        # ------------------------------------------------------------------
        spawned_events = [
            e for e in events if e["event"] == "stream.delegate:agent_spawned"
        ]
        assert len(spawned_events) == 1, (
            f"Expected exactly 1 stream.delegate:agent_spawned event, "
            f"got {len(spawned_events)}"
        )
        spawned_data = json.loads(spawned_events[0]["data"])
        assert spawned_data["agent"] == "test-writer", (
            f"Expected agent='test-writer' in spawned event, got: {spawned_data}"
        )
        assert spawned_data["instruction"] == "Write unit tests", (
            f"Expected instruction='Write unit tests' in spawned event, "
            f"got: {spawned_data}"
        )

        # ------------------------------------------------------------------
        # Verify stream.complete includes accumulated usage: 50+100=150, 20+30=50
        # ------------------------------------------------------------------
        complete_events = [e for e in events if e["event"] == "stream.complete"]
        assert len(complete_events) == 1, (
            f"Expected exactly 1 stream.complete event, got {len(complete_events)}"
        )
        complete_data = json.loads(complete_events[0]["data"])
        assert "usage" in complete_data, (
            f"Expected 'usage' key in stream.complete data, got: {complete_data}"
        )
        assert complete_data["usage"]["input_tokens"] == 150, (
            f"Expected accumulated input_tokens=150 (50+100), "
            f"got: {complete_data['usage']['input_tokens']}"
        )
        assert complete_data["usage"]["output_tokens"] == 50, (
            f"Expected accumulated output_tokens=50 (20+30), "
            f"got: {complete_data['usage']['output_tokens']}"
        )
