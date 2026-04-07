"""Tests for agent_ref support in SessionClient and _build_turn_body."""

from __future__ import annotations

import json

import httpx

from amplifier_cli.client import SessionClient


class TestBuildTurnBodyAgentRef:
    """Unit-tests for the agent_ref field in _build_turn_body."""

    def _client(self) -> SessionClient:
        return SessionClient()

    def test_agent_ref_included_when_provided(self) -> None:
        """agent_ref is present in the body when explicitly supplied."""
        client = self._client()
        body = client._build_turn_body(
            "hello",
            workspace_content=None,
            provider_name=None,
            services=None,
            agent_ref="foundation",
        )
        assert body["agent_ref"] == "foundation"

    def test_agent_ref_absent_when_none(self) -> None:
        """agent_ref key is absent from the body when not supplied."""
        client = self._client()
        body = client._build_turn_body(
            "hello",
            workspace_content=None,
            provider_name=None,
            services=None,
            agent_ref=None,
        )
        assert "agent_ref" not in body

    def test_agent_ref_absent_by_default(self) -> None:
        """agent_ref defaults to None, so it is omitted from the request body."""
        client = self._client()
        body = client._build_turn_body(
            "hello",
            workspace_content=None,
            provider_name=None,
            services=None,
        )
        assert "agent_ref" not in body

    def test_all_fields_present_together(self) -> None:
        """All optional fields coexist correctly when all are supplied."""
        client = self._client()
        body = client._build_turn_body(
            "hi",
            workspace_content="<ctx/>",
            provider_name="anthropic",
            services=[{"id": "svc-machine"}],
            agent_ref="foundation",
        )
        assert body["prompt"] == "hi"
        assert body["workspace_content"] == "<ctx/>"
        assert body["provider_name"] == "anthropic"
        assert body["services"] == [{"id": "svc-machine"}]
        assert body["agent_ref"] == "foundation"


class TestStreamTurnAgentRef:
    """Integration-style tests verifying agent_ref reaches the HTTP request."""

    async def test_stream_turn_sends_agent_ref(self) -> None:
        """stream_turn() includes agent_ref in the POST body."""
        captured_body: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_body.update(json.loads(request.content))
            sse = "event: complete\ndata: {}\n\n"
            return httpx.Response(200, text=sse)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            events = [
                e
                async for e in client.stream_turn(
                    "session-1",
                    "hello",
                    agent_ref="foundation",
                )
            ]

        assert captured_body.get("agent_ref") == "foundation"
        assert len(events) == 1

    async def test_stream_turn_omits_agent_ref_when_none(self) -> None:
        """stream_turn() does not send agent_ref when it is None."""
        captured_body: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_body.update(json.loads(request.content))
            return httpx.Response(200, text="event: complete\ndata: {}\n\n")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            _ = [e async for e in client.stream_turn("session-2", "hi")]

        assert "agent_ref" not in captured_body

    async def test_send_turn_sends_agent_ref(self) -> None:
        """send_turn() includes agent_ref in the POST body."""
        captured_body: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_body.update(json.loads(request.content))
            return httpx.Response(200, json={"result": "ok"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url="http://localhost:8090", transport=transport
        ) as http:
            client = SessionClient()
            client._http = http
            await client.send_turn("session-3", "ping", agent_ref="foundation")

        assert captured_body.get("agent_ref") == "foundation"
