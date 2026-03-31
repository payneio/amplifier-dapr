"""State module for session-service — manages transcript persistence via Dapr."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from amplifier_service_sdk.models import Message

_STATE_STORE_NAME = "statestore"
_logger = logging.getLogger(__name__)


async def _save_state(dapr_url: str, key: str, value: Any) -> None:
    """Save a key-value pair to the Dapr state store (bulk-save format).

    Uses the Dapr bulk-save endpoint ``POST /v1.0/state/{store}`` which
    accepts an array of ``{key, value}`` objects.  The per-key path suffix
    is intentionally omitted so the payload format matches the endpoint.

    Args:
        dapr_url: Base URL of the Dapr HTTP sidecar.
        key: State key.
        value: Value to store (must be JSON-serializable).
    """
    url = f"{dapr_url}/v1.0/state/{_STATE_STORE_NAME}"
    payload = [{"key": key, "value": value}]
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


async def _get_state(dapr_url: str, key: str) -> Any | None:
    """Get a value from the Dapr state store.

    Args:
        dapr_url: Base URL of the Dapr HTTP sidecar.
        key: State key to retrieve.

    Returns:
        The stored value, or None if not found (204 or empty response).
    """
    url = f"{dapr_url}/v1.0/state/{_STATE_STORE_NAME}/{key}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()


async def save_transcript(
    session_id: str, messages: list[Message], dapr_url: str
) -> None:
    """Save transcript for a session to the Dapr state store.

    Serializes messages via model_dump() and stores them under the key
    '{session_id}-transcript'. Logs errors without raising.

    Args:
        session_id: The session identifier.
        messages: The list of messages to persist.
        dapr_url: Base URL of the Dapr HTTP sidecar.
    """
    key = f"{session_id}-transcript"
    value = [m.model_dump() for m in messages]
    try:
        await _save_state(dapr_url, key, value)
    except Exception:
        _logger.exception("Failed to save transcript for session %s", session_id)


async def load_transcript(session_id: str, dapr_url: str) -> list[Message]:
    """Load transcript for a session from the Dapr state store.

    Deserializes stored data via Message.model_validate. Returns an empty
    list if the session is missing or an error occurs.

    Args:
        session_id: The session identifier.
        dapr_url: Base URL of the Dapr HTTP sidecar.

    Returns:
        List of Message objects, or empty list on missing/error.
    """
    key = f"{session_id}-transcript"
    try:
        data = await _get_state(dapr_url, key)
        if data is None:
            return []
        return [Message.model_validate(m) for m in data]
    except Exception:
        _logger.exception("Failed to load transcript for session %s", session_id)
        return []
