"""Tests for the MachineDriver abstract base class."""

import pytest

from svc_machine.driver import (
    ExecResult,  # noqa: F401
    FileEditResult,  # noqa: F401
    FileGlobResult,  # noqa: F401
    FileReadResult,  # noqa: F401
    MachineDriver,
)


def test_machine_driver_cannot_be_instantiated_directly() -> None:
    """MachineDriver() raises TypeError because it is an ABC."""
    with pytest.raises(TypeError):
        MachineDriver()  # type: ignore[abstract]


def test_machine_driver_abstractmethods() -> None:
    """MachineDriver.__abstractmethods__ contains exactly the required methods."""
    expected = {
        "connect",
        "disconnect",
        "exec",
        "exec_background",
        "file_read",
        "file_write",
        "file_edit",
        "file_list",
        "file_glob",
        "file_grep",
    }
    assert MachineDriver.__abstractmethods__ == expected
