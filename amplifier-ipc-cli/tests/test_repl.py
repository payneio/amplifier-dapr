"""Tests for repl.py - REPL module for the Amplifier IPC CLI."""

from __future__ import annotations

import os
import tempfile

from rich.console import Console

from amplifier_ipc_cli.repl import (
    CancellationState,
    build_prompt_html,
    process_mentions,
)


# ---------------------------------------------------------------------------
# CancellationState tests
# ---------------------------------------------------------------------------


class TestCancellationState:
    def test_initial_state(self) -> None:
        """CancellationState starts with all flags false and no current tool."""
        state = CancellationState()
        assert state.is_cancelled is False
        assert state.is_immediate is False
        assert state.current_tool is None

    def test_request_graceful(self) -> None:
        """request_graceful() sets is_cancelled=True but leaves is_immediate=False."""
        state = CancellationState()
        state.request_graceful()
        assert state.is_cancelled is True
        assert state.is_immediate is False

    def test_request_immediate(self) -> None:
        """request_immediate() sets both is_cancelled=True and is_immediate=True."""
        state = CancellationState()
        state.request_immediate()
        assert state.is_cancelled is True
        assert state.is_immediate is True

    def test_reset(self) -> None:
        """reset() clears all flags back to their initial values."""
        state = CancellationState()
        state.request_immediate()
        state.current_tool = "bash"
        state.reset()
        assert state.is_cancelled is False
        assert state.is_immediate is False
        assert state.current_tool is None


# ---------------------------------------------------------------------------
# process_mentions tests
# ---------------------------------------------------------------------------


class TestProcessMentions:
    def test_no_mentions(self) -> None:
        """Input without @ mentions is returned unchanged (minus leading/trailing space)."""
        console = Console(quiet=True)
        result = process_mentions("hello world", console)
        assert "hello world" in result
        # No context_file blocks added
        assert "<context_file" not in result

    def test_nonexistent_file_skipped(self) -> None:
        """A mention pointing to a nonexistent file is removed but no block is added."""
        console = Console(quiet=True)
        result = process_mentions("hello @/nonexistent_xyz_file_abc.txt world", console)
        assert "<context_file" not in result
        # The @mention itself should be stripped from the text portion
        assert "@/nonexistent_xyz_file_abc.txt" not in result

    def test_existing_file_injected(self) -> None:
        """A mention pointing to an existing file is replaced by a <context_file> block."""
        console = Console(quiet=True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("file content here")
            tmp_path = f.name

        try:
            result = process_mentions(f"please look at @{tmp_path}", console)
            assert "<context_file" in result
            assert "file content here" in result
            # The @ mention path should be stripped from the user text portion
            assert (
                f"@{tmp_path}" not in result.split("</context_file>")[-1]
                if "</context_file>" in result
                else True
            )
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# build_prompt_html tests
# ---------------------------------------------------------------------------


class TestBuildPromptHtml:
    def test_no_mode(self) -> None:
        """With no active mode, prompt is a green '>'."""
        html = build_prompt_html(None)
        html_str = str(html)
        # Should contain a '>' character
        assert ">" in html_str
        # Should use green colour
        assert "green" in html_str.lower() or "ansigreen" in html_str.lower()
        # Should NOT contain mode brackets
        assert "[" not in html_str

    def test_with_mode(self) -> None:
        """With an active mode, prompt shows cyan '[mode_name]>'."""
        html = build_prompt_html("mymode")
        html_str = str(html)
        # Should contain the mode name in brackets
        assert "[mymode]" in html_str
        # Should use cyan colour
        assert "cyan" in html_str.lower() or "ansicyan" in html_str.lower()

    def test_html_escape(self) -> None:
        """Special HTML characters in mode name are escaped."""
        html = build_prompt_html("a&b<c>d")
        html_str = str(html)
        # Raw chars should not appear unescaped inside tag content
        # The mode name part should be HTML-escaped
        assert "&amp;" in html_str or "a&b" not in html_str
        assert "&lt;" in html_str or "<c>" not in html_str
        assert "&gt;" in html_str or ">d" not in html_str
