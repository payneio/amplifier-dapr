"""Tests for commands.py - slash command dispatcher."""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock

from amplifier_ipc_cli.commands import SlashResult, dispatch_slash


# ---------------------------------------------------------------------------
# TestSlashResult
# ---------------------------------------------------------------------------


class TestSlashResult:
    def test_defaults(self) -> None:
        """SlashResult has default values: should_exit=False, inline_prompt=None, new_mode=None."""
        result = SlashResult()
        assert result.should_exit is False
        assert result.inline_prompt is None
        assert result.new_mode is None

    def test_custom_values(self) -> None:
        """SlashResult accepts custom values."""
        result = SlashResult(
            should_exit=True, inline_prompt="hello", new_mode="brainstorm"
        )
        assert result.should_exit is True
        assert result.inline_prompt == "hello"
        assert result.new_mode == "brainstorm"

    def test_is_dataclass(self) -> None:
        """SlashResult is a dataclass with should_exit, inline_prompt, new_mode fields."""
        field_names = {f.name for f in fields(SlashResult)}
        assert "should_exit" in field_names
        assert "inline_prompt" in field_names
        assert "new_mode" in field_names


# ---------------------------------------------------------------------------
# TestDispatchSlash
# ---------------------------------------------------------------------------


class TestDispatchSlash:
    def _make_console(self) -> MagicMock:
        """Create a mock console."""
        console = MagicMock()
        console.print = MagicMock()
        return console

    def _make_client(self) -> MagicMock:
        """Create a mock client with async methods."""
        client = MagicMock()
        client.get_session_info = AsyncMock(
            return_value={"id": "sess-1", "status": "active", "turn_count": 3}
        )
        client.get_tools = AsyncMock(
            return_value=[
                {"name": "bash", "description": "Run bash commands"},
                {"name": "read_file", "description": "Read a file from the filesystem"},
            ]
        )
        client.clear_session = AsyncMock(return_value={"cleared": True})
        client.get_modes = AsyncMock(
            return_value=[
                {"name": "brainstorm", "description": "Brainstorm mode"},
            ]
        )
        client.get_agents = AsyncMock(
            return_value=[
                {"name": "zen-architect", "description": "Designs module specs"},
                {"name": "modular-builder", "description": "Builds modules"},
            ]
        )
        return client

    async def test_exit(self) -> None:
        """/exit returns SlashResult with should_exit=True."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/exit", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is True

    async def test_quit(self) -> None:
        """/quit returns SlashResult with should_exit=True."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/quit", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is True

    async def test_help(self) -> None:
        """/help prints help text to the console."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/help", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        # console.print should have been called with some help text
        console.print.assert_called()

    async def test_status(self) -> None:
        """/status calls client.get_session_info and renders a Panel with a Table."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/status", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        client.get_session_info.assert_awaited_once_with("sess-1")
        # Console should print a Panel
        console.print.assert_called()

    async def test_tools(self) -> None:
        """/tools calls client.get_tools and renders a Table."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/tools", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        client.get_tools.assert_awaited_once_with("sess-1")
        console.print.assert_called()

    async def test_clear(self) -> None:
        """/clear calls client.clear_session."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/clear", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        client.clear_session.assert_awaited_once_with("sess-1")

    async def test_unknown_command(self) -> None:
        """Unknown commands print a yellow warning."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/unknowncmd", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        # Should print a warning
        console.print.assert_called()
        # Verify warning contains both 'yellow' markup and the unknown command name
        args = console.print.call_args[0][0]
        assert "yellow" in args
        assert "unknowncmd" in args

    async def test_status_exception_handled(self) -> None:
        """/status catches exceptions and prints a yellow warning."""
        console = self._make_console()
        client = self._make_client()
        client.get_session_info = AsyncMock(side_effect=Exception("Connection failed"))
        result = await dispatch_slash("/status", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        console.print.assert_called()

    async def test_tools_exception_handled(self) -> None:
        """/tools catches exceptions and prints a yellow warning."""
        console = self._make_console()
        client = self._make_client()
        client.get_tools = AsyncMock(side_effect=Exception("Connection failed"))
        result = await dispatch_slash("/tools", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        console.print.assert_called()

    async def test_modes(self) -> None:
        """/modes calls client.get_modes and renders a Table."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/modes", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        client.get_modes.assert_awaited_once_with("sess-1")
        console.print.assert_called()

    async def test_mode_set(self) -> None:
        """/mode NAME on sets the active mode and returns new_mode."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/mode brainstorm on", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.new_mode == "brainstorm"

    async def test_mode_clear(self) -> None:
        """/mode NAME off clears the active mode, new_mode=None."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/mode brainstorm off", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.new_mode is None

    async def test_agents(self) -> None:
        """/agents calls client.get_agents and renders a Table."""
        console = self._make_console()
        client = self._make_client()
        result = await dispatch_slash("/agents", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        client.get_agents.assert_awaited_once_with("sess-1")
        console.print.assert_called()

    async def test_agents_exception_handled(self) -> None:
        """/agents catches exceptions and prints a yellow warning."""
        console = self._make_console()
        client = self._make_client()
        client.get_agents = AsyncMock(side_effect=Exception("Connection failed"))
        result = await dispatch_slash("/agents", client, "sess-1", console)
        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        console.print.assert_called()
