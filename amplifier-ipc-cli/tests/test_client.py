"""Tests for SessionClient and SSEEvent."""

from __future__ import annotations

import json

import httpx
import pytest

from amplifier_ipc_cli.client import SSEEvent, SessionClient


# ---------------------------------------------------------------------------
# SSEEvent tests
# ---------------------------------------------------------------------------


class TestSSEEvent:
    def test_from_lines_parses_event_and_data(self) -> None:
        """Parses both event type and JSON data fields from raw SSE text."""
        raw = 'event: tool_use\ndata: {"name": "bash"}'
        event = SSEEvent.from_lines(raw)
        assert event is not None
        assert event.event == "tool_use"
        assert event.data == {"name": "bash"}

    def test_from_lines_data_only(self) -> None:
        """When no event field, event type defaults to 'message'."""
        raw = 'data: {"message": "hello"}'
        event = SSEEvent.from_lines(raw)
        assert event is not None
        assert event.event == "message"
        assert event.data == {"message": "hello"}

    def test_from_lines_empty_returns_none(self) -> None:
        """Empty or whitespace-only input returns None."""
        assert SSEEvent.from_lines("") is None
        assert SSEEvent.from_lines("   ") is None
        assert SSEEvent.from_lines("\n\n") is None


# ---------------------------------------------------------------------------
# SessionClient tests
# ---------------------------------------------------------------------------


class TestSessionClient:
    def test_default_base_url(self) -> None:
        """SessionClient defaults to http://localhost:8080."""
        client = SessionClient()
        assert client.base_url == "http://localhost:8080"

    def test_custom_base_url(self) -> None:
        """SessionClient accepts a custom base_url."""
        client = SessionClient(base_url="http://myserver:9090")
        assert client.base_url == "http://myserver:9090"

    async def test_healthcheck(self) -> None:
        """healthcheck() performs GET /healthz and returns True on 200."""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, json={"status": "ok"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(base_url="http://localhost:8080", transport=transport) as http:
            client = SessionClient()
            client._http = http
            result = await client.healthcheck()

        assert result is True
        assert calls == ["http://localhost:8080/healthz"]

    async def test_send_turn_calls_session_service(self) -> None:
        """send_turn() performs POST /sessions/{id}/turn with prompt in body."""
        session_id = "test-session-123"
        expected_response = {"turn_id": "turn-1", "status": "completed"}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == f"/sessions/{session_id}/turn"
            body = json.loads(request.content)
            assert body["prompt"] == "Hello world"
            return httpx.Response(200, json=expected_response)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(base_url="http://localhost:8080", transport=transport) as http:
            client = SessionClient()
            client._http = http
            result = await client.send_turn(session_id, "Hello world")

        assert result == expected_response

    async def test_get_session_info(self) -> None:
        """get_session_info() performs GET /sessions/{id} and returns the response dict."""
        session_id = "test-session-456"
        expected_info = {"id": session_id, "status": "active"}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == f"/sessions/{session_id}"
            return httpx.Response(200, json=expected_info)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(base_url="http://localhost:8080", transport=transport) as http:
            client = SessionClient()
            client._http = http
            result = await client.get_session_info(session_id)

        assert result == expected_info
