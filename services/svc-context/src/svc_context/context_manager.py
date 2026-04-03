"""SimpleContextManager — session-keyed in-memory storage with ephemeral progressive compaction."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from amplifier_service_sdk.models import Message


def _estimate_tokens(message: Message) -> int:
    """Estimate token count for a message using chars / 4 heuristic, minimum 1."""
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


def _has_tool_calls(message: Message) -> bool:
    """Return True if the message is an assistant message with tool_calls."""
    return message.role == "assistant" and bool(message.tool_calls)


def _find_tool_call_pair_indices(
    messages: list[Message], assistant_idx: int
) -> list[int]:
    """Find the indices of tool results that match the assistant message's tool calls.

    Returns a list of indices (into messages) for tool-result messages that correspond
    to the tool calls made by the assistant message at assistant_idx.
    """
    assistant_msg = messages[assistant_idx]
    if not _has_tool_calls(assistant_msg):
        return []

    # Collect the IDs that this assistant message is calling
    tool_call_ids: set[str] = set()
    for tc in assistant_msg.tool_calls or []:
        tool_call_ids.add(tc.id)

    if not tool_call_ids:
        return []

    # Scan forward for matching tool result messages
    result_indices: list[int] = []
    for i in range(assistant_idx + 1, len(messages)):
        msg = messages[i]
        if _is_tool_result(msg) and msg.tool_call_id in tool_call_ids:
            result_indices.append(i)

    return result_indices


def format_compaction_notice(stats: dict) -> str:
    """Generate a system-reminder XML block from compaction stats."""
    levels = stats.get("levels_applied", [])
    original_count = stats.get("original_count", 0)
    final_count = stats.get("final_count", 0)
    original_tokens = stats.get("original_tokens", 0)
    final_tokens = stats.get("final_tokens", 0)

    return (
        "<system-reminder>\n"
        "<compaction-notice>\n"
        f"  <levels_applied>{levels}</levels_applied>\n"
        f"  <original_messages>{original_count}</original_messages>\n"
        f"  <compacted_messages>{final_count}</compacted_messages>\n"
        f"  <original_tokens>{original_tokens}</original_tokens>\n"
        f"  <final_tokens>{final_tokens}</final_tokens>\n"
        "</compaction-notice>\n"
        "</system-reminder>"
    )


def _compact(
    messages: list[Message],
    target_tokens: int,
    protected_recent: float,
    protected_tool_results: int,
    truncate_chars: int,
) -> tuple[list[Message], dict]:
    """Apply 7 progressive compaction levels until target_tokens is reached.

    Returns (compacted_messages, stats_dict).

    Invariants:
    - System messages are NEVER compacted.
    - Last 2 non-system messages are always protected.
    - Tool-call/result pairs are always removed together (Level 3).
    - The stored messages list is never modified — callers pass a copy.
    """
    working = list(messages)
    stats: dict = {
        "levels_applied": [],
        "original_count": len(messages),
        "original_tokens": _total_tokens(messages),
    }

    def under_target() -> bool:
        return _total_tokens(working) <= target_tokens

    if under_target():
        stats["final_count"] = len(working)
        stats["final_tokens"] = _total_tokens(working)
        return working, stats

    # ------------------------------------------------------------------ #
    # Levels 1 & 2: truncate tool results in 25% batches                 #
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
    if truncatable:
        level1_count = max(1, len(truncatable) // 4)
        for idx in truncatable[:level1_count]:
            working[idx] = _truncate_content(working[idx], truncate_chars)
        stats["levels_applied"].append(1)

    if under_target():
        stats["final_count"] = len(working)
        stats["final_tokens"] = _total_tokens(working)
        return working, stats

    # Level 2 — truncate next 25% (indices 25–50%)
    if truncatable:
        level2_start = max(1, len(truncatable) // 4)
        level2_end = level2_start + max(1, len(truncatable) // 4)
        if len(truncatable) > level2_start:
            for idx in truncatable[level2_start:level2_end]:
                working[idx] = _truncate_content(working[idx], truncate_chars)
            stats["levels_applied"].append(2)

    if under_target():
        stats["final_count"] = len(working)
        stats["final_tokens"] = _total_tokens(working)
        return working, stats

    # ------------------------------------------------------------------ #
    # Level 3: remove oldest tool-call/result PAIRS (always together)    #
    # ------------------------------------------------------------------ #
    non_system_indices = [i for i, m in enumerate(working) if not _is_system(m)]
    protected_tail = (
        set(non_system_indices[-2:])
        if len(non_system_indices) >= 2
        else set(non_system_indices)
    )

    indices_to_remove: set[int] = set()
    for i, msg in enumerate(working):
        if i in protected_tail:
            continue
        if _has_tool_calls(msg):
            result_indices = _find_tool_call_pair_indices(working, i)
            pair_indices = {i} | set(result_indices)
            # Only remove if none of the pair members are in the protected tail
            if not pair_indices.intersection(protected_tail):
                indices_to_remove |= pair_indices

    if indices_to_remove:
        working = [m for idx, m in enumerate(working) if idx not in indices_to_remove]
        stats["levels_applied"].append(3)

    if under_target():
        stats["final_count"] = len(working)
        stats["final_tokens"] = _total_tokens(working)
        return working, stats

    # ------------------------------------------------------------------ #
    # Level 4: stub old user messages with '[message compacted]'         #
    # ------------------------------------------------------------------ #
    non_system_indices = [i for i, m in enumerate(working) if not _is_system(m)]
    protected_tail = (
        set(non_system_indices[-2:])
        if len(non_system_indices) >= 2
        else set(non_system_indices)
    )

    compacted_any = False
    for i, msg in enumerate(working):
        if i not in protected_tail and msg.role == "user":
            stub = msg.model_copy(deep=True)
            stub.content = "[message compacted]"
            working[i] = stub
            compacted_any = True

    if compacted_any:
        stats["levels_applied"].append(4)

    if under_target():
        stats["final_count"] = len(working)
        stats["final_tokens"] = _total_tokens(working)
        return working, stats

    # ------------------------------------------------------------------ #
    # Level 5: remove oldest user/assistant pairs                        #
    # ------------------------------------------------------------------ #
    non_system_indices = [i for i, m in enumerate(working) if not _is_system(m)]
    protected_tail = (
        set(non_system_indices[-2:])
        if len(non_system_indices) >= 2
        else set(non_system_indices)
    )

    pairs_to_remove: set[int] = set()
    i = 0
    while i < len(working):
        if i not in protected_tail and working[i].role == "user":
            # Find the immediately following assistant response
            for j in range(i + 1, len(working)):
                if working[j].role == "assistant" and j not in protected_tail:
                    pairs_to_remove.add(i)
                    pairs_to_remove.add(j)
                    break
        i += 1

    if pairs_to_remove:
        working = [m for idx, m in enumerate(working) if idx not in pairs_to_remove]
        stats["levels_applied"].append(5)

    if under_target():
        stats["final_count"] = len(working)
        stats["final_tokens"] = _total_tokens(working)
        return working, stats

    # ------------------------------------------------------------------ #
    # Level 6: remove all but last N turns (protected_recent %)         #
    # ------------------------------------------------------------------ #
    non_system_msgs = [m for m in working if not _is_system(m)]
    system_msgs = [m for m in working if _is_system(m)]
    keep_count = max(1, int(len(non_system_msgs) * protected_recent))
    working = system_msgs + non_system_msgs[-keep_count:]
    stats["levels_applied"].append(6)

    if under_target():
        stats["final_count"] = len(working)
        stats["final_tokens"] = _total_tokens(working)
        return working, stats

    # ------------------------------------------------------------------ #
    # Level 7: Emergency — keep only system prompt + last turn           #
    # ------------------------------------------------------------------ #
    system_msgs = [m for m in working if _is_system(m)]
    non_system_msgs = [m for m in working if not _is_system(m)]
    last_turn = non_system_msgs[-1:] if non_system_msgs else []
    working = system_msgs + last_turn
    stats["levels_applied"].append(7)

    stats["final_count"] = len(working)
    stats["final_tokens"] = _total_tokens(working)
    return working, stats


class SimpleContextManager:
    """Session-keyed in-memory context manager with ephemeral progressive compaction.

    Each session_id gets isolated message storage via self._sessions.
    Compaction is ephemeral — get_messages returns a compacted copy, never
    modifying the stored messages.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, list[Message]] = {}
        self.max_tokens: int = 200_000
        self.compact_threshold: float = 0.85
        self.target_usage: float = 0.60
        self.protected_recent: float = 0.30
        # protected_tool_results shields the most recent N tool results from
        # Level 1/2 content truncation only.  Level 3+ may still remove or
        # truncate those messages if budget pressure demands it.
        self.protected_tool_results: int = 5
        self.truncate_chars: int = 8_000

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_session(self, session_id: str) -> list[Message]:
        """Return the message list for session_id, creating it if absent."""
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        return self._sessions[session_id]

    # ------------------------------------------------------------------ #
    # Mutation methods                                                    #
    # ------------------------------------------------------------------ #

    async def add_message(self, session_id: str, message: Message) -> None:
        """Append a message to the session store, stamping a timestamp into metadata."""
        msg = message.model_copy(deep=True)
        if msg.metadata is None:
            msg.metadata = {}
        msg.metadata["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
        self._get_session(session_id).append(msg)

    async def set_messages(self, session_id: str, messages: list[Message]) -> None:
        """Replace the session's stored message list with the provided messages."""
        self._sessions[session_id] = [m.model_copy(deep=True) for m in messages]

    async def clear(self, session_id: str) -> None:
        """Empty the stored message list for the given session."""
        self._sessions[session_id] = []

    # ------------------------------------------------------------------ #
    # Query (ephemeral compaction)                                        #
    # ------------------------------------------------------------------ #

    async def get_messages(
        self,
        session_id: str,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ) -> list[Message]:
        """Return a (possibly compacted) copy of the session's message list.

        Compaction is ephemeral: the stored messages are never modified.

        Budget = context_window - max_output_tokens if both provided,
                 else self.max_tokens.

        If compaction occurs, a compaction-notice system message is inserted
        after any existing system messages.
        """
        # Determine budget
        if context_window is not None:
            budget = context_window - (max_output_tokens or 0)
        else:
            budget = self.max_tokens

        # Work on a deep copy so the stored list is never mutated
        snapshot: list[Message] = copy.deepcopy(self._get_session(session_id))

        current_tokens = _total_tokens(snapshot)
        threshold = int(budget * self.compact_threshold)

        if current_tokens <= threshold:
            # No compaction needed — return copy as-is
            return snapshot

        target_tokens = int(budget * self.target_usage)

        compacted, stats = _compact(
            snapshot,
            target_tokens=target_tokens,
            protected_recent=self.protected_recent,
            protected_tool_results=self.protected_tool_results,
            truncate_chars=self.truncate_chars,
        )

        if stats.get("levels_applied"):
            # Insert compaction notice after the last system message
            notice_content = format_compaction_notice(stats)
            notice_msg = Message(role="system", content=notice_content)

            last_sys_idx = -1
            for i, m in enumerate(compacted):
                if _is_system(m):
                    last_sys_idx = i

            insert_pos = last_sys_idx + 1
            compacted.insert(insert_pos, notice_msg)

        return compacted
