"""SimpleContextManager — in-memory message storage with ephemeral progressive compaction."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from amplifier_service_sdk.models import Message


def _estimate_tokens(message: Message) -> int:
    """Estimate token count for a message using chars / 4 heuristic."""
    content = message.content
    if content is None:
        char_count = 0
    elif isinstance(content, str):
        char_count = len(content)
    elif isinstance(content, list):
        # List content — count chars from each text item
        char_count = sum(
            len(item.get("text", "")) if isinstance(item, dict) else len(str(item))
            for item in content
        )
    else:
        char_count = len(str(content))
    return max(1, char_count // 4)


def _total_tokens(messages: list[Message]) -> int:
    """Sum token estimates for all messages."""
    return sum(_estimate_tokens(m) for m in messages)


def _truncate_content(message: Message, max_chars: int) -> Message:
    """Return a copy of message with content truncated to max_chars."""
    msg = message.model_copy(deep=True)
    if isinstance(msg.content, str) and len(msg.content) > max_chars:
        msg.content = msg.content[:max_chars] + "...[truncated]"
    return msg


def _is_tool_result(message: Message) -> bool:
    """Return True if the message is a tool result (role=tool or has tool_call_id)."""
    return message.role == "tool" or message.tool_call_id is not None


def _is_system(message: Message) -> bool:
    """Return True if the message is a system message."""
    return message.role == "system"


def _compact(
    messages: list[Message],
    target_tokens: int,
    protected_recent: float,
    protected_tool_results: int,
    truncate_chars: int,
) -> list[Message]:
    """Apply progressive compaction levels until target_tokens is reached or all levels exhausted.

    System messages are NEVER compacted.
    Messages list is not modified in-place — a working copy is used.
    """
    working = list(messages)

    # ------------------------------------------------------------------ #
    # Helper: check if we've hit the target                               #
    # ------------------------------------------------------------------ #

    def under_target() -> bool:
        return _total_tokens(working) <= target_tokens

    if under_target():
        return working

    # ------------------------------------------------------------------ #
    # Level 1 & 2: truncate tool results in 25% batches                  #
    # ------------------------------------------------------------------ #
    tool_result_indices = [
        i for i, m in enumerate(working) if _is_tool_result(m) and not _is_system(m)
    ]

    # Protect the most recent N tool results from Level 1/2 truncation
    protected_tr = (
        set(tool_result_indices[-protected_tool_results:])
        if protected_tool_results > 0
        else set()
    )
    truncatable = [i for i in tool_result_indices if i not in protected_tr]

    # Level 1 — truncate oldest 25% of truncatable tool results
    level1_count = max(1, len(truncatable) // 4)
    for idx in truncatable[:level1_count]:
        working[idx] = _truncate_content(working[idx], truncate_chars)

    if under_target():
        return working

    # Level 2 — truncate next 25% of truncatable (indices 25–50%)
    level2_start = level1_count
    level2_end = level2_start + max(1, len(truncatable) // 4)
    for idx in truncatable[level2_start:level2_end]:
        working[idx] = _truncate_content(working[idx], truncate_chars)

    if under_target():
        return working

    # ------------------------------------------------------------------ #
    # Level 3: remove oldest messages, protecting recent %               #
    # ------------------------------------------------------------------ #
    non_system_count = sum(1 for m in working if not _is_system(m))
    keep_recent_count = max(1, int(non_system_count * protected_recent))

    # Identify non-system messages oldest-first; keep the last keep_recent_count
    non_system_indices = [i for i, m in enumerate(working) if not _is_system(m)]
    removable_indices = set(non_system_indices[:-keep_recent_count])

    # Remove oldest (preserve order by rebuilding list)
    working = [m for i, m in enumerate(working) if i not in removable_indices]

    if under_target():
        return working

    # ------------------------------------------------------------------ #
    # Level 4: truncate all remaining non-system messages                #
    # ------------------------------------------------------------------ #
    working = [
        _truncate_content(m, truncate_chars) if not _is_system(m) else m
        for m in working
    ]

    if under_target():
        return working

    # ------------------------------------------------------------------ #
    # Level 5: keep last 4 non-system messages + all system messages     #
    # ------------------------------------------------------------------ #
    # Design note: system messages are placed first regardless of where  #
    # they originally appeared in the conversation.  This is intentional #
    # — most providers treat system messages as preamble, and at this    #
    # last-resort level preserving positional order matters less than    #
    # ensuring the model still sees its instructions.                    #
    system_msgs = [m for m in working if _is_system(m)]
    non_system_msgs = [m for m in working if not _is_system(m)]
    last_four = non_system_msgs[-4:]
    working = system_msgs + last_four

    return working


class SimpleContextManager:
    """In-memory context manager with ephemeral progressive compaction.

    self.messages is NEVER modified by compaction — get_messages returns
    a compacted copy only.
    """

    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.max_tokens: int = 200_000
        self.compact_threshold: float = 0.85
        self.target_usage: float = 0.60
        self.protected_recent: float = 0.30
        self.protected_tool_results: int = 5
        self.truncate_chars: int = 8_000

    # ------------------------------------------------------------------ #
    # Mutation methods                                                    #
    # ------------------------------------------------------------------ #

    async def add_message(self, message: Message) -> None:
        """Append a message to the store, stamping a timestamp into metadata."""
        msg = message.model_copy(deep=True)
        if msg.metadata is None:
            msg.metadata = {}
        msg.metadata["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
        self.messages.append(msg)

    async def set_messages(self, messages: list[Message]) -> None:
        """Replace the stored message list with the provided messages."""
        self.messages = [m.model_copy(deep=True) for m in messages]

    async def clear(self) -> None:
        """Empty the stored message list."""
        self.messages = []

    # ------------------------------------------------------------------ #
    # Query (ephemeral compaction)                                        #
    # ------------------------------------------------------------------ #

    async def get_messages(
        self,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> list[Message]:
        """Return a (possibly compacted) copy of the message list.

        Compaction is ephemeral: self.messages is never modified.

        Budget = context_window - max_output_tokens if both provided,
                 else self.max_tokens.
        """
        # Determine budget
        if context_window is not None:
            budget = context_window - (max_output_tokens or 0)
        else:
            budget = self.max_tokens

        # Work on a deep copy so self.messages is never mutated
        snapshot: list[Message] = copy.deepcopy(self.messages)

        current_tokens = _total_tokens(snapshot)
        threshold = int(budget * self.compact_threshold)

        if current_tokens <= threshold:
            # No compaction needed — return copy as-is
            return snapshot

        target_tokens = int(budget * self.target_usage)

        return _compact(
            snapshot,
            target_tokens=target_tokens,
            protected_recent=self.protected_recent,
            protected_tool_results=self.protected_tool_results,
            truncate_chars=self.truncate_chars,
        )
