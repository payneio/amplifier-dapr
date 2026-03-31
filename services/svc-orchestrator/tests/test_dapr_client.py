"""Tests for DaprClient — Dapr HTTP API wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from svc_orchestrator.dapr_client import DaprClient


class TestDaprClientInvoke:
    """Tests for DaprClient.invoke() — service invocation via Dapr."""

    @pytest.mark.asyncio
    async def test_invoke_builds_correct_url(self) -> None:
        """invoke() POSTs to /v1.0/invoke/{app_id}/method/{method} with data."""
        client = DaprClient(dapr_url="http://localhost:3500")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"result": "ok"})

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "svc_orchestrator.dapr_client.httpx.AsyncClient", return_value=mock_http
        ):
            result = await client.invoke("my-app", "do-work", {"key": "val"})

        mock_http.post.assert_called_once()
        call_args = mock_http.post.call_args
        url = (
            call_args[0][0]
            if call_args[0]
            else call_args.kwargs.get(
                "url", call_args[1].get("url") if call_args[1] else None
            )
        )
        assert url == "http://localhost:3500/v1.0/invoke/my-app/method/do-work"
        assert result == {"result": "ok"}


class TestDaprClientInvokeGet:
    """Tests for DaprClient.invoke_get() — service invocation using GET."""

    @pytest.mark.asyncio
    async def test_invoke_get(self) -> None:
        """invoke_get() GETs /v1.0/invoke/{app_id}/method/{method} with params."""
        client = DaprClient(dapr_url="http://localhost:3500")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"status": "healthy"})

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "svc_orchestrator.dapr_client.httpx.AsyncClient", return_value=mock_http
        ):
            result = await client.invoke_get(
                "svc-health", "health", params={"check": "all"}
            )

        mock_http.get.assert_called_once()
        call_args = mock_http.get.call_args
        url = (
            call_args[0][0]
            if call_args[0]
            else call_args.kwargs.get(
                "url", call_args[1].get("url") if call_args[1] else None
            )
        )
        assert url == "http://localhost:3500/v1.0/invoke/svc-health/method/health"
        assert result == {"status": "healthy"}


class TestDaprClientPublish:
    """Tests for DaprClient.publish() — Dapr pub/sub publishing."""

    @pytest.mark.asyncio
    async def test_publish_builds_correct_url(self) -> None:
        """publish() POSTs to /v1.0/publish/{pubsub_name}/{topic} with data."""
        client = DaprClient(dapr_url="http://localhost:3500")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "svc_orchestrator.dapr_client.httpx.AsyncClient", return_value=mock_http
        ):
            result = await client.publish("pubsub", "events", {"event": "created"})

        mock_http.post.assert_called_once()
        call_args = mock_http.post.call_args
        url = (
            call_args[0][0]
            if call_args[0]
            else call_args.kwargs.get(
                "url", call_args[1].get("url") if call_args[1] else None
            )
        )
        assert url == "http://localhost:3500/v1.0/publish/pubsub/events"
        assert result is None  # publish returns None
