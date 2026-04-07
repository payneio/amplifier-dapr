"""Tests for token usage accumulation and emission in execute_stream."""

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


def _simple_routing_table(
    provider_app_id: str = "svc-provider-mock",
    context: str = "svc-context",
) -> RoutingTable:
    return RoutingTable(
        providers={"mock": provider_app_id},
        tools={},
        context=context,
        hooks={},
    )


def _routing_table_with_tool(
    provider_app_id: str = "svc-provider-mock",
    context: str = "svc-context",
) -> RoutingTable:
    return RoutingTable(
        providers={"mock": provider_app_id},
        tools={"bash": "svc-machine"},
        context=context,
        hooks={},
    )


def _make_simple_mock(
    provider_app_id: str,
    provider_response: dict[str, Any],
) -> tuple[Any, Any, Any]:
    """Return mock_invoke, mock_invoke_get, mock_publish for a single-iteration run."""

    async def mock_invoke(
        app_id: str, method: str, data: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        if app_id == provider_app_id and "complete" in method:
            return provider_response
        return {"ok": True}

    async def mock_invoke_get(
        app_id: str, method: str, **kwargs: Any
    ) -> dict[str, Any]:
        return {"messages": [{"role": "user", "content": "Hello"}]}

    async def mock_publish(*args: Any, **kwargs: Any) -> None:
        pass

    return mock_invoke, mock_invoke_get, mock_publish


# ---------------------------------------------------------------------------
# TestCompleteEventUsage
# ---------------------------------------------------------------------------


class TestCompleteEventUsage:
    """stream.complete event carries usage when provider returns token counts."""

    @pytest.mark.asyncio
    async def test_complete_event_includes_usage(self) -> None:
        """Provider returns usage {input_tokens: 150, output_tokens: 42},
        verify stream.complete contains usage."""
        dapr = _make_dapr()
        provider_response = {
            "content": "Hello there!",
            "tool_calls": None,
            "usage": {"input_tokens": 150, "output_tokens": 42},
            "stop_reason": "end_turn",
        }
        mock_invoke, mock_invoke_get, mock_publish = _make_simple_mock(
            "svc-provider-mock", provider_response
        )
        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="You are a helpful assistant.",
            messages=[Message(role="user", content="Hello")],
            config={"provider": "mock"},
            routing_table=_simple_routing_table(),
            session_id="session-usage-1",
        ):
            events.append(event)

        complete_events = [e for e in events if e["event"] == "stream.complete"]
        assert len(complete_events) == 1, (
            f"Expected exactly 1 stream.complete event, got {len(complete_events)}"
        )

        event_data = json.loads(complete_events[0]["data"])
        assert "usage" in event_data, (
            f"Expected 'usage' key in stream.complete data, got: {event_data}"
        )
        assert event_data["usage"]["input_tokens"] == 150, (
            f"Expected input_tokens=150, got: {event_data['usage']['input_tokens']}"
        )
        assert event_data["usage"]["output_tokens"] == 42, (
            f"Expected output_tokens=42, got: {event_data['usage']['output_tokens']}"
        )

    @pytest.mark.asyncio
    async def test_complete_event_no_usage_when_none(self) -> None:
        """Provider returns usage=None, verify no 'usage' key in complete data."""
        dapr = _make_dapr()
        provider_response = {
            "content": "Hello there!",
            "tool_calls": None,
            "usage": None,
            "stop_reason": "end_turn",
        }
        mock_invoke, mock_invoke_get, mock_publish = _make_simple_mock(
            "svc-provider-mock", provider_response
        )
        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="You are a helpful assistant.",
            messages=[Message(role="user", content="Hello")],
            config={"provider": "mock"},
            routing_table=_simple_routing_table(),
            session_id="session-usage-2",
        ):
            events.append(event)

        complete_events = [e for e in events if e["event"] == "stream.complete"]
        assert len(complete_events) == 1

        event_data = json.loads(complete_events[0]["data"])
        assert "usage" not in event_data, (
            f"Expected no 'usage' key in stream.complete data, got: {event_data}"
        )

    @pytest.mark.asyncio
    async def test_usage_accumulates_across_iterations(self) -> None:
        """Two provider calls (tool loop): first returns {input: 100, output: 20},
        second returns {input: 200, output: 30}. Verify accumulated {input: 300, output: 50}."""
        dapr = _make_dapr()
        provider_call_count = 0

        async def mock_invoke(
            app_id: str, method: str, data: dict[str, Any], **kwargs: Any
        ) -> dict[str, Any]:
            nonlocal provider_call_count
            if app_id == "svc-provider-mock" and "complete" in method:
                provider_call_count += 1
                if provider_call_count == 1:
                    return {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-bash-1",
                                "name": "bash",
                                "arguments": {"command": "echo hello"},
                            }
                        ],
                        "usage": {"input_tokens": 100, "output_tokens": 20},
                        "stop_reason": "tool_use",
                    }
                else:
                    return {
                        "content": "Done!",
                        "tool_calls": None,
                        "usage": {"input_tokens": 200, "output_tokens": 30},
                        "stop_reason": "end_turn",
                    }
            if app_id == "svc-machine" and "tools/bash/execute" in method:
                return {"success": True, "output": "hello"}
            return {"ok": True}

        async def mock_invoke_get(
            app_id: str, method: str, **kwargs: Any
        ) -> dict[str, Any]:
            return {"messages": [{"role": "user", "content": "Run a command"}]}

        async def mock_publish(*args: Any, **kwargs: Any) -> None:
            pass

        dapr.invoke = mock_invoke  # type: ignore[method-assign]
        dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
        dapr.publish = mock_publish  # type: ignore[method-assign]

        orch = Orchestrator(dapr=dapr)
        events: list[dict[str, Any]] = []
        async for event in orch.execute_stream(
            system_prompt="You are a helpful assistant.",
            messages=[Message(role="user", content="Run a command")],
            config={"provider": "mock"},
            routing_table=_routing_table_with_tool(),
            session_id="session-usage-3",
        ):
            events.append(event)

        complete_events = [e for e in events if e["event"] == "stream.complete"]
        assert len(complete_events) == 1, (
            f"Expected exactly 1 stream.complete event, got {len(complete_events)}"
        )

        event_data = json.loads(complete_events[0]["data"])
        assert "usage" in event_data, (
            f"Expected 'usage' key in stream.complete data, got: {event_data}"
        )
        assert event_data["usage"]["input_tokens"] == 300, (
            f"Expected accumulated input_tokens=300, got: {event_data['usage']['input_tokens']}"
        )
        assert event_data["usage"]["output_tokens"] == 50, (
            f"Expected accumulated output_tokens=50, got: {event_data['usage']['output_tokens']}"
        )
