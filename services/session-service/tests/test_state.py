"""Tests for session_service.state module — Dapr state store integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from amplifier_service_sdk.models import Message

from session_service.state import load_transcript, save_transcript


class TestSaveTranscript:
    """Tests for save_transcript function."""

    async def test_saves_with_correct_key_and_value_count(self) -> None:
        """save_transcript uses key '{session_id}-transcript' and serializes all messages."""
        messages = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi"),
        ]
        with patch(
            "session_service.state._save_state", new_callable=AsyncMock
        ) as mock_save:
            await save_transcript("sess-123", messages, "http://localhost:3500")
            mock_save.assert_called_once()
            args = mock_save.call_args[0]
            key = args[1]
            value = args[2]
            assert key == "sess-123-transcript"
            assert len(value) == 2  # value count matches messages count


class TestLoadTranscript:
    """Tests for load_transcript function."""

    async def test_empty_for_missing(self) -> None:
        """load_transcript returns empty list when state store returns None."""
        with patch(
            "session_service.state._get_state",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await load_transcript("missing-session", "http://localhost:3500")
            assert result == []

    async def test_returns_messages(self) -> None:
        """load_transcript deserializes stored dicts back to Message objects."""
        stored = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        with patch(
            "session_service.state._get_state",
            new_callable=AsyncMock,
            return_value=stored,
        ):
            result = await load_transcript("sess-456", "http://localhost:3500")
            assert len(result) == 2
            assert all(isinstance(m, Message) for m in result)
            assert result[0].role == "user"
            assert result[0].content == "hello"
            assert result[1].role == "assistant"
            assert result[1].content == "world"
