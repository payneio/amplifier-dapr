"""Tests for SimpleContextManager — in-memory storage and ephemeral progressive compaction."""

from __future__ import annotations

from amplifier_service_sdk.models import Message

from svc_context.context_manager import SimpleContextManager


class TestSimpleContextManager:
    """Tests for SimpleContextManager."""

    # -----------------------------------------------------------------------
    # Test 1: add_message and get_messages basic round-trip
    # -----------------------------------------------------------------------

    async def test_add_and_get_messages(self) -> None:
        """add_message stores messages; get_messages returns them in order."""
        cm = SimpleContextManager()

        user_msg = Message(role="user", content="Hello!")
        assistant_msg = Message(role="assistant", content="Hi there!")

        await cm.add_message(user_msg)
        await cm.add_message(assistant_msg)

        messages = await cm.get_messages()

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello!"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi there!"

    # -----------------------------------------------------------------------
    # Test 2: clear() empties the message list
    # -----------------------------------------------------------------------

    async def test_clear(self) -> None:
        """clear() must remove all stored messages."""
        cm = SimpleContextManager()

        await cm.add_message(Message(role="user", content="msg1"))
        await cm.add_message(Message(role="assistant", content="msg2"))

        assert len(await cm.get_messages()) == 2

        await cm.clear()

        assert len(await cm.get_messages()) == 0

    # -----------------------------------------------------------------------
    # Test 3: set_messages replaces the entire message list
    # -----------------------------------------------------------------------

    async def test_set_messages_bulk(self) -> None:
        """set_messages() replaces the list with the provided messages."""
        cm = SimpleContextManager()

        # Add some initial messages
        await cm.add_message(Message(role="user", content="old1"))
        await cm.add_message(Message(role="assistant", content="old2"))

        # Replace with new messages
        new_messages = [
            Message(role="user", content="new1"),
            Message(role="assistant", content="new2"),
            Message(role="user", content="new3"),
        ]
        await cm.set_messages(new_messages)

        messages = await cm.get_messages()
        assert len(messages) == 3
        assert messages[0].content == "new1"
        assert messages[1].content == "new2"
        assert messages[2].content == "new3"

    # -----------------------------------------------------------------------
    # Test 4: add_message adds a timestamp to metadata
    # -----------------------------------------------------------------------

    async def test_timestamps(self) -> None:
        """add_message adds a 'timestamp' key to the message metadata."""
        cm = SimpleContextManager()

        msg = Message(role="user", content="time check")
        await cm.add_message(msg)

        messages = await cm.get_messages()
        assert len(messages) == 1
        stored = messages[0]
        assert stored.metadata is not None, (
            "metadata must not be None after add_message"
        )
        assert "timestamp" in stored.metadata, "metadata must contain 'timestamp' key"

    # -----------------------------------------------------------------------
    # Test 5: add_message preserves existing metadata keys
    # -----------------------------------------------------------------------

    async def test_metadata_preservation(self) -> None:
        """add_message preserves pre-existing metadata keys when adding timestamp."""
        cm = SimpleContextManager()

        msg = Message(
            role="user",
            content="hello",
            metadata={"session_id": "abc123", "priority": 1},
        )
        await cm.add_message(msg)

        messages = await cm.get_messages()
        stored = messages[0]
        assert stored.metadata is not None
        assert stored.metadata.get("session_id") == "abc123"
        assert stored.metadata.get("priority") == 1
        assert "timestamp" in stored.metadata

    # -----------------------------------------------------------------------
    # Test 6: no compaction when under budget
    # -----------------------------------------------------------------------

    async def test_compaction_under_budget_noop(self) -> None:
        """get_messages returns all messages unchanged when well under budget."""
        cm = SimpleContextManager()

        # Short messages that comfortably fit in the budget
        await cm.add_message(Message(role="user", content="Hello"))
        await cm.add_message(Message(role="assistant", content="Hi there!"))

        messages = await cm.get_messages()
        assert len(messages) == 2

        # original list unchanged
        assert len(cm.messages) == 2

    # -----------------------------------------------------------------------
    # Test 7: compaction reduces message count when over budget
    # -----------------------------------------------------------------------

    async def test_compaction_triggers(self) -> None:
        """get_messages compacts messages when token usage exceeds compact_threshold."""
        cm = SimpleContextManager()
        # Tight budget: 100 tokens max, trigger at 50%
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.30

        long_content = "x" * 200  # 200 chars / 4 = 50 tokens each
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(Message(role=role, content=long_content))

        # Total = 6 * 50 = 300 tokens, well over 50% of 100
        messages = await cm.get_messages()

        # Compaction should reduce message count below 6
        assert len(messages) < 6, (
            f"Expected compaction to reduce messages, got {len(messages)}"
        )

    # -----------------------------------------------------------------------
    # Test 8: get_messages does not modify self.messages (ephemeral compaction)
    # -----------------------------------------------------------------------

    async def test_get_messages_does_not_modify_original(self) -> None:
        """Compaction in get_messages must NOT modify self.messages (ephemeral)."""
        cm = SimpleContextManager()
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.30

        long_content = "x" * 200  # 50 tokens each
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(Message(role=role, content=long_content))

        original_count = len(cm.messages)

        # This should trigger compaction
        compacted = await cm.get_messages()

        # Returned list was compacted
        assert len(compacted) < original_count, "Compacted result must be smaller"

        # But self.messages must be unchanged
        assert len(cm.messages) == original_count, (
            "self.messages must not be modified by get_messages compaction"
        )
