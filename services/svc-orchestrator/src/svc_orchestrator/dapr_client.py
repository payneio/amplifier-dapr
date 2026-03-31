"""DaprClient — async HTTP wrapper for the Dapr v1.0 sidecar API."""

from __future__ import annotations

from typing import Any

import httpx


class DaprClient:
    """Async client for interacting with the Dapr sidecar HTTP API.

    Covers service invocation, pub/sub publishing, and state store operations.
    Uses a fresh httpx.AsyncClient per call (stateless, safe for concurrent use).
    """

    def __init__(self, dapr_url: str = "http://localhost:3500") -> None:
        """Initialise the Dapr client.

        Args:
            dapr_url: Base URL of the Dapr HTTP sidecar (no trailing slash).
        """
        self._base_url = dapr_url.rstrip("/")

    # ------------------------------------------------------------------
    # Service Invocation
    # ------------------------------------------------------------------

    async def invoke(
        self,
        app_id: str,
        method: str,
        data: dict[str, Any],
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Invoke a method on a remote Dapr application via POST.

        Args:
            app_id: Target application ID registered in Dapr.
            method: Method/endpoint name on the target app.
            data: JSON-serialisable payload to send.
            timeout: Request timeout in seconds.

        Returns:
            JSON response dict from the target service.
        """
        url = f"{self._base_url}/v1.0/invoke/{app_id}/method/{method}"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, timeout=timeout)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def invoke_get(
        self,
        app_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Invoke a method on a remote Dapr application via GET.

        Args:
            app_id: Target application ID registered in Dapr.
            method: Method/endpoint name on the target app.
            params: Optional query parameters.
            timeout: Request timeout in seconds.

        Returns:
            JSON response dict from the target service.
        """
        url = f"{self._base_url}/v1.0/invoke/{app_id}/method/{method}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Pub/Sub
    # ------------------------------------------------------------------

    async def publish(
        self,
        pubsub_name: str,
        topic: str,
        data: dict[str, Any],
    ) -> None:
        """Publish a message to a Dapr pub/sub topic.

        Args:
            pubsub_name: Name of the Dapr pub/sub component.
            topic: Topic to publish the message to.
            data: JSON-serialisable event payload.
        """
        url = f"{self._base_url}/v1.0/publish/{pubsub_name}/{topic}"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data)
            response.raise_for_status()

    # ------------------------------------------------------------------
    # State Store
    # ------------------------------------------------------------------

    async def get_state(
        self,
        store_name: str,
        key: str,
    ) -> dict[str, Any] | None:
        """Retrieve a value from the Dapr state store.

        Args:
            store_name: Name of the Dapr state store component.
            key: State key to retrieve.

        Returns:
            Parsed JSON dict if the key exists, or None on 204/empty response.
        """
        url = f"{self._base_url}/v1.0/state/{store_name}/{key}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            if response.status_code == 204 or not response.content:
                return None
            return response.json()  # type: ignore[no-any-return]

    async def save_state(
        self,
        store_name: str,
        key: str,
        value: Any,
    ) -> None:
        """Save a value to the Dapr state store.

        Args:
            store_name: Name of the Dapr state store component.
            key: State key to store the value under.
            value: JSON-serialisable value to persist.
        """
        url = f"{self._base_url}/v1.0/state/{store_name}"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=[{"key": key, "value": value}])
            response.raise_for_status()
