"""Tests for InstanceManager — per-session machine instance lifecycle management."""

from unittest.mock import AsyncMock, patch

import pytest

from svc_machine.driver import MachineDriver
from svc_machine.instance_manager import InstanceManager, InstanceNotFoundError


class FakeDriver(MachineDriver):
    """Minimal fake driver for lifecycle tests."""

    async def connect(self) -> None:  # type: ignore[override]
        pass

    async def disconnect(self) -> None:  # type: ignore[override]
        pass

    def exec(self, command, timeout=30, working_dir=None):  # type: ignore[override]
        return None

    def exec_background(self, command, working_dir=None):  # type: ignore[override]
        return None

    def file_read(self, path, offset=1, limit=None):  # type: ignore[override]
        return None

    def file_write(self, path, content):  # type: ignore[override]
        return None

    def file_edit(self, path, old_string, new_string, replace_all=False):  # type: ignore[override]
        return None

    def file_list(self, path="."):  # type: ignore[override]
        return None

    def file_glob(
        self, pattern, path=".", exclude=None, type_filter="file", include_ignored=False
    ):  # type: ignore[override]
        return None

    def file_grep(  # type: ignore[override]
        self,
        pattern,
        path=".",
        output_mode="files_with_matches",
        glob_pattern=None,
        file_type=None,
        after_context=None,
        before_context=None,
        context=None,
        case_insensitive=False,
        line_numbers=True,
        head_limit=None,
        offset=0,
        include_ignored=False,
        multiline=False,
    ):
        return None


@pytest.fixture
def manager() -> InstanceManager:
    return InstanceManager()


@pytest.fixture
def fake_driver() -> FakeDriver:
    """FakeDriver with connect/disconnect replaced by AsyncMock for call tracking."""
    driver = FakeDriver()
    driver.connect = AsyncMock()  # type: ignore[method-assign]
    driver.disconnect = AsyncMock()  # type: ignore[method-assign]
    return driver


async def test_create_instance_returns_nonempty_unique_ids(
    manager: InstanceManager, fake_driver: FakeDriver
) -> None:
    """create_instance() returns non-empty string IDs, and each call returns a unique ID."""
    with patch.object(manager, "_create_driver", return_value=fake_driver):
        id1 = await manager.create_instance("local", {})
        id2 = await manager.create_instance("local", {})
    assert isinstance(id1, str) and id1
    assert isinstance(id2, str) and id2
    assert id1 != id2


async def test_create_instance_calls_connect(
    manager: InstanceManager, fake_driver: FakeDriver
) -> None:
    """create_instance() awaits driver.connect() exactly once."""
    with patch.object(manager, "_create_driver", return_value=fake_driver):
        await manager.create_instance("local", {})
    fake_driver.connect.assert_called_once()  # type: ignore[attr-defined]


async def test_get_driver_returns_machine_driver(
    manager: InstanceManager, fake_driver: FakeDriver
) -> None:
    """get_driver() returns a MachineDriver for a valid instance ID."""
    with patch.object(manager, "_create_driver", return_value=fake_driver):
        instance_id = await manager.create_instance("local", {})
    driver = manager.get_driver(instance_id)
    assert isinstance(driver, MachineDriver)


async def test_get_driver_raises_instance_not_found(manager: InstanceManager) -> None:
    """get_driver() raises InstanceNotFoundError with instance_id attribute for unknown IDs."""
    with pytest.raises(InstanceNotFoundError) as exc_info:
        manager.get_driver("unknown-id")
    assert exc_info.value.instance_id == "unknown-id"


async def test_destroy_instance_removes_from_registry(
    manager: InstanceManager, fake_driver: FakeDriver
) -> None:
    """destroy_instance() removes the instance so get_driver() raises InstanceNotFoundError."""
    with patch.object(manager, "_create_driver", return_value=fake_driver):
        instance_id = await manager.create_instance("local", {})
    await manager.destroy_instance(instance_id)
    with pytest.raises(InstanceNotFoundError):
        manager.get_driver(instance_id)


async def test_destroy_instance_calls_disconnect(
    manager: InstanceManager, fake_driver: FakeDriver
) -> None:
    """destroy_instance() awaits driver.disconnect() exactly once."""
    with patch.object(manager, "_create_driver", return_value=fake_driver):
        instance_id = await manager.create_instance("local", {})
    await manager.destroy_instance(instance_id)
    fake_driver.disconnect.assert_called_once()  # type: ignore[attr-defined]


async def test_destroy_instance_raises_for_unknown(manager: InstanceManager) -> None:
    """destroy_instance() raises InstanceNotFoundError with instance_id for unknown IDs."""
    with pytest.raises(InstanceNotFoundError) as exc_info:
        await manager.destroy_instance("nonexistent")
    assert exc_info.value.instance_id == "nonexistent"


async def test_create_instance_unsupported_type_raises_value_error(
    manager: InstanceManager,
) -> None:
    """create_instance() with an unsupported driver_type raises ValueError."""
    with pytest.raises(ValueError):
        await manager.create_instance("unsupported_driver", {})
