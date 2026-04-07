"""Phase 5 E2E integration tests for the Amplifier IPC CLI modules.

In-process tests — no Docker required.

Covers:
  - workspace.resolve_workspace_content
  - settings.CLISettings
  - commands.dispatch_slash / SlashResult
  - display.StreamingDisplay
  - client.SessionClient / SSEEvent
  - repl.process_mentions
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from rich.console import Console

from amplifier_cli.client import SSEEvent, SessionClient
from amplifier_cli.commands import SlashResult, dispatch_slash
from amplifier_cli.display import StreamingDisplay
from amplifier_cli.settings import CLISettings
from amplifier_cli.workspace import resolve_workspace_content


# ---------------------------------------------------------------------------
# Shared test helper
# ---------------------------------------------------------------------------


def _make_console() -> tuple[Console, StringIO]:
    """Return a Rich Console backed by a StringIO for output capture."""
    buf = StringIO()
    console = Console(file=buf, no_color=True, width=120)
    return console, buf


# ===========================================================================
# TestWorkspaceResolver
# ===========================================================================


class TestWorkspaceResolver:
    """resolve_workspace_content() reads eligible files from .amplifier/."""

    def test_returns_agents_md(self, tmp_path: Path) -> None:
        """AGENTS.md inside .amplifier/ appears in the result dict."""
        amplifier_dir = tmp_path / ".amplifier"
        amplifier_dir.mkdir()
        (amplifier_dir / "AGENTS.md").write_text("# Agents")

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/AGENTS.md" in result
        assert result[".amplifier/AGENTS.md"] == "# Agents"

    def test_excludes_settings_yaml(self, tmp_path: Path) -> None:
        """settings.yaml is excluded from the result."""
        amplifier_dir = tmp_path / ".amplifier"
        amplifier_dir.mkdir()
        (amplifier_dir / "settings.yaml").write_text("url: http://localhost:8090\n")
        (amplifier_dir / "AGENTS.md").write_text("# Agents")

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/settings.yaml" not in result
        assert ".amplifier/AGENTS.md" in result

    def test_excludes_settings_local_yaml(self, tmp_path: Path) -> None:
        """settings.local.yaml is excluded from the result."""
        amplifier_dir = tmp_path / ".amplifier"
        amplifier_dir.mkdir()
        (amplifier_dir / "settings.local.yaml").write_text("url: http://custom:9000\n")

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/settings.local.yaml" not in result

    def test_empty_dict_when_no_amplifier_dir(self, tmp_path: Path) -> None:
        """Returns empty dict when .amplifier/ does not exist."""
        result = resolve_workspace_content(tmp_path)

        assert result == {}

    def test_multiple_files_all_included(self, tmp_path: Path) -> None:
        """All eligible files are present in the result."""
        amplifier_dir = tmp_path / ".amplifier"
        amplifier_dir.mkdir()
        (amplifier_dir / "AGENTS.md").write_text("# Agents")
        (amplifier_dir / "context.md").write_text("Some context")

        result = resolve_workspace_content(tmp_path)

        assert len(result) == 2
        assert ".amplifier/AGENTS.md" in result
        assert ".amplifier/context.md" in result

    def test_skips_large_files(self, tmp_path: Path) -> None:
        """Files exceeding 512 KB are skipped."""
        amplifier_dir = tmp_path / ".amplifier"
        amplifier_dir.mkdir()
        large_file = amplifier_dir / "large.txt"
        large_file.write_bytes(b"x" * (512 * 1024 + 1))

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/large.txt" not in result

    def test_skips_binary_files(self, tmp_path: Path) -> None:
        """Non-UTF-8 binary files are silently skipped."""
        amplifier_dir = tmp_path / ".amplifier"
        amplifier_dir.mkdir()
        binary_file = amplifier_dir / "binary.bin"
        binary_file.write_bytes(bytes(range(256)))

        result = resolve_workspace_content(tmp_path)

        assert ".amplifier/binary.bin" not in result

    def test_keys_use_relative_path(self, tmp_path: Path) -> None:
        """Dict keys are relative to workspace_root, not absolute paths."""
        amplifier_dir = tmp_path / ".amplifier"
        amplifier_dir.mkdir()
        (amplifier_dir / "readme.md").write_text("hi")

        result = resolve_workspace_content(tmp_path)

        keys = list(result.keys())
        assert len(keys) == 1
        assert not keys[0].startswith("/")
        assert keys[0] == ".amplifier/readme.md"


# ===========================================================================
# TestCLISettings
# ===========================================================================


class TestCLISettings:
    """CLISettings.from_yaml() loads fields and falls back to defaults."""

    def test_from_yaml_loads_all_fields(self, tmp_path: Path) -> None:
        """Valid YAML populates url and provider."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text("url: http://my-server:9000\nprovider: anthropic\n")

        settings = CLISettings.from_yaml(settings_file)

        assert settings.url == "http://my-server:9000"
        assert settings.provider == "anthropic"

    def test_from_yaml_defaults_on_missing_file(self, tmp_path: Path) -> None:
        """Missing file → default url and provider."""
        missing = tmp_path / "nonexistent.yaml"
        settings = CLISettings.from_yaml(missing)

        assert settings.url == "http://localhost:8090"
        assert settings.provider == "mock"

    def test_from_yaml_defaults_on_invalid_yaml(self, tmp_path: Path) -> None:
        """Malformed YAML → defaults."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text(":\t: bad yaml {{{\n")

        settings = CLISettings.from_yaml(settings_file)

        assert settings.url == "http://localhost:8090"
        assert settings.provider == "mock"

    def test_from_yaml_partial_override(self, tmp_path: Path) -> None:
        """YAML with only url uses the default provider."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text("url: http://other:1234\n")

        settings = CLISettings.from_yaml(settings_file)

        assert settings.url == "http://other:1234"
        assert settings.provider == "mock"

    def test_from_yaml_non_dict_returns_defaults(self, tmp_path: Path) -> None:
        """YAML content that is not a dict (e.g. a list) returns defaults."""
        settings_file = tmp_path / "settings.yaml"
        settings_file.write_text("- item1\n- item2\n")

        settings = CLISettings.from_yaml(settings_file)

        assert settings.url == "http://localhost:8090"
        assert settings.provider == "mock"

    def test_default_constructor(self) -> None:
        """CLISettings() with no args has the expected defaults."""
        settings = CLISettings()

        assert settings.url == "http://localhost:8090"
        assert settings.provider == "mock"


# ===========================================================================
# TestSlashCommands
# ===========================================================================


class TestSlashCommands:
    """dispatch_slash() correctly handles each slash command."""

    async def test_exit_returns_should_exit_true(self) -> None:
        """/exit → should_exit=True."""
        client = AsyncMock(spec=SessionClient)
        console, _ = _make_console()

        result = await dispatch_slash("/exit", client, "session-1", console)

        assert isinstance(result, SlashResult)
        assert result.should_exit is True

    async def test_quit_returns_should_exit_true(self) -> None:
        """/quit → should_exit=True."""
        client = AsyncMock(spec=SessionClient)
        console, _ = _make_console()

        result = await dispatch_slash("/quit", client, "session-1", console)

        assert result.should_exit is True

    async def test_help_prints_help_text(self) -> None:
        """/help prints help text and returns should_exit=False."""
        client = AsyncMock(spec=SessionClient)
        console, buf = _make_console()

        result = await dispatch_slash("/help", client, "session-1", console)

        assert result.should_exit is False
        output = buf.getvalue()
        # The help text advertises /exit and /help at minimum
        assert "/exit" in output or "/help" in output

    async def test_unknown_command_prints_warning_and_returns_default(self) -> None:
        """Unrecognised command prints a warning and returns default SlashResult."""
        client = AsyncMock(spec=SessionClient)
        console, buf = _make_console()

        result = await dispatch_slash("/unknowncmd", client, "session-1", console)

        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        output = buf.getvalue().lower()
        assert "unknown" in output

    async def test_status_calls_get_session_info(self) -> None:
        """/status calls client.get_session_info and returns SlashResult."""
        client = AsyncMock(spec=SessionClient)
        client.get_session_info.return_value = {
            "id": "session-1",
            "status": "active",
            "turn_count": 3,
        }
        console, buf = _make_console()

        result = await dispatch_slash("/status", client, "session-1", console)

        assert isinstance(result, SlashResult)
        assert result.should_exit is False
        client.get_session_info.assert_called_once_with("session-1")
        assert "session-1" in buf.getvalue()

    async def test_status_handles_client_error_gracefully(self) -> None:
        """/status with a failing client prints a warning, not an exception."""
        client = AsyncMock(spec=SessionClient)
        client.get_session_info.side_effect = ConnectionError("refused")
        console, buf = _make_console()

        result = await dispatch_slash("/status", client, "session-1", console)

        # Should still return a valid SlashResult, not raise
        assert isinstance(result, SlashResult)
        output = buf.getvalue()
        assert len(output) > 0  # Some message was printed

    async def test_mode_on_sets_new_mode(self) -> None:
        """/mode NAME on → SlashResult.new_mode == NAME."""
        client = AsyncMock(spec=SessionClient)
        console, _ = _make_console()

        result = await dispatch_slash("/mode zen on", client, "session-1", console)

        assert isinstance(result, SlashResult)
        assert result.new_mode == "zen"

    async def test_mode_off_clears_new_mode(self) -> None:
        """/mode NAME off → SlashResult.new_mode is None."""
        client = AsyncMock(spec=SessionClient)
        console, _ = _make_console()

        result = await dispatch_slash("/mode zen off", client, "session-1", console)

        assert isinstance(result, SlashResult)
        assert result.new_mode is None


# ===========================================================================
# TestStreamingDisplay
# ===========================================================================


class TestStreamingDisplay:
    """StreamingDisplay correctly dispatches and renders SSE events."""

    def test_token_event_renders_text(self) -> None:
        """token event prints its text to the console."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        display.handle_sse_event(
            SSEEvent(event="token", data={"text": "Hello, world!"})
        )

        assert "Hello, world!" in buf.getvalue()

    def test_thinking_event_renders_when_enabled(self) -> None:
        """thinking event renders when show_thinking=True."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console, show_thinking=True)

        display.handle_sse_event(
            SSEEvent(event="thinking", data={"thinking": "deep thoughts"})
        )

        assert "deep thoughts" in buf.getvalue()

    def test_thinking_event_suppressed_when_disabled(self) -> None:
        """thinking event is not rendered when show_thinking=False."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console, show_thinking=False)

        display.handle_sse_event(SSEEvent(event="thinking", data={"text": "hidden"}))

        assert "hidden" not in buf.getvalue()

    def test_tool_call_renders_name_and_args(self) -> None:
        """tool_call event renders tool name and argument key-value pairs."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        display.handle_sse_event(
            SSEEvent(
                event="tool_call",
                data={"tool_name": "bash", "arguments": {"command": "ls -la"}},
            )
        )

        output = buf.getvalue()
        # bash tool renders as "$ command" format (not the tool name explicitly)
        assert "$ ls -la" in output

    def test_tool_result_success(self) -> None:
        """tool_result event with success=True renders tool name and output."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        display.handle_sse_event(
            SSEEvent(
                event="tool_result",
                data={"tool_name": "bash", "success": True, "output": "tests passed"},
            )
        )

        output = buf.getvalue()
        assert "bash" in output
        assert "tests passed" in output

    def test_tool_result_failure(self) -> None:
        """tool_result event with success=False renders tool name and output."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        display.handle_sse_event(
            SSEEvent(
                event="tool_result",
                data={
                    "tool_name": "bash",
                    "success": False,
                    "output": "command not found",
                },
            )
        )

        output = buf.getvalue()
        assert "bash" in output
        assert "command not found" in output

    def test_complete_event_stores_response(self) -> None:
        """complete event stores the final response text in display.response."""
        console, _ = _make_console()
        display = StreamingDisplay(console=console)

        assert display.response is None

        display.handle_sse_event(
            SSEEvent(event="complete", data={"response": "Final answer"})
        )

        assert display.response == "Final answer"

    def test_unknown_event_is_silently_ignored(self) -> None:
        """Unknown event types do not raise exceptions."""
        console, _ = _make_console()
        display = StreamingDisplay(console=console)

        # Must not raise
        display.handle_sse_event(SSEEvent(event="totally_unknown_event_xyz", data={}))

    def test_error_event_renders_message(self) -> None:
        """error event prints the error message."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        display.handle_sse_event(
            SSEEvent(event="error", data={"message": "Something went wrong"})
        )

        assert "Something went wrong" in buf.getvalue()

    async def test_async_handle_event_delegates_to_sync(self) -> None:
        """async handle_event() produces the same output as handle_sse_event()."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        await display.handle_event(SSEEvent(event="token", data={"text": "async text"}))

        assert "async text" in buf.getvalue()

    def test_content_block_start_prints_border(self) -> None:
        """content_block_start event prints a thinking block header."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        display.handle_sse_event(
            SSEEvent(event="content_block_start", data={"type": "thinking"})
        )

        output = buf.getvalue()
        # Either "Thinking" label or the ╭ box-drawing character
        assert "Thinking" in output or "\u256d" in output

    def test_content_block_end_prints_border(self) -> None:
        """content_block_end event prints a thinking block footer."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        # Must start the thinking block first so the end handler has state to close.
        display.handle_sse_event(
            SSEEvent(event="content_block_start", data={"type": "thinking"})
        )
        display.handle_sse_event(
            SSEEvent(event="content_block_end", data={"type": "thinking"})
        )

        # ╚ double-line box-drawing character (bottom-left corner)
        assert "\u255a" in buf.getvalue()

    def test_full_streaming_sequence_no_error(self) -> None:
        """A realistic sequence of events renders without exceptions."""
        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        events = [
            SSEEvent(event="content_block_start", data={"type": "thinking"}),
            SSEEvent(event="thinking", data={"thinking": "Let me think..."}),
            SSEEvent(event="content_block_end", data={"type": "thinking"}),
            SSEEvent(event="token", data={"text": "Here is my answer: "}),
            SSEEvent(
                event="tool_call",
                data={"tool_name": "bash", "arguments": {"cmd": "ls"}},
            ),
            SSEEvent(
                event="tool_result",
                data={"tool_name": "bash", "success": True, "output": "file.txt"},
            ),
            SSEEvent(event="token", data={"text": "Done."}),
            SSEEvent(event="complete", data={"response": "Here is my answer: Done."}),
        ]

        for event in events:
            display.handle_sse_event(event)

        assert display.response == "Here is my answer: Done."
        output = buf.getvalue()
        assert "Here is my answer" in output
        assert "bash" in output


# ===========================================================================
# TestSSEEventParsing
# ===========================================================================


class TestSSEEventParsing:
    """SSEEvent.from_lines() correctly parses raw SSE text blocks."""

    def test_parse_event_and_json_data(self) -> None:
        """Standard event+data block is correctly parsed."""
        raw = 'event: token\ndata: {"text": "hello"}'
        event = SSEEvent.from_lines(raw)

        assert event is not None
        assert event.event == "token"
        assert event.data == {"text": "hello"}

    def test_default_event_type_is_message(self) -> None:
        """When no event line is present, type defaults to 'message'."""
        raw = 'data: {"text": "no event field"}'
        event = SSEEvent.from_lines(raw)

        assert event is not None
        assert event.event == "message"
        assert event.data == {"text": "no event field"}

    def test_empty_input_returns_none(self) -> None:
        """Empty or whitespace-only input returns None."""
        assert SSEEvent.from_lines("") is None
        assert SSEEvent.from_lines("   \n  ") is None

    def test_invalid_json_falls_back_to_raw_string(self) -> None:
        """Malformed JSON in data field is returned as a raw string."""
        raw = "event: error\ndata: not-valid-json"
        event = SSEEvent.from_lines(raw)

        assert event is not None
        assert event.event == "error"
        assert event.data == "not-valid-json"

    def test_complete_event_with_response_field(self) -> None:
        """complete event with a response field is parsed correctly."""
        raw = 'event: complete\ndata: {"response": "done"}'
        event = SSEEvent.from_lines(raw)

        assert event is not None
        assert event.event == "complete"
        assert event.data == {"response": "done"}

    def test_extra_whitespace_is_trimmed(self) -> None:
        """Leading/trailing whitespace around event and data values is stripped."""
        raw = 'event:   token   \ndata:   {"text": "trimmed"}   '
        event = SSEEvent.from_lines(raw)

        assert event is not None
        assert event.event == "token"
        assert event.data == {"text": "trimmed"}

    def test_multiline_block_last_data_wins(self) -> None:
        """When a block has multiple data lines, the last one is used."""
        raw = 'event: token\ndata: {"text": "first"}\ndata: {"text": "second"}'
        event = SSEEvent.from_lines(raw)

        assert event is not None
        # Per the parser implementation, the last data line overwrites previous ones
        assert event.data == {"text": "second"}


# ===========================================================================
# TestSessionClient
# ===========================================================================


class TestSessionClient:
    """SessionClient constructs correct URLs and HTTP bodies."""

    def test_default_base_url(self) -> None:
        """Default base_url is http://localhost:8090."""
        client = SessionClient()
        assert client.base_url == "http://localhost:8090"

    def test_custom_base_url(self) -> None:
        """Custom base_url is stored as provided."""
        client = SessionClient(base_url="http://my-service:9090")
        assert client.base_url == "http://my-service:9090"

    async def test_send_turn_posts_to_correct_path(self) -> None:
        """send_turn POSTs to /sessions/{session_id}/turn."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"response": "ok", "turn": 1}

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response

        client = SessionClient(base_url="http://localhost:8090")
        client._http = mock_http

        result = await client.send_turn(
            session_id="sess-1",
            prompt="hello",
            workspace_content="ws",
            provider_name="mock",
        )

        assert result == {"response": "ok", "turn": 1}
        mock_http.post.assert_called_once()
        call_args = mock_http.post.call_args
        url_arg = call_args.args[0] if call_args.args else ""
        assert "sess-1" in str(url_arg)
        assert "turn" in str(url_arg)

    def test_build_turn_body_all_fields(self) -> None:
        """_build_turn_body includes all provided optional fields."""
        client = SessionClient()
        body = client._build_turn_body(
            prompt="hello",
            workspace_content="ws",
            provider_name="anthropic",
            services=[{"name": "bash"}],
        )

        assert body["prompt"] == "hello"
        assert body["workspace_content"] == "ws"
        assert body["provider_name"] == "anthropic"
        assert body["services"] == [{"name": "bash"}]

    def test_build_turn_body_minimal(self) -> None:
        """_build_turn_body with only prompt omits optional fields."""
        client = SessionClient()
        body = client._build_turn_body(
            prompt="minimal",
            workspace_content=None,
            provider_name=None,
            services=None,
        )

        assert body == {"prompt": "minimal"}
        assert "workspace_content" not in body
        assert "provider_name" not in body
        assert "services" not in body

    async def test_send_turn_body_contains_correct_fields(self) -> None:
        """send_turn passes correct JSON body to HTTP client."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {}

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response

        client = SessionClient()
        client._http = mock_http

        await client.send_turn(
            session_id="sess-2",
            prompt="minimal",
        )

        body = mock_http.post.call_args.kwargs.get("json", {})
        assert body.get("prompt") == "minimal"
        assert "workspace_content" not in body
        assert "provider_name" not in body

    async def test_healthcheck_returns_true_on_200(self) -> None:
        """healthcheck returns True when service responds HTTP 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response

        client = SessionClient()
        client._http = mock_http

        assert await client.healthcheck() is True

    async def test_healthcheck_returns_false_on_non_200(self) -> None:
        """healthcheck returns False for non-200 status."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_http = AsyncMock()
        mock_http.get.return_value = mock_response

        client = SessionClient()
        client._http = mock_http

        assert await client.healthcheck() is False

    async def test_healthcheck_returns_false_on_http_error(self) -> None:
        """healthcheck returns False when an httpx.HTTPError is raised."""
        import httpx

        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.HTTPError("connection refused")

        client = SessionClient()
        client._http = mock_http

        assert await client.healthcheck() is False

    async def test_close_resets_internal_client(self) -> None:
        """close() acloses the underlying client and resets _http to None."""
        mock_http = AsyncMock()
        client = SessionClient()
        client._http = mock_http

        await client.close()

        mock_http.aclose.assert_called_once()
        assert client._http is None

    async def test_context_manager_protocol(self) -> None:
        """SessionClient works as an async context manager."""
        async with SessionClient() as client:
            assert isinstance(client, SessionClient)


# ===========================================================================
# TestProcessMentions
# ===========================================================================


class TestProcessMentions:
    """process_mentions() in repl.py injects @mention file content."""

    def test_no_mentions_returns_input_unchanged(self) -> None:
        """Input with no @mentions is returned unchanged."""
        from amplifier_cli.repl import process_mentions

        console, _ = _make_console()
        result = process_mentions("hello world", console)

        assert result == "hello world"

    def test_mention_nonexistent_file_strips_token(self) -> None:
        """@mention for a nonexistent file silently strips the token."""
        from amplifier_cli.repl import process_mentions

        console, _ = _make_console()
        result = process_mentions("check @nonexistent.txt please", console)

        assert "@nonexistent.txt" not in result

    def test_mention_existing_file_injects_context_block(self, tmp_path: Path) -> None:
        """@mention for a readable file prepends a <context_file> block."""
        from amplifier_cli.repl import process_mentions

        notes = tmp_path / "notes.txt"
        notes.write_text("important notes here")

        console, _ = _make_console()
        result = process_mentions(f"see @{notes} for details", console)

        assert "important notes here" in result
        assert "<context_file" in result
        assert str(notes) in result  # path attribute present

    def test_mention_strips_token_from_user_text(self, tmp_path: Path) -> None:
        """The @mention token itself is removed from the final prompt text."""
        from amplifier_cli.repl import process_mentions

        notes = tmp_path / "notes.txt"
        notes.write_text("file content")

        console, _ = _make_console()
        result = process_mentions(f"see @{notes} for details", console)

        # The @token should be stripped from the user text portion
        assert f"@{notes}" not in result
