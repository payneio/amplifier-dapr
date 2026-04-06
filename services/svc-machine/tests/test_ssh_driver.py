"""Tests for SSHDriver — SSH-based machine backend driver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from svc_machine.driver import ExecResult, MachineDriver
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
