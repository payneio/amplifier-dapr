"""State module for session-service — manages transcript persistence."""

from __future__ import annotations

from amplifier_service_sdk.models import Message


def save_transcript(session_id: str, messages: list[Message]) -> None:
    """Save transcript for a session (no-op stub).

    Args:
        session_id: The session identifier.
        messages: The list of messages to persist.
    """


def load_transcript(session_id: str) -> list[Message]:
    """Load transcript for a session.

    Args:
        session_id: The session identifier.

    Returns:
        Empty list (stub — no persistence backend).
    """
    return []
