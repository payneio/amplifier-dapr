"""Tests for SessionClient and SSEEvent."""

from __future__ import annotations

import json

import httpx

from amplifier_cli.client import SSEEvent, SessionClient


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
        """SessionClient defaults to http://localhost:8090."""
        client = SessionClient()
        assert client.base_url == "http://localhost:8090"

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
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.healthcheck()

        assert result is True
        assert calls == ["http://localhost:8090/healthz"]

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
            base_url="http://localhost:8090", transport=transport
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
            base_url="http://localhost:8090", transport=transport
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
            base_url="http://localhost:8090", transport=transport
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
            base_url="http://localhost:8090", transport=transport
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
            base_url="http://localhost:8090", transport=transport
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
            base_url="http://localhost:8090", transport=transport
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
            base_url="http://localhost:8090", transport=transport
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
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.clear_session(session_id)

        assert result is True

    async def test_get_agents_returns_list(self) -> None:
        """get_agents() performs GET /sessions/{id}/agents and returns the agents list."""
        session_id = "test-session-agents"
        agents_list = [
            {"name": "zen-architect", "description": "Designs module specs"},
            {"name": "modular-builder", "description": "Builds modules"},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == f"/sessions/{session_id}/agents"
            return httpx.Response(200, json={"agents": agents_list})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.get_agents(session_id)

        assert result == agents_list

    async def test_get_agents_returns_empty_list(self) -> None:
        """get_agents() returns an empty list when server returns {agents: []}."""
        session_id = "test-session-no-agents"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"agents": []})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.get_agents(session_id)

        assert result == []


class TestCreateSession:
    """Tests for create_session() method."""

    async def test_create_session_calls_correct_endpoint(self) -> None:
        """create_session() performs POST /sessions/create with agent_ref and machine_config, returns session info."""
        expected_response = {
            "session_id": "ses-abc123",
            "machine_instance_id": "mi-xyz456",
        }
        machine_config = {
            "type": "ssh",
            "host": "myserver.example.com",
            "working_dir": "/home/user",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/sessions/create"
            body = json.loads(request.content)
            assert body["agent_ref"] == "custom-agent"
            assert body["machine_config"] == machine_config
            return httpx.Response(200, json=expected_response)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.create_session(
                agent_ref="custom-agent", machine_config=machine_config
            )

        assert result == expected_response
        assert result["session_id"] == "ses-abc123"
        assert result["machine_instance_id"] == "mi-xyz456"

    async def test_create_session_without_machine_config(self) -> None:
        """create_session() sends null machine_config when not provided, response has null machine_instance_id."""
        expected_response = {
            "session_id": "ses-def456",
            "machine_instance_id": None,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/sessions/create"
            body = json.loads(request.content)
            assert body["agent_ref"] == "default"
            assert body["machine_config"] is None
            return httpx.Response(200, json=expected_response)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.create_session()

        assert result == expected_response
        assert result["machine_instance_id"] is None

    async def test_create_session_default_machine_config(self) -> None:
        """create_session() with use_default_machine=True sends {type: ssh, host: localhost, working_dir: cwd}."""
        expected_response = {
            "session_id": "ses-ghi789",
            "machine_instance_id": "mi-local001",
        }
        captured_body: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/sessions/create"
            captured_body.update(json.loads(request.content))
            return httpx.Response(200, json=expected_response)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            result = await client.create_session(use_default_machine=True)

        assert result == expected_response
        assert captured_body["agent_ref"] == "default"
        machine_config = captured_body["machine_config"]
        assert machine_config is not None
        assert machine_config["type"] == "ssh"
        assert machine_config["host"] == "host.docker.internal"
        assert "working_dir" in machine_config
