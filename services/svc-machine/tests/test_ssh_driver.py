"""Tests for SSHDriver — SSH-based machine backend driver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from svc_machine.driver import ExecResult, FileEditResult, FileReadResult, MachineDriver
from svc_machine.ssh_driver import SSHDriver


def test_ssh_driver_is_subclass_of_machine_driver() -> None:
    """issubclass(SSHDriver, MachineDriver) is True."""
    assert issubclass(SSHDriver, MachineDriver)


def test_ssh_driver_can_be_instantiated() -> None:
    """SSHDriver(host='localhost', port=22, working_dir='/workspace') can be instantiated."""
    driver = SSHDriver(host="localhost", port=22, working_dir="/workspace")
    assert driver.host == "localhost"
    assert driver.port == 22
    assert driver.working_dir == "/workspace"
    assert driver._conn is None


async def test_connect_calls_asyncssh_connect() -> None:
    """connect() calls asyncssh.connect with host and port."""
    driver = SSHDriver(host="myhost", port=2222, working_dir="/workspace")
    mock_conn = MagicMock()
    mock_asyncssh = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=mock_conn)

    with patch("svc_machine.ssh_driver.asyncssh", mock_asyncssh):
        await driver.connect()

    mock_asyncssh.connect.assert_called_once()
    call_kwargs = mock_asyncssh.connect.call_args.kwargs
    assert call_kwargs.get("host") == "myhost"
    assert call_kwargs.get("port") == 2222


async def test_disconnect_closes_connection_and_sets_none() -> None:
    """disconnect() closes the connection and sets _conn to None."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")
    mock_conn = MagicMock()
    driver._conn = mock_conn

    await driver.disconnect()

    mock_conn.close.assert_called_once()
    assert driver._conn is None


async def test_exec_returns_exec_result() -> None:
    """exec() returns ExecResult with correct stdout, stderr, exit_code."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")

    mock_result = MagicMock()
    mock_result.stdout = "hello"
    mock_result.stderr = ""
    mock_result.returncode = 0

    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    driver._conn = mock_conn

    result = await driver.exec("echo hello")

    assert isinstance(result, ExecResult)
    assert result.stdout == "hello"
    assert result.stderr == ""
    assert result.exit_code == 0


async def test_exec_captures_nonzero_exit_code() -> None:
    """exec() captures non-zero exit codes."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")

    mock_result = MagicMock()
    mock_result.stdout = ""
    mock_result.stderr = "error output"
    mock_result.returncode = 42

    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    driver._conn = mock_conn

    result = await driver.exec("false_command")

    assert isinstance(result, ExecResult)
    assert result.exit_code == 42


async def test_exec_wraps_command_with_working_dir() -> None:
    """exec() wraps commands with 'cd /workspace && ...'."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")

    mock_result = MagicMock()
    mock_result.stdout = ""
    mock_result.stderr = ""
    mock_result.returncode = 0

    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    driver._conn = mock_conn

    await driver.exec("echo hello")

    call_args = mock_conn.run.call_args
    # First positional arg is the command sent over SSH
    command_sent = (
        call_args.args[0] if call_args.args else call_args.kwargs.get("command", "")
    )
    assert command_sent.startswith("cd /workspace && ")


async def test_exec_raises_if_not_connected() -> None:
    """exec() raises RuntimeError when called without a prior connect()."""
    import pytest

    driver = SSHDriver(host="localhost", working_dir="/workspace")
    # _conn is None — no connect() called
    with pytest.raises(RuntimeError, match="not connected"):
        await driver.exec("echo hi")


async def test_exec_background_raises_if_not_connected() -> None:
    """exec_background() raises RuntimeError when called without a prior connect()."""
    import pytest

    driver = SSHDriver(host="localhost", working_dir="/workspace")
    with pytest.raises(RuntimeError, match="not connected"):
        await driver.exec_background("sleep 10")


async def test_connect_raises_if_already_connected() -> None:
    """connect() raises RuntimeError when called while already connected."""
    import pytest
    from unittest.mock import MagicMock

    driver = SSHDriver(host="localhost", working_dir="/workspace")
    driver._conn = MagicMock()  # simulate an existing live connection

    with pytest.raises(RuntimeError, match="already connected"):
        await driver.connect()


# ─── File operation tests (Task 5) ───────────────────────────────────────────


def _make_sftp_mock(
    read_data: bytes | None = None, raise_on_open: Exception | None = None
) -> MagicMock:
    """Build a mock SFTP client with configurable read/write behaviour."""
    mock_file = AsyncMock()
    if read_data is not None:
        mock_file.read = AsyncMock(return_value=read_data)
    mock_file.write = AsyncMock()
    mock_file.close = AsyncMock()

    mock_sftp = AsyncMock()
    if raise_on_open is not None:
        mock_sftp.open = AsyncMock(side_effect=raise_on_open)
    else:
        mock_sftp.open = AsyncMock(return_value=mock_file)

    return mock_sftp


def _make_conn_with_sftp(mock_sftp: MagicMock) -> AsyncMock:
    """Build a mock SSH connection that returns the given SFTP mock."""
    mock_exec_result = MagicMock()
    mock_exec_result.stdout = ""
    mock_exec_result.stderr = ""
    mock_exec_result.returncode = 0

    mock_conn = AsyncMock()
    mock_conn.start_sftp_client = AsyncMock(return_value=mock_sftp)
    mock_conn.run = AsyncMock(return_value=mock_exec_result)
    return mock_conn


# ── Acceptance criterion 1: file_read_async returns FileReadResult ────────────


async def test_file_read_async_returns_file_read_result() -> None:
    """file_read() returns a FileReadResult with content and total_lines."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")
    mock_sftp = _make_sftp_mock(read_data=b"line1\nline2\nline3\n")
    driver._conn = _make_conn_with_sftp(mock_sftp)

    result = await driver.file_read("/workspace/test.txt")

    assert isinstance(result, FileReadResult)
    assert result.total_lines == 3
    assert "line1" in result.content
    assert "line2" in result.content


async def test_file_read_async_applies_offset_and_limit() -> None:
    """file_read() applies 1-based offset and optional limit to lines."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")
    mock_sftp = _make_sftp_mock(read_data=b"a\nb\nc\nd\ne\n")
    driver._conn = _make_conn_with_sftp(mock_sftp)

    # offset=2 → skip line 1 ("a"), limit=2 → take lines 2,3 ("b","c")
    result = await driver.file_read("/workspace/test.txt", offset=2, limit=2)

    assert result is not None
    assert result.total_lines == 5
    lines = result.content.splitlines()
    assert lines == ["b", "c"]


# ── Acceptance criterion 2: file_read_async returns None for OSError ──────────


async def test_file_read_async_returns_none_on_oserror() -> None:
    """file_read() returns None when the file does not exist (OSError)."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")
    mock_sftp = _make_sftp_mock(raise_on_open=OSError("No such file"))
    driver._conn = _make_conn_with_sftp(mock_sftp)

    result = await driver.file_read("/workspace/nonexistent.txt")

    assert result is None


# ── Acceptance criterion 3: file_write_async writes content and returns True ──


async def test_file_write_async_writes_content_and_returns_true() -> None:
    """file_write() writes content via SFTP and returns True."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")
    mock_sftp = _make_sftp_mock()
    driver._conn = _make_conn_with_sftp(mock_sftp)

    result = await driver.file_write("/workspace/test.txt", "hello world\n")

    assert result is True
    # The mock file's write() should have been called with encoded content
    mock_sftp.open.return_value.write.assert_called_once_with(b"hello world\n")


# ── file_edit_async ────────────────────────────────────────────────────────────


async def test_file_edit_async_replaces_string() -> None:
    """file_edit() replaces old_string with new_string and returns FileEditResult."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")
    mock_sftp = _make_sftp_mock(read_data=b"hello world\n")
    driver._conn = _make_conn_with_sftp(mock_sftp)

    result = await driver.file_edit(
        "/workspace/test.txt", old_string="world", new_string="earth"
    )

    assert isinstance(result, FileEditResult)
    assert result.success is True
    assert result.replacements_made == 1


async def test_file_edit_async_returns_none_for_missing_file() -> None:
    """file_edit() returns None when the target file does not exist."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")
    mock_sftp = _make_sftp_mock(raise_on_open=OSError("No such file"))
    driver._conn = _make_conn_with_sftp(mock_sftp)

    result = await driver.file_edit(
        "/workspace/missing.txt", old_string="a", new_string="b"
    )

    assert result is None


# ── Acceptance criterion 4: file_grep executes rg over SSH ───────────────────


async def test_file_grep_executes_rg_and_returns_matches() -> None:
    """file_grep() executes rg over SSH and returns a dict with correct count."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")

    mock_result = MagicMock()
    mock_result.stdout = "file1.py\nfile2.py\n"
    mock_result.stderr = ""
    mock_result.returncode = 0

    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    driver._conn = mock_conn

    result = await driver.file_grep("pattern", path=".")

    assert result is not None
    assert "matches" in result
    assert result["total_matches"] == 2
    assert "file1.py" in result["matches"]


async def test_file_grep_count_mode_parses_correctly() -> None:
    """file_grep() in count mode returns list of {file, count} dicts."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")

    mock_result = MagicMock()
    mock_result.stdout = "src/main.py:5\nsrc/utils.py:2\n"
    mock_result.stderr = ""
    mock_result.returncode = 0

    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    driver._conn = mock_conn

    result = await driver.file_grep("pattern", path=".", output_mode="count")

    assert result is not None
    matches = result["matches"]
    assert len(matches) == 2
    assert matches[0]["file"] == "src/main.py"
    assert matches[0]["count"] == 5


async def test_file_grep_content_mode_parses_correctly() -> None:
    """file_grep() in content mode returns list of {file, line, content} dicts."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")

    mock_result = MagicMock()
    mock_result.stdout = "src/main.py:10:    do_something()\n"
    mock_result.stderr = ""
    mock_result.returncode = 0

    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=mock_result)
    driver._conn = mock_conn

    result = await driver.file_grep("pattern", path=".", output_mode="content")

    assert result is not None
    matches = result["matches"]
    assert len(matches) == 1
    assert matches[0]["file"] == "src/main.py"
    assert matches[0]["line"] == 10
    assert "do_something" in matches[0]["content"]


# ── _parse_grep_output static method ─────────────────────────────────────────


def test_parse_grep_output_files_with_matches() -> None:
    """_parse_grep_output handles files_with_matches mode: returns list of paths."""
    output = "src/foo.py\nsrc/bar.py\n"
    result = SSHDriver._parse_grep_output(output, "files_with_matches")
    assert result == ["src/foo.py", "src/bar.py"]


def test_parse_grep_output_count() -> None:
    """_parse_grep_output handles count mode: returns [{file, count}] list."""
    output = "foo.py:3\nbar.py:1\n"
    result = SSHDriver._parse_grep_output(output, "count")
    assert result == [{"file": "foo.py", "count": 3}, {"file": "bar.py", "count": 1}]


def test_parse_grep_output_content() -> None:
    """_parse_grep_output handles content mode: returns [{file, line, content}] list."""
    output = "foo.py:42:    hello_world()\n"
    result = SSHDriver._parse_grep_output(output, "content")
    assert len(result) == 1
    assert result[0]["file"] == "foo.py"
    assert result[0]["line"] == 42
    assert "hello_world" in result[0]["content"]


# ── _resolve_path helper ──────────────────────────────────────────────────────


def test_resolve_path_absolute() -> None:
    """_resolve_path leaves absolute paths unchanged."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")
    assert driver._resolve_path("/etc/hosts") == "/etc/hosts"


def test_resolve_path_relative() -> None:
    """_resolve_path joins relative paths with working_dir."""
    driver = SSHDriver(host="localhost", working_dir="/workspace")
    assert driver._resolve_path("config.json") == "/workspace/config.json"
