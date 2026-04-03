"""Tests for session-keyed SimpleContextManager isolation and scoping."""

from __future__ import annotations

from amplifier_service_sdk.models import Message

from svc_context.context_manager import SimpleContextManager


class TestSessionContext:
    """Tests verifying that SimpleContextManager isolates state by session_id."""

    # -----------------------------------------------------------------------
    # Test 1: sessions are isolated from each other
    # -----------------------------------------------------------------------

    async def test_different_sessions_are_isolated(self) -> None:
        """Messages added to different sessions must not bleed into each other."""
        cm = SimpleContextManager()

        await cm.add_message("session_a", Message(role="user", content="message for a"))
        await cm.add_message("session_b", Message(role="user", content="message for b"))

        messages_a = await cm.get_messages("session_a")
        messages_b = await cm.get_messages("session_b")

        assert len(messages_a) == 1, "session_a should have exactly 1 message"
        assert len(messages_b) == 1, "session_b should have exactly 1 message"
        assert messages_a[0].content == "message for a"
        assert messages_b[0].content == "message for b"

    # -----------------------------------------------------------------------
    # Test 2: clear() only affects the target session
    # -----------------------------------------------------------------------

    async def test_clear_only_affects_target_session(self) -> None:
        """clear(session_id) must empty only the target session, leaving others intact."""
        cm = SimpleContextManager()

        await cm.add_message("session_a", Message(role="user", content="keep me"))
        await cm.add_message("session_b", Message(role="user", content="clear me"))

        await cm.clear("session_b")

        messages_a = await cm.get_messages("session_a")
        messages_b = await cm.get_messages("session_b")

        assert len(messages_a) == 1, (
            "session_a should be untouched after clearing session_b"
        )
        assert messages_a[0].content == "keep me"
        assert len(messages_b) == 0, "session_b should be empty after clear"

    # -----------------------------------------------------------------------
    # Test 3: set_messages() is scoped to its session
    # -----------------------------------------------------------------------

    async def test_set_messages_is_session_scoped(self) -> None:
        """set_messages(session_id, ...) must only replace the target session's messages."""
        cm = SimpleContextManager()

        await cm.add_message("session_a", Message(role="user", content="original"))
        await cm.add_message("session_b", Message(role="user", content="untouched"))

        new_messages = [Message(role="user", content="replacement")]
        await cm.set_messages("session_a", new_messages)

        messages_a = await cm.get_messages("session_a")
        messages_b = await cm.get_messages("session_b")

        assert len(messages_a) == 1
        assert messages_a[0].content == "replacement", (
            "session_a should contain the replacement message"
        )
        assert len(messages_b) == 1
        assert messages_b[0].content == "untouched", (
            "session_b must not be affected by set_messages on session_a"
        )

    # -----------------------------------------------------------------------
    # Test 4: unknown session returns empty list
    # -----------------------------------------------------------------------

    async def test_empty_session_returns_empty_list(self) -> None:
        """get_messages for a session with no messages must return an empty list."""
        cm = SimpleContextManager()

        messages = await cm.get_messages("nonexistent_session")

        assert messages == [], (
            "An unknown session should return an empty list, not raise an error"
        )
