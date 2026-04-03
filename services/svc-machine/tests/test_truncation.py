"""Tests for truncate_output — output truncation with head/tail preservation."""

from svc_machine.truncation import truncate_output


# ---------------------------------------------------------------------------
# TestTruncateOutput
# ---------------------------------------------------------------------------


class TestTruncateOutput:
    """Truncation behaviour for svc-machine command output."""

    def test_short_output_unchanged(self) -> None:
        """Text well under the byte limit is returned unchanged."""
        text = "hello world"
        result, was_truncated = truncate_output(text, max_bytes=500)
        assert result == text
        assert was_truncated is False

    def test_exact_limit_unchanged(self) -> None:
        """Text whose byte length exactly equals the limit is returned unchanged."""
        text = "a" * 500
        result, was_truncated = truncate_output(text, max_bytes=500)
        assert result == text
        assert was_truncated is False

    def test_over_limit_is_truncated(self) -> None:
        """200-line text truncated at 500 bytes: was_truncated True, marker present."""
        lines = [f"line-{i:04d}" for i in range(200)]
        text = "\n".join(lines)
        result, was_truncated = truncate_output(text, max_bytes=500)
        assert was_truncated is True
        assert "[...truncated" in result

    def test_truncated_has_head_and_tail(self) -> None:
        """500-line text truncated at 2000 bytes retains first and last lines."""
        lines = [f"line-{i:04d}" for i in range(500)]
        text = "\n".join(lines)
        result, was_truncated = truncate_output(text, max_bytes=2000)
        assert was_truncated is True
        assert "line-0000" in result
        assert "line-0499" in result

    def test_truncated_marker_has_byte_counts(self) -> None:
        """Truncation marker contains the original byte count."""
        text = "x" * 10_000
        result, was_truncated = truncate_output(text, max_bytes=1000)
        assert was_truncated is True
        # Marker always uses {:,} formatting, so exactly "10,000"
        assert "10,000" in result

    def test_empty_string(self) -> None:
        """Empty string is returned unchanged with was_truncated False."""
        result, was_truncated = truncate_output("", max_bytes=500)
        assert result == ""
        assert was_truncated is False

    def test_default_max_bytes(self) -> None:
        """Small text without explicit max_bytes returns was_truncated False (default 100,000)."""
        text = "short text"
        result, was_truncated = truncate_output(text)
        assert was_truncated is False
        assert result == text
