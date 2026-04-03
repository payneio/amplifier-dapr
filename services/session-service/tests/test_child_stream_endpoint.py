"""Tests for the streaming child turn endpoint in session-service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from session_service.app import create_session_app


class TestChildStreamEndpoint:
    """Tests for the POST /sessions/{id}/turn/stream child endpoint."""

    def test_endpoint_registered(self) -> None:
        """POST /sessions/{id}/turn/stream returns non-404 (endpoint is registered)."""
        app = create_session_app(dapr_url="http://localhost:3500")
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/sessions/test-child-123/turn/stream",
            json={"prompt": "hello from child"},
        )
        assert response.status_code != 404


class TestChildStreamEndpointQuality:
    """Tests for edge cases and behavioral invariants of the child stream endpoint."""

    @pytest.fixture
    def app_client(self) -> TestClient:
        """Create a TestClient with server exceptions suppressed."""
        app = create_session_app(dapr_url="http://localhost:3500")
        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture
    def mock_prepare_payload(self):
        """Patch _prepare_turn_payload to avoid real service discovery calls."""
        with patch(
            "session_service.app._prepare_turn_payload",
            new_callable=AsyncMock,
            return_value=(
                {"_tool_specs": [], "_modes": [], "_agents": []},
                "system prompt",
                "mock",
                "svc-orchestrator",
            ),
        ) as m:
            yield m

    def _make_stream_client_mock(self, sse_lines: list[str]) -> MagicMock:
        """Build an httpx AsyncClient mock that streams the given SSE lines.

        Mirrors the async context-manager protocol used in the production code:
        ``async with httpx.AsyncClient() as client:``
            ``async with client.stream(...) as response:``
                ``async for line in response.aiter_lines():``
        """

        async def _aiter_lines():
            for line in sse_lines:
                yield line

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = lambda: _aiter_lines()

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream.return_value = mock_stream_ctx

        return mock_client

    def test_error_path_yields_sse_error_event(self, app_client: TestClient) -> None:
        """Exception during turn setup surfaces as an SSE error event, not a 500."""
        with patch(
            "session_service.app._prepare_turn_payload",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network unavailable"),
        ):
            response = app_client.post(
                "/sessions/err-test-123/turn/stream",
                json={"prompt": "trigger error"},
            )
        assert response.status_code != 404
        assert "error" in response.text
        assert "network unavailable" in response.text

    def test_no_transcript_save_on_child_turn(
        self, app_client: TestClient, mock_prepare_payload: AsyncMock
    ) -> None:
        """Child stream endpoint must not call save_transcript (sessions are ephemeral)."""
        sse_lines = ["event: complete", 'data: {"result": "done"}', ""]
        stream_mock = self._make_stream_client_mock(sse_lines)

        with (
            patch("session_service.app.httpx.AsyncClient", return_value=stream_mock),
            patch(
                "session_service.app.save_transcript", new_callable=AsyncMock
            ) as mock_save,
        ):
            app_client.post(
                "/sessions/child-no-save-123/turn/stream",
                json={"prompt": "do something"},
            )

        mock_save.assert_not_called()

    def test_partial_event_flushed_at_stream_end(
        self, app_client: TestClient, mock_prepare_payload: AsyncMock
    ) -> None:
        """Partial SSE event is emitted even if the stream ends without a trailing blank line."""
        # No trailing blank line — without the defensive flush this event is silently dropped
        sse_lines = ["event: complete", 'data: {"result": "done"}']
        stream_mock = self._make_stream_client_mock(sse_lines)

        with patch("session_service.app.httpx.AsyncClient", return_value=stream_mock):
            response = app_client.post(
                "/sessions/partial-flush-123/turn/stream",
                json={"prompt": "flush me"},
            )

        assert "complete" in response.text, (
            "Partial event at stream end must be flushed and present in response"
        )
        assert "done" in response.text
