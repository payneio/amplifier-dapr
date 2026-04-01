"""Tests for SessionClient and SSEEvent."""

from __future__ import annotations

import json

import httpx

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
        async with httpx.AsyncClient(
            base_url="http://localhost:8080", transport=transport
        ) as http:
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
        async with httpx.AsyncClient(
            base_url="http://localhost:8080", transport=transport
        ) as http:
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
        async with httpx.AsyncClient(
            base_url="http://localhost:8080", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.get_session_info(session_id)

        assert result == expected_info

    async def test_stream_turn_yields_sse_events(self) -> None:
        """stream_turn() yields SSEEvents parsed from the SSE response body."""
        session_id = "test-session-789"
        sse_body = 'event: delta\ndata: {"text": "hello"}\n\nevent: done\ndata: {"text": ""}\n\n'

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == f"/sessions/{session_id}/turn/stream"
            return httpx.Response(200, text=sse_body)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8080", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            events = [e async for e in client.stream_turn(session_id, "hi")]

        assert len(events) == 2
        assert events[0].event == "delta"
        assert events[0].data == {"text": "hello"}
        assert events[1].event == "done"
        assert events[1].data == {"text": ""}

    async def test_close_is_safe_when_no_http_created(self) -> None:
        """close() does not raise when _http has never been created."""
        client = SessionClient()
        await client.close()  # should not raise

    async def test_async_context_manager(self) -> None:
        """SessionClient supports 'async with' and closes cleanly on exit."""
        async with SessionClient() as client:
            assert isinstance(client, SessionClient)

    async def test_healthcheck_returns_false_on_network_error(self) -> None:
        """healthcheck() returns False instead of raising on connection error."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8080", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.healthcheck()

        assert result is False


class TestSSEEventEdgeCases:
    def test_from_lines_malformed_json_returns_raw_string(self) -> None:
        """from_lines() with malformed JSON returns SSEEvent with the raw data string."""
        raw = "event: delta\ndata: {not valid json}"
        event = SSEEvent.from_lines(raw)
        assert event is not None
        assert event.event == "delta"
        assert event.data == "{not valid json}"


class TestSessionClientMetadataMethods:
    """Tests for get_tools, get_modes, and clear_session methods."""

    async def test_get_tools_returns_list(self) -> None:
        """get_tools() performs GET /sessions/{id}/tools and returns the tools list."""
        session_id = "test-session-tools"
        tools_list = [{"name": "bash"}, {"name": "read_file"}]

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == f"/sessions/{session_id}/tools"
            return httpx.Response(200, json={"tools": tools_list})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8080", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.get_tools(session_id)

        assert result == tools_list

    async def test_get_tools_returns_empty_list(self) -> None:
        """get_tools() returns an empty list when server returns {tools: []}."""
        session_id = "test-session-no-tools"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"tools": []})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8080", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.get_tools(session_id)

        assert result == []

    async def test_get_modes_returns_list(self) -> None:
        """get_modes() performs GET /sessions/{id}/modes and returns the modes list."""
        session_id = "test-session-modes"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == f"/sessions/{session_id}/modes"
            return httpx.Response(200, json={"modes": []})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8080", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.get_modes(session_id)

        assert result == []

    async def test_clear_session_posts_to_correct_endpoint(self) -> None:
        """clear_session() performs POST /sessions/{id}/clear and returns True."""
        session_id = "test-session-clear"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == f"/sessions/{session_id}/clear"
            return httpx.Response(200, json={"status": "cleared"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8080", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.clear_session(session_id)

        assert result is True
