"""Output truncation with head/tail preservation."""

from __future__ import annotations

from collections.abc import Iterable

_DEFAULT_MAX_BYTES = 100_000


def _collect_lines(lines: Iterable[str], budget: int) -> list[str]:
    """Accumulate lines from *lines* until adding the next would exceed *budget* bytes.

    Args:
        lines: Source of lines to consume (forward or reversed iterator).
        budget: Maximum byte ceiling; each line is counted as its UTF-8 length
                plus one for the ``"\\n"`` separator.

    Returns:
        The collected lines in the order they were yielded from *lines*.
    """
    collected: list[str] = []
    used = 0
    for line in lines:
        line_bytes = len(line.encode("utf-8")) + 1  # +1 for the "\n" separator
        if used + line_bytes > budget:
            break
        collected.append(line)
        used += line_bytes
    return collected


def truncate_output(text: str, max_bytes: int = _DEFAULT_MAX_BYTES) -> tuple[str, bool]:
    """Truncate *text* to *max_bytes* while preserving head and tail content.

    Args:
        text: Command output to (potentially) truncate.
        max_bytes: Byte ceiling; defaults to :data:`_DEFAULT_MAX_BYTES`.

    Returns:
        A ``(result, was_truncated)`` tuple. *was_truncated* is ``False`` when
        the original text fit within *max_bytes*; ``True`` otherwise.
    """
    original_bytes = len(text.encode("utf-8"))
    if original_bytes <= max_bytes:
        return (text, False)

    head_budget = int(max_bytes * 0.4)
    tail_budget = int(max_bytes * 0.2)

    lines = text.split("\n")

    head_lines = _collect_lines(lines, head_budget)

    tail_lines = _collect_lines(reversed(lines), tail_budget)
    tail_lines.reverse()  # restore chronological order

    head_content = "\n".join(head_lines)
    tail_content = "\n".join(tail_lines)

    shown_bytes = len(head_content.encode("utf-8")) + len(tail_content.encode("utf-8"))

    marker = (
        f"\n[...truncated {original_bytes:,} bytes, showing {shown_bytes:,} bytes...]\n"
    )

    return (head_content + marker + tail_content, True)
