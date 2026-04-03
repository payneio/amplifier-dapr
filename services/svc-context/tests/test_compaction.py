"""Comprehensive test suite for the 7-level compaction engine with paired tool-call/result removal."""

from __future__ import annotations

from amplifier_service_sdk.models import Message, ToolCall

from svc_context.context_manager import (
    SimpleContextManager,
    _compact,
    format_compaction_notice,
)

_SESSION = "test-compaction-session"
_LONG_CONTENT = "x" * 200  # 50 tokens each — deliberately above compaction threshold


def _make_tool_pair(call_id: str, content: str = "result") -> tuple[Message, Message]:
    """Create an assistant-with-tool-call + tool-result Message pair using ToolCall model."""
    tool_call = ToolCall(id=call_id, name="test_tool", arguments={})
    assistant = Message(role="assistant", content=None, tool_calls=[tool_call])
    result = Message(role="tool", content=content, tool_call_id=call_id)
    return assistant, result


class TestPairedToolCallRemoval:
    """Tests verifying that tool-call/result pairs are always removed together (Level 3)."""

    async def test_tool_call_and_result_removed_together(self) -> None:
        """Level 3 must remove both the assistant tool-call and its matching tool result together.

        'call-old' must never be in an orphaned state: either both the assistant message
        that contains the tool_call and the tool-result message with the matching
        tool_call_id are present, or both are absent.
        """
        cm = SimpleContextManager()
        cm.max_tokens = 200
        cm.compact_threshold = 0.50
        cm.target_usage = 0.20

        # System message (stays always)
        await cm.add_message(_SESSION, Message(role="system", content="System."))

        # Old tool pair with 400-char content — large enough to push over threshold
        old_asst, old_result = _make_tool_pair("call-old", content="x" * 400)
        await cm.add_message(_SESSION, old_asst)
        await cm.add_message(_SESSION, old_result)

        # Recent user+assistant — will be in the protected tail
        await cm.add_message(_SESSION, Message(role="user", content="Recent user."))
        await cm.add_message(
            _SESSION, Message(role="assistant", content="Recent assistant.")
        )

        messages = await cm.get_messages(_SESSION)

        # Collect all tool_call IDs present in assistant tool_calls
        call_ids_in_calls: set[str] = set()
        for m in messages:
            if m.tool_calls:
                for tc in m.tool_calls:
                    call_ids_in_calls.add(tc.id)

        # Collect all tool_call_id references in tool-result messages
        call_ids_in_results: set[str] = {
            m.tool_call_id for m in messages if m.tool_call_id
        }

        # 'call-old' must NOT be orphaned: both present or both absent
        old_in_calls = "call-old" in call_ids_in_calls
        old_in_results = "call-old" in call_ids_in_results
        assert old_in_calls == old_in_results, (
            f"'call-old' is orphaned after compaction: "
            f"in_calls={old_in_calls}, in_results={old_in_results}"
        )

    async def test_no_orphaned_tool_results_after_compaction(self) -> None:
        """After compaction, every tool_call_id in a tool-result must match a tool_call
        present in some assistant message — no orphaned tool results allowed.
        """
        cm = SimpleContextManager()
        cm.max_tokens = 400
        cm.compact_threshold = 0.50
        cm.target_usage = 0.25

        # System message
        await cm.add_message(_SESSION, Message(role="system", content="System."))

        # 5 tool pairs, each tool result has 200-char content
        for i in range(5):
            asst, result = _make_tool_pair(f"call-{i}", content="t" * 200)
            await cm.add_message(_SESSION, asst)
            await cm.add_message(_SESSION, result)

        # Final user+assistant — these occupy the protected tail
        await cm.add_message(_SESSION, Message(role="user", content="Final user."))
        await cm.add_message(
            _SESSION, Message(role="assistant", content="Final assistant.")
        )

        messages = await cm.get_messages(_SESSION)

        # Build a set of all tool_call IDs referenced from assistant tool_calls
        call_ids_in_calls: set[str] = set()
        for m in messages:
            if m.tool_calls:
                for tc in m.tool_calls:
                    call_ids_in_calls.add(tc.id)

        # Every tool-result message must have a matching tool_call
        for m in messages:
            if m.tool_call_id:
                assert m.tool_call_id in call_ids_in_calls, (
                    f"Orphaned tool result detected: tool_call_id='{m.tool_call_id}' "
                    f"has no matching assistant tool_call in the compacted output"
                )


class TestCompactionLevels:
    """Tests for individual compaction level behaviours."""

    def test_level1_truncates_tool_results(self) -> None:
        """Direct _compact() call: Level 1 should truncate large tool results."""
        tool_call = ToolCall(id="call-1", name="test_tool", arguments={})
        messages = [
            Message(role="system", content="System"),
            Message(role="user", content="Hello"),
            Message(
                role="assistant",
                content="Using tool",
                tool_calls=[tool_call],
            ),
            Message(role="tool", content="x" * 10000, tool_call_id="call-1"),
            Message(role="user", content="Last user"),
            Message(role="assistant", content="Last assistant"),
        ]

        result, stats = _compact(
            messages,
            target_tokens=500,
            protected_recent=0.3,
            protected_tool_results=0,
            truncate_chars=100,
        )

        # At least one compaction level must have been applied
        assert len(stats["levels_applied"]) >= 1, (
            f"Expected at least one level applied, got {stats['levels_applied']}"
        )
        # Specifically, Level 1 must have run (truncating tool results)
        assert 1 in stats["levels_applied"], (
            f"Expected level 1 in levels_applied, got {stats['levels_applied']}"
        )

        # The tool result must still be present (not removed, just truncated at Level 1)
        tool_msgs = [m for m in result if m.role == "tool"]
        assert len(tool_msgs) > 0, (
            "Tool result message should still be present after Level 1 (truncation, not removal)"
        )

        # Content must have been truncated
        tool_content = str(tool_msgs[0].content)
        assert len(tool_content) < 10000, (
            "Tool result content length should be less than original 10000 chars"
        )
        assert "...[truncated]" in tool_content, (
            "Truncated content must end with the '...[truncated]' marker"
        )

    async def test_system_messages_never_compacted(self) -> None:
        """System messages must survive all compaction levels intact.

        Compaction-notice system messages are filtered out by checking for
        metadata source='context-compaction'.
        """
        cm = SimpleContextManager()
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.10  # very aggressive — drives through multiple levels

        sys_content = "You are a test assistant."
        await cm.add_message(_SESSION, Message(role="system", content=sys_content))

        # 6 alternating messages with 200-char content → 6 * 50 = 300 tokens (>> 50 threshold)
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(_SESSION, Message(role=role, content=_LONG_CONTENT))

        messages = await cm.get_messages(_SESSION)

        # Filter out compaction-notice system messages by their metadata source
        original_sys_msgs = [
            m
            for m in messages
            if m.role == "system"
            and not (m.metadata and m.metadata.get("source") == "context-compaction")
        ]

        assert len(original_sys_msgs) >= 1, (
            "At least one original (non-notice) system message must survive compaction"
        )
        assert any(m.content == sys_content for m in original_sys_msgs), (
            f"System message with content '{sys_content}' must survive all compaction levels"
        )

    async def test_last_turn_always_preserved(self) -> None:
        """The last two non-system messages (protected tail) must always be preserved
        through compaction regardless of budget pressure.
        """
        cm = SimpleContextManager()
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.05  # very low target drives many compaction levels

        # System message
        await cm.add_message(_SESSION, Message(role="system", content="S"))

        # 10 alternating messages with 200-char content — heavy traffic to compact
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(_SESSION, Message(role=role, content=_LONG_CONTENT))

        # Final identifiable messages — 8-char content = 2 tokens each
        # These land in the protected tail and must survive
        final_user_content = "FINAL_U_"  # 8 chars → 2 tokens
        final_asst_content = "FINAL_A_"  # 8 chars → 2 tokens
        await cm.add_message(_SESSION, Message(role="user", content=final_user_content))
        await cm.add_message(
            _SESSION, Message(role="assistant", content=final_asst_content)
        )

        messages = await cm.get_messages(_SESSION)

        # Check among non-system messages only
        non_system = [m for m in messages if m.role != "system"]
        non_system_contents = [str(m.content) for m in non_system]

        assert any(final_asst_content in c for c in non_system_contents), (
            f"Final assistant message ('{final_asst_content}') must be preserved after compaction"
        )
        assert any(final_user_content in c for c in non_system_contents), (
            f"Final user message ('{final_user_content}') must be preserved after compaction"
        )


class TestCompactionNotice:
    """Tests for the compaction notice message inserted after compaction."""

    def test_notice_contains_level_and_actions(self) -> None:
        """format_compaction_notice must produce a notice string that identifies the
        compaction level applied, the number of messages removed, and mentions truncation.
        """
        stats = {
            "levels_applied": [3],
            "original_count": 10,
            "final_count": 5,
            "original_tokens": 1000,
            "final_tokens": 400,
        }
        notice = format_compaction_notice(stats)
        removed = stats["original_count"] - stats["final_count"]  # 5

        assert "context-compaction" in notice, (
            "Notice must contain 'context-compaction' to identify the notice type"
        )
        assert "level 3" in notice, (
            "Notice must mention 'level 3' when levels_applied=[3]"
        )
        assert str(removed) in notice, (
            f"Notice must contain the removed-message count ({removed})"
        )
        assert "truncated" in notice, (
            "Notice must mention 'truncated' to inform about tool-result truncation"
        )

    async def test_compaction_notice_inserted_in_messages(self) -> None:
        """get_messages must insert a compaction-notice system message with
        metadata source='context-compaction' when compaction occurs.
        """
        cm = SimpleContextManager()
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.30

        await cm.add_message(_SESSION, Message(role="system", content="System."))

        # 6 alternating 200-char messages → 300 tokens >> 50 threshold
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(_SESSION, Message(role=role, content=_LONG_CONTENT))

        messages = await cm.get_messages(_SESSION)

        # Compaction notice must be present and tagged with the correct metadata
        compaction_notices = [
            m
            for m in messages
            if m.role == "system"
            and m.metadata is not None
            and m.metadata.get("source") == "context-compaction"
        ]
        assert len(compaction_notices) >= 1, (
            "A compaction-notice system message with metadata source='context-compaction' "
            "must be inserted when compaction occurs"
        )


class TestEphemeralCompaction:
    """Tests verifying that get_messages never mutates the stored message list."""

    async def test_get_messages_does_not_modify_stored(self) -> None:
        """get_messages must return a compacted copy without modifying the stored messages.

        The length of cm._sessions[session] must equal the number of messages added,
        even after a compacting get_messages call.
        """
        cm = SimpleContextManager()
        cm.max_tokens = 100
        cm.compact_threshold = 0.50
        cm.target_usage = 0.30

        # 6 alternating messages → 300 tokens >> threshold (50)
        for i in range(6):
            role = "user" if i % 2 == 0 else "assistant"
            await cm.add_message(_SESSION, Message(role=role, content=_LONG_CONTENT))

        original_count = len(cm._sessions[_SESSION])  # must be 6

        # This call should trigger compaction
        compacted = await cm.get_messages(_SESSION)

        # Returned list must be compacted (fewer messages than stored)
        assert len(compacted) < original_count, (
            f"Expected compacted output to have fewer messages than {original_count}, "
            f"got {len(compacted)}"
        )

        # Stored list must be completely unchanged
        assert len(cm._sessions[_SESSION]) == original_count, (
            f"Stored messages must not be modified by get_messages: "
            f"expected {original_count}, got {len(cm._sessions[_SESSION])}"
        )
