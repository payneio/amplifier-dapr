"""Tests for the MachineDriver abstract base class."""

from pathlib import Path

import pytest

from svc_machine.driver import (
    ExecResult,  # noqa: F401
    FileEditResult,  # noqa: F401
    FileGlobResult,  # noqa: F401
    FileReadResult,  # noqa: F401
    MachineDriver,
)
from svc_machine.local_backend import LocalBackend


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


class TestLocalBackendImplementsDriver:
    """Tests verifying LocalBackend properly implements the MachineDriver ABC."""

    def test_local_backend_is_subclass_of_machine_driver(self) -> None:
        """issubclass(LocalBackend, MachineDriver) is True."""
        assert issubclass(LocalBackend, MachineDriver)

    def test_local_backend_instance_is_machine_driver(self, tmp_path: Path) -> None:
        """LocalBackend can be instantiated and isinstance(backend, MachineDriver) is True."""
        backend = LocalBackend(workspace_dir=tmp_path)
        assert isinstance(backend, MachineDriver)
