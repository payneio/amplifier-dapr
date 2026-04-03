"""Tests for fine-grained content block SSE events from execute_stream.

Covers the structured content_block:start/delta/end and thinking:delta/final
event sequence that replaces the old stream.thinking event.
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


def _routing_table() -> RoutingTable:
    return RoutingTable(
        providers={"mock": "svc-provider-mock"},
        tools={},
        context="svc-context",
        hooks={},
    )


def _make_mocks(content: Any) -> tuple[Any, Any, Any]:
    """Return mock invoke, invoke_get, publish functions for the given content."""

    async def mock_invoke(
        app_id: str, method: str, data: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        if app_id == "svc-provider-mock" and "complete" in method:
            return {
                "content": content,
                "tool_calls": None,
                "usage": None,
                "stop_reason": "end_turn",
            }
        return {"ok": True}

    async def mock_invoke_get(
        app_id: str, method: str, **kwargs: Any
    ) -> dict[str, Any]:
        return {"messages": [{"role": "user", "content": "Hello"}]}

    async def mock_publish(*args: Any, **kwargs: Any) -> None:
        pass

    return mock_invoke, mock_invoke_get, mock_publish


async def _collect_events(content: Any) -> list[dict[str, Any]]:
    """Run execute_stream with the given content and collect all events."""
    dapr = _make_dapr()
    mock_invoke, mock_invoke_get, mock_publish = _make_mocks(content)
    dapr.invoke = mock_invoke  # type: ignore[method-assign]
    dapr.invoke_get = mock_invoke_get  # type: ignore[method-assign]
    dapr.publish = mock_publish  # type: ignore[method-assign]

    orch = Orchestrator(dapr=dapr)
    events: list[dict[str, Any]] = []
    async for event in orch.execute_stream(
        system_prompt="You are helpful.",
        messages=[Message(role="user", content="Hello")],
        config={"provider": "mock"},
        routing_table=_routing_table(),
        session_id="test-session",
    ):
        events.append(event)
    return events


def _event_names(events: list[dict[str, Any]]) -> list[str]:
    return [e["event"] for e in events]


def _events_by_type(
    events: list[dict[str, Any]], event_type: str
) -> list[dict[str, Any]]:
    return [e for e in events if e["event"] == event_type]


def _data(event: dict[str, Any]) -> dict[str, Any]:
    return json.loads(event["data"])


# ---------------------------------------------------------------------------
# TestContentBlockEvents
# ---------------------------------------------------------------------------


class TestContentBlockEvents:
    """Fine-grained content block and thinking events from execute_stream."""

    @pytest.mark.asyncio
    async def test_thinking_block_emits_full_sequence(self) -> None:
        """Provider returns thinking + text blocks; verify full event sequence."""
        thinking_text = "Let me reason through this carefully."
        answer_text = "The answer is 42."
        content = [
            {"type": "thinking", "thinking": thinking_text},
            {"type": "text", "text": answer_text},
        ]
        events = await _collect_events(content)
        names = _event_names(events)

        # --- Required events present ---
        assert "stream.content_block:start" in names, (
            f"Expected stream.content_block:start in {names}"
        )
        assert "stream.thinking:delta" in names, (
            f"Expected stream.thinking:delta in {names}"
        )
        assert "stream.thinking:final" in names, (
            f"Expected stream.thinking:final in {names}"
        )
        assert "stream.content_block:end" in names, (
            f"Expected stream.content_block:end in {names}"
        )
        assert "stream.content_block:delta" in names, (
            f"Expected stream.content_block:delta for text in {names}"
        )

        # --- Old stream.thinking must NOT be present ---
        assert "stream.thinking" not in names, (
            f"Expected stream.thinking to be absent, but found it in {names}"
        )

        # --- thinking:delta data has {delta: text} ---
        thinking_delta_events = _events_by_type(events, "stream.thinking:delta")
        assert len(thinking_delta_events) >= 1
        td_data = _data(thinking_delta_events[0])
        assert "delta" in td_data, (
            f"Expected 'delta' key in thinking:delta data: {td_data}"
        )
        assert td_data["delta"] == thinking_text, (
            f"Expected delta={thinking_text!r}, got {td_data['delta']!r}"
        )

        # --- thinking:final data has {text: text} ---
        thinking_final_events = _events_by_type(events, "stream.thinking:final")
        assert len(thinking_final_events) >= 1
        tf_data = _data(thinking_final_events[0])
        assert "text" in tf_data, (
            f"Expected 'text' key in thinking:final data: {tf_data}"
        )
        assert tf_data["text"] == thinking_text, (
            f"Expected text={thinking_text!r}, got {tf_data['text']!r}"
        )

        # --- content_block:delta has {delta, block_type: "text"} ---
        delta_events = _events_by_type(events, "stream.content_block:delta")
        assert len(delta_events) >= 1
        delta_data = _data(delta_events[0])
        assert delta_data.get("block_type") == "text", (
            f"Expected block_type='text' in content_block:delta data: {delta_data}"
        )
        assert "delta" in delta_data, (
            f"Expected 'delta' key in content_block:delta data: {delta_data}"
        )
        assert delta_data["delta"] == answer_text, (
            f"Expected delta={answer_text!r}, got {delta_data['delta']!r}"
        )

    @pytest.mark.asyncio
    async def test_text_only_response_emits_content_block_delta(self) -> None:
        """Provider returns text-only block; verify content_block start/delta/end."""
        text_content = "Just a plain text response."
        content = [{"type": "text", "text": text_content}]
        events = await _collect_events(content)
        names = _event_names(events)

        assert "stream.content_block:start" in names, (
            f"Expected stream.content_block:start in {names}"
        )
        assert "stream.content_block:delta" in names, (
            f"Expected stream.content_block:delta in {names}"
        )
        assert "stream.content_block:end" in names, (
            f"Expected stream.content_block:end in {names}"
        )

        # Verify the delta carries the text
        delta_events = _events_by_type(events, "stream.content_block:delta")
        delta_data = _data(delta_events[0])
        assert delta_data.get("delta") == text_content, (
            f"Expected delta={text_content!r}, got {delta_data.get('delta')!r}"
        )

    @pytest.mark.asyncio
    async def test_plain_string_content_no_content_block_events(self) -> None:
        """Provider returns plain string content; verify no content_block events."""
        content = "Plain string response"
        events = await _collect_events(content)
        names = _event_names(events)

        assert "stream.content_block:start" not in names, (
            f"Expected NO stream.content_block:start for plain string, got {names}"
        )
        assert "stream.content_block:delta" not in names, (
            f"Expected NO stream.content_block:delta for plain string, got {names}"
        )
