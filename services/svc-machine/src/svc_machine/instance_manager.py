"""InstanceManager — per-session machine instance lifecycle management."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from svc_machine.driver import MachineDriver
from svc_machine.local_backend import LocalBackend


class InstanceNotFoundError(Exception):
    """Raised when an instance ID is not found in the registry."""

    def __init__(self, instance_id: str) -> None:
        self.instance_id = instance_id
        super().__init__(f"Instance {instance_id!r} not found")


class InstanceManager:
    """Manages per-session machine instance lifecycle."""

    def __init__(self) -> None:
        self._instances: dict[str, MachineDriver] = {}

    async def create_instance(self, driver_type: str, config: dict[str, Any]) -> str:
        """Create a new machine instance.

        Args:
            driver_type: Type of driver to create ('local' or 'ssh').
            config: Driver-specific configuration dict.

        Returns:
            A 12-character hex instance ID.

        Raises:
            ValueError: If driver_type is not recognised.
        """
        driver = self._create_driver(driver_type, config)
        await driver.connect()  # type: ignore[misc]
        instance_id = uuid.uuid4().hex[:12]
        self._instances[instance_id] = driver
        return instance_id

    def get_driver(self, instance_id: str) -> MachineDriver:
        """Return the driver for an existing instance.

        Args:
            instance_id: The ID returned by create_instance().

        Returns:
            The MachineDriver for that instance.

        Raises:
            InstanceNotFoundError: If instance_id is not known.
        """
        if instance_id not in self._instances:
            raise InstanceNotFoundError(instance_id)
        return self._instances[instance_id]

    async def destroy_instance(self, instance_id: str) -> None:
        """Tear down an existing instance.

        Args:
            instance_id: The ID returned by create_instance().

        Raises:
            InstanceNotFoundError: If instance_id is not known.
        """
        if instance_id not in self._instances:
            raise InstanceNotFoundError(instance_id)
        driver = self._instances.pop(instance_id)
        await driver.disconnect()  # type: ignore[misc]

    def _create_driver(self, driver_type: str, config: dict[str, Any]) -> MachineDriver:
        """Factory: instantiate the correct driver for driver_type.

        Args:
            driver_type: 'local' or 'ssh'.
            config: Driver-specific configuration.

        Returns:
            An uninitialised MachineDriver.

        Raises:
            ValueError: If driver_type is not 'local' or 'ssh'.
        """
        if driver_type == "local":
            return LocalBackend(workspace_dir=Path(config.get("workspace_dir", ".")))
        if driver_type == "ssh":
            from svc_machine.ssh_driver import SSHDriver  # lazy import

            return SSHDriver(
                host=config["host"],
                port=config.get("port", 22),
                username=config["username"],
                working_dir=config.get("working_dir", "."),
            )
        raise ValueError(f"Unknown driver type: {driver_type!r}")
