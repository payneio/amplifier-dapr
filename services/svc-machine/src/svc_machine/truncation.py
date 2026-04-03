"""Output truncation with head/tail preservation."""

from __future__ import annotations

_DEFAULT_MAX_BYTES = 100_000


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

    # --- head: collect lines until head_budget exceeded ---
    head_lines: list[str] = []
    head_bytes = 0
    for line in lines:
        line_bytes = len(line.encode("utf-8")) + 1  # +1 for the "\n" separator
        if head_bytes + line_bytes > head_budget:
            break
        head_lines.append(line)
        head_bytes += line_bytes

    # --- tail: collect lines from the end until tail_budget exceeded ---
    tail_lines: list[str] = []
    tail_bytes = 0
    for line in reversed(lines):
        line_bytes = len(line.encode("utf-8")) + 1  # +1 for the "\n" separator
        if tail_bytes + line_bytes > tail_budget:
            break
        tail_lines.append(line)
        tail_bytes += line_bytes
    tail_lines.reverse()  # restore chronological order

    head_content = "\n".join(head_lines)
    tail_content = "\n".join(tail_lines)

    shown_bytes = len(head_content.encode("utf-8")) + len(tail_content.encode("utf-8"))

    marker = (
        f"\n[...truncated {original_bytes:,} bytes, showing {shown_bytes:,} bytes...]\n"
    )

    return (head_content + marker + tail_content, True)
