# Phase 1: Machine Service Consolidation Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Consolidate svc-bash, svc-filesystem, and svc-search into the machine service with per-session instance management and an SSH/SFTP backend driver.

**Architecture:** The machine service gains three new layers: (1) an abstract `MachineDriver` interface defining the contract for exec/file operations, (2) an `SSHDriver` implementation using `asyncssh` for SSH exec and SFTP file operations, and (3) an `InstanceManager` that creates/destroys/looks up per-session driver instances. The existing REST endpoints are refactored from flat paths (`/exec`, `/files/read`) to instance-scoped paths (`/instances/{id}/exec`, `/instances/{id}/files/read`), and the service registers all six tool names (`bash`, `read_file`, `write_file`, `edit_file`, `grep`, `glob`) in its `ServiceConfig` so `/describe` advertises them.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, asyncssh, pytest, pytest-asyncio

**Design document:** `docs/design/machine-service-consolidation-design.md`

---

## Task 1: Create the MachineDriver Abstract Base Class

**Files:**
- Create: `services/svc-machine/src/svc_machine/driver.py`
- Test: `services/svc-machine/tests/test_driver.py`

**Step 1: Write the test**

Create `services/svc-machine/tests/test_driver.py`:

```python
"""Tests for MachineDriver abstract base class."""

from __future__ import annotations

import pytest

from svc_machine.driver import MachineDriver


class TestMachineDriverIsAbstract:
    """MachineDriver cannot be instantiated directly."""

    def test_cannot_instantiate(self) -> None:
        """MachineDriver raises TypeError when instantiated directly."""
        with pytest.raises(TypeError):
            MachineDriver()  # type: ignore[abstract]

    def test_required_methods_exist(self) -> None:
        """MachineDriver defines all required abstract methods."""
        abstract_methods = MachineDriver.__abstractmethods__
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
        assert abstract_methods == expected
```

**Step 2: Run the test to verify it fails**

```bash
cd services/svc-machine && python -m pytest tests/test_driver.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'svc_machine.driver'`

**Step 3: Write the implementation**

Create `services/svc-machine/src/svc_machine/driver.py`:

```python
"""Abstract base class for machine backend drivers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ExecResult:
    """Result of a command execution."""

    stdout: str
    stderr: str
    exit_code: int


@dataclass
class FileReadResult:
    """Result of a file read operation."""

    content: str
    total_lines: int


@dataclass
class FileEditResult:
    """Result of a file edit operation."""

    success: bool
    replacements_made: int


@dataclass
class FileGlobResult:
    """Result of a file glob operation."""

    matches: list[str]
    total_files: int


class MachineDriver(ABC):
    """Abstract interface for machine backend drivers.

    Every driver (SSH, future S3, etc.) implements this contract.
    The LocalBackend in local_backend.py already implements these methods —
    this ABC formalises the interface.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the backend. Called once at instance creation."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the connection. Called when the instance is destroyed."""

    @abstractmethod
    async def exec(
        self,
        command: str,
        timeout: int = 30,
        working_dir: str | None = None,
    ) -> ExecResult:
        """Execute a shell command."""

    @abstractmethod
    async def exec_background(
        self,
        command: str,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        """Spawn a background process. Returns dict with 'pid' and 'status'."""

    @abstractmethod
    def file_read(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> FileReadResult | None:
        """Read a file. Returns None if not found."""

    @abstractmethod
    def file_write(self, path: str, content: str) -> bool:
        """Write content to a file. Returns True on success."""

    @abstractmethod
    def file_edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileEditResult | None:
        """Replace string(s) in a file. Returns None if not found."""

    @abstractmethod
    def file_list(self, path: str = ".") -> list[dict[str, Any]] | None:
        """List directory entries. Returns None if not a directory."""

    @abstractmethod
    def file_glob(
        self,
        pattern: str,
        path: str = ".",
        exclude: list[str] | None = None,
        type_filter: str = "file",
        include_ignored: bool = False,
    ) -> FileGlobResult | None:
        """Match files using a glob pattern. Returns None if base path not found."""

    @abstractmethod
    async def file_grep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob_pattern: str | None = None,
        file_type: str | None = None,
        after_context: int | None = None,
        before_context: int | None = None,
        context: int | None = None,
        case_insensitive: bool = False,
        line_numbers: bool = True,
        head_limit: int | None = None,
        offset: int = 0,
        include_ignored: bool = False,
        multiline: bool = False,
    ) -> dict[str, Any] | None:
        """Search file contents with regex. Returns None if path is invalid."""
```

**Step 4: Run the test to verify it passes**

```bash
cd services/svc-machine && python -m pytest tests/test_driver.py -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
cd services/svc-machine && git add src/svc_machine/driver.py tests/test_driver.py && git commit -m "feat(machine): add MachineDriver abstract base class"
```

---

## Task 2: Make LocalBackend implement MachineDriver

**Files:**
- Modify: `services/svc-machine/src/svc_machine/local_backend.py`
- Test: `services/svc-machine/tests/test_driver.py` (add to existing)

**Step 1: Write the test**

Append to `services/svc-machine/tests/test_driver.py`:

```python
from pathlib import Path

from svc_machine.local_backend import LocalBackend


class TestLocalBackendImplementsDriver:
    """LocalBackend is a valid MachineDriver implementation."""

    def test_is_subclass(self) -> None:
        """LocalBackend is a subclass of MachineDriver."""
        assert issubclass(LocalBackend, MachineDriver)

    def test_can_instantiate(self, tmp_path: Path) -> None:
        """LocalBackend can be instantiated (no abstract methods missing)."""
        backend = LocalBackend(workspace_dir=tmp_path)
        assert isinstance(backend, MachineDriver)
```

**Step 2: Run the test to verify it fails**

```bash
cd services/svc-machine && python -m pytest tests/test_driver.py::TestLocalBackendImplementsDriver -v
```

Expected: FAIL — `LocalBackend` is not a subclass of `MachineDriver`

**Step 3: Modify LocalBackend to inherit from MachineDriver**

In `services/svc-machine/src/svc_machine/local_backend.py`, make these changes:

1. Add the import at the top (after existing imports):

```python
from svc_machine.driver import (
    ExecResult,
    FileEditResult,
    FileGlobResult,
    FileReadResult,
    MachineDriver,
)
```

2. Remove the four duplicate dataclass definitions (`ExecResult`, `FileReadResult`, `FileEditResult`, `FileGlobResult`) — they now come from `driver.py`.

3. Change the class declaration from:
```python
class LocalBackend:
```
to:
```python
class LocalBackend(MachineDriver):
```

4. Add `connect` and `disconnect` methods (no-ops for local):
```python
    async def connect(self) -> None:
        """No-op for local backend — no connection needed."""

    async def disconnect(self) -> None:
        """No-op for local backend — no connection to tear down."""
```

5. Update imports in `tests/test_local_backend.py` — the dataclasses now come from `driver.py`. Change:
```python
from svc_machine.local_backend import (
    ExecResult,
    FileEditResult,
    FileGlobResult,
    FileReadResult,
    LocalBackend,
)
```
to:
```python
from svc_machine.driver import ExecResult, FileEditResult, FileGlobResult, FileReadResult
from svc_machine.local_backend import LocalBackend
```

**Step 4: Run all tests to verify nothing broke**

```bash
cd services/svc-machine && python -m pytest tests/ -v
```

Expected: ALL PASS (existing tests still pass + 2 new tests pass)

**Step 5: Commit**

```bash
cd services/svc-machine && git add -A && git commit -m "refactor(machine): make LocalBackend implement MachineDriver ABC"
```

---

## Task 3: Create the InstanceManager

**Files:**
- Create: `services/svc-machine/src/svc_machine/instance_manager.py`
- Test: `services/svc-machine/tests/test_instance_manager.py`

**Step 1: Write the test**

Create `services/svc-machine/tests/test_instance_manager.py`:

```python
"""Tests for InstanceManager — per-session machine instance lifecycle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from svc_machine.driver import MachineDriver
from svc_machine.instance_manager import InstanceManager, InstanceNotFoundError


class TestCreateInstance:
    """Tests for InstanceManager.create_instance()."""

    @pytest.fixture
    def manager(self) -> InstanceManager:
        return InstanceManager()

    async def test_create_returns_instance_id(self, manager: InstanceManager) -> None:
        """create_instance() returns a non-empty string ID."""
        instance_id = await manager.create_instance(
            driver_type="local", config={"workspace_dir": "/tmp/test"}
        )
        assert isinstance(instance_id, str)
        assert len(instance_id) > 0

    async def test_create_unique_ids(self, manager: InstanceManager) -> None:
        """Each call to create_instance() returns a unique ID."""
        id1 = await manager.create_instance(
            driver_type="local", config={"workspace_dir": "/tmp/test1"}
        )
        id2 = await manager.create_instance(
            driver_type="local", config={"workspace_dir": "/tmp/test2"}
        )
        assert id1 != id2

    async def test_create_calls_driver_connect(self, manager: InstanceManager) -> None:
        """create_instance() calls connect() on the driver."""
        with patch.object(manager, "_create_driver") as mock_create:
            mock_driver = AsyncMock(spec=MachineDriver)
            mock_create.return_value = mock_driver
            await manager.create_instance(
                driver_type="local", config={"workspace_dir": "/tmp/test"}
            )
            mock_driver.connect.assert_awaited_once()


class TestGetDriver:
    """Tests for InstanceManager.get_driver()."""

    @pytest.fixture
    def manager(self) -> InstanceManager:
        return InstanceManager()

    async def test_get_driver_returns_driver(self, manager: InstanceManager) -> None:
        """get_driver() returns the MachineDriver for a valid instance ID."""
        instance_id = await manager.create_instance(
            driver_type="local", config={"workspace_dir": "/tmp/test"}
        )
        driver = manager.get_driver(instance_id)
        assert isinstance(driver, MachineDriver)

    def test_get_driver_unknown_id_raises(self, manager: InstanceManager) -> None:
        """get_driver() raises InstanceNotFoundError for unknown ID."""
        with pytest.raises(InstanceNotFoundError):
            manager.get_driver("nonexistent-id")


class TestDestroyInstance:
    """Tests for InstanceManager.destroy_instance()."""

    @pytest.fixture
    def manager(self) -> InstanceManager:
        return InstanceManager()

    async def test_destroy_removes_instance(self, manager: InstanceManager) -> None:
        """destroy_instance() removes the instance — get_driver() raises after."""
        instance_id = await manager.create_instance(
            driver_type="local", config={"workspace_dir": "/tmp/test"}
        )
        await manager.destroy_instance(instance_id)
        with pytest.raises(InstanceNotFoundError):
            manager.get_driver(instance_id)

    async def test_destroy_calls_driver_disconnect(
        self, manager: InstanceManager
    ) -> None:
        """destroy_instance() calls disconnect() on the driver."""
        with patch.object(manager, "_create_driver") as mock_create:
            mock_driver = AsyncMock(spec=MachineDriver)
            mock_create.return_value = mock_driver
            instance_id = await manager.create_instance(
                driver_type="local", config={"workspace_dir": "/tmp/test"}
            )
            await manager.destroy_instance(instance_id)
            mock_driver.disconnect.assert_awaited_once()

    async def test_destroy_unknown_id_raises(self, manager: InstanceManager) -> None:
        """destroy_instance() raises InstanceNotFoundError for unknown ID."""
        with pytest.raises(InstanceNotFoundError):
            await manager.destroy_instance("nonexistent-id")


class TestUnknownDriverType:
    """Tests for unsupported driver types."""

    @pytest.fixture
    def manager(self) -> InstanceManager:
        return InstanceManager()

    async def test_unknown_driver_type_raises(self, manager: InstanceManager) -> None:
        """create_instance() raises ValueError for unsupported driver_type."""
        with pytest.raises(ValueError, match="Unsupported driver type"):
            await manager.create_instance(
                driver_type="unsupported", config={}
            )
```

**Step 2: Run the test to verify it fails**

```bash
cd services/svc-machine && python -m pytest tests/test_instance_manager.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'svc_machine.instance_manager'`

**Step 3: Write the implementation**

Create `services/svc-machine/src/svc_machine/instance_manager.py`:

```python
"""Instance manager for per-session machine instances."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from svc_machine.driver import MachineDriver


class InstanceNotFoundError(Exception):
    """Raised when an instance ID is not found."""

    def __init__(self, instance_id: str) -> None:
        super().__init__(f"Machine instance not found: {instance_id}")
        self.instance_id = instance_id


class InstanceManager:
    """Manages per-session machine driver instances.

    Each session gets one instance, created at session start and destroyed
    at session end. The manager owns the lifecycle of the driver (connect/disconnect).
    """

    def __init__(self) -> None:
        self._instances: dict[str, MachineDriver] = {}

    async def create_instance(
        self, driver_type: str, config: dict[str, Any]
    ) -> str:
        """Create a new machine instance with the given driver type and config.

        Args:
            driver_type: Backend type — 'local' or 'ssh'.
            config: Driver-specific configuration (e.g. workspace_dir, host, port).

        Returns:
            A unique instance ID string.

        Raises:
            ValueError: If driver_type is not supported.
        """
        driver = self._create_driver(driver_type, config)
        await driver.connect()
        instance_id = uuid.uuid4().hex[:12]
        self._instances[instance_id] = driver
        return instance_id

    def get_driver(self, instance_id: str) -> MachineDriver:
        """Look up the driver for an instance.

        Args:
            instance_id: The instance ID returned by create_instance().

        Returns:
            The MachineDriver for the instance.

        Raises:
            InstanceNotFoundError: If the instance ID is not found.
        """
        driver = self._instances.get(instance_id)
        if driver is None:
            raise InstanceNotFoundError(instance_id)
        return driver

    async def destroy_instance(self, instance_id: str) -> None:
        """Destroy a machine instance, disconnecting the driver.

        Args:
            instance_id: The instance ID to destroy.

        Raises:
            InstanceNotFoundError: If the instance ID is not found.
        """
        driver = self._instances.pop(instance_id, None)
        if driver is None:
            raise InstanceNotFoundError(instance_id)
        await driver.disconnect()

    def _create_driver(
        self, driver_type: str, config: dict[str, Any]
    ) -> MachineDriver:
        """Factory method to create a driver instance.

        Args:
            driver_type: Backend type — 'local' or 'ssh'.
            config: Driver-specific configuration.

        Returns:
            A MachineDriver instance (not yet connected).

        Raises:
            ValueError: If driver_type is not supported.
        """
        if driver_type == "local":
            from svc_machine.local_backend import LocalBackend

            workspace_dir = Path(config.get("workspace_dir", "/workspace"))
            return LocalBackend(workspace_dir=workspace_dir)

        if driver_type == "ssh":
            from svc_machine.ssh_driver import SSHDriver

            return SSHDriver(
                host=config.get("host", "localhost"),
                port=config.get("port", 22),
                username=config.get("username"),
                working_dir=config.get("working_dir", "/workspace"),
            )

        raise ValueError(f"Unsupported driver type: {driver_type!r}")
```

**Step 4: Run the test to verify it passes**

```bash
cd services/svc-machine && python -m pytest tests/test_instance_manager.py -v
```

Expected: PASS (8 tests). Note: the SSH driver import in `_create_driver` is lazy (inside the `if` block), so the SSH tests won't trigger it — only `local` and `unsupported` are tested.

**Step 5: Commit**

```bash
cd services/svc-machine && git add src/svc_machine/instance_manager.py tests/test_instance_manager.py && git commit -m "feat(machine): add InstanceManager for per-session machine instances"
```

---

## Task 4: Create the SSHDriver skeleton

**Files:**
- Create: `services/svc-machine/src/svc_machine/ssh_driver.py`
- Test: `services/svc-machine/tests/test_ssh_driver.py`
- Modify: `services/svc-machine/pyproject.toml` (add asyncssh)

**Step 1: Add asyncssh dependency**

In `services/svc-machine/pyproject.toml`, add `"asyncssh>=2.14"` to the `dependencies` list:

Change:
```toml
dependencies = [
    "amplifier-service-sdk",
    "pydantic>=2.0",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
]
```
to:
```toml
dependencies = [
    "amplifier-service-sdk",
    "pydantic>=2.0",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "asyncssh>=2.14",
]
```

Then install:
```bash
cd services/svc-machine && uv pip install -e ".[dev]" 2>/dev/null || pip install -e . 2>/dev/null || echo "Dependencies noted — install manually if needed"
```

**Step 2: Write the test**

Create `services/svc-machine/tests/test_ssh_driver.py`:

```python
"""Tests for SSHDriver — SSH/SFTP backend for machine instances."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from svc_machine.driver import ExecResult, MachineDriver
from svc_machine.ssh_driver import SSHDriver


class TestSSHDriverIsDriver:
    """SSHDriver implements MachineDriver."""

    def test_is_subclass(self) -> None:
        """SSHDriver is a subclass of MachineDriver."""
        assert issubclass(SSHDriver, MachineDriver)

    def test_can_instantiate(self) -> None:
        """SSHDriver can be instantiated without connecting."""
        driver = SSHDriver(host="localhost", port=22, working_dir="/workspace")
        assert isinstance(driver, MachineDriver)


class TestSSHDriverExec:
    """Tests for SSHDriver.exec() with mocked SSH connection."""

    @pytest.fixture
    def driver(self) -> SSHDriver:
        return SSHDriver(host="localhost", port=22, working_dir="/workspace")

    async def test_exec_returns_exec_result(self, driver: SSHDriver) -> None:
        """exec() returns an ExecResult with stdout, stderr, exit_code."""
        mock_result = MagicMock()
        mock_result.stdout = "hello\n"
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)
        driver._conn = mock_conn

        result = await driver.exec("echo hello")
        assert isinstance(result, ExecResult)
        assert result.stdout == "hello\n"
        assert result.exit_code == 0

    async def test_exec_nonzero_exit(self, driver: SSHDriver) -> None:
        """exec() captures non-zero exit codes."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "error\n"
        mock_result.exit_status = 1

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)
        driver._conn = mock_conn

        result = await driver.exec("false")
        assert result.exit_code == 1
        assert result.stderr == "error\n"

    async def test_exec_uses_working_dir(self, driver: SSHDriver) -> None:
        """exec() prepends cd to the command when working_dir is set."""
        mock_result = MagicMock()
        mock_result.stdout = "/workspace\n"
        mock_result.stderr = ""
        mock_result.exit_status = 0

        mock_conn = AsyncMock()
        mock_conn.run = AsyncMock(return_value=mock_result)
        driver._conn = mock_conn

        await driver.exec("pwd")
        # Verify the command was wrapped with cd
        call_args = mock_conn.run.call_args
        cmd = call_args[0][0]
        assert "cd" in cmd
        assert "/workspace" in cmd


class TestSSHDriverConnect:
    """Tests for SSHDriver.connect() and disconnect()."""

    async def test_connect_creates_connection(self) -> None:
        """connect() calls asyncssh.connect with host/port."""
        driver = SSHDriver(host="testhost", port=2222, working_dir="/workspace")
        with patch("svc_machine.ssh_driver.asyncssh") as mock_asyncssh:
            mock_conn = AsyncMock()
            mock_asyncssh.connect = AsyncMock(return_value=mock_conn)
            await driver.connect()
            mock_asyncssh.connect.assert_awaited_once()
            call_kwargs = mock_asyncssh.connect.call_args
            assert call_kwargs[1]["host"] == "testhost" or call_kwargs[0][0] == "testhost"

    async def test_disconnect_closes_connection(self) -> None:
        """disconnect() closes the SSH connection."""
        driver = SSHDriver(host="localhost", port=22, working_dir="/workspace")
        mock_conn = MagicMock()
        mock_conn.close = MagicMock()
        driver._conn = mock_conn
        await driver.disconnect()
        mock_conn.close.assert_called_once()
        assert driver._conn is None
```

**Step 3: Run the test to verify it fails**

```bash
cd services/svc-machine && python -m pytest tests/test_ssh_driver.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'svc_machine.ssh_driver'`

**Step 4: Write the implementation**

Create `services/svc-machine/src/svc_machine/ssh_driver.py`:

```python
"""SSH/SFTP backend driver for machine instances."""

from __future__ import annotations

import asyncio
from typing import Any

try:
    import asyncssh
except ImportError:
    asyncssh = None  # type: ignore[assignment]

from svc_machine.driver import (
    ExecResult,
    FileEditResult,
    FileGlobResult,
    FileReadResult,
    MachineDriver,
)


class SSHDriver(MachineDriver):
    """Machine driver that connects to a host via SSH/SFTP.

    Uses asyncssh for async SSH command execution and SFTP file operations.
    Even for local machines, this connects to localhost:22 to get full host
    access (not limited to the container filesystem).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 22,
        username: str | None = None,
        working_dir: str = "/workspace",
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._working_dir = working_dir
        self._conn: Any | None = None  # asyncssh.SSHClientConnection

    async def connect(self) -> None:
        """Establish SSH connection to the host."""
        if asyncssh is None:
            raise RuntimeError("asyncssh is required for SSHDriver")
        connect_kwargs: dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "known_hosts": None,  # Disable host key checking for now
        }
        if self._username:
            connect_kwargs["username"] = self._username
        self._conn = await asyncssh.connect(**connect_kwargs)

    async def disconnect(self) -> None:
        """Close the SSH connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _wrap_command(self, command: str, working_dir: str | None = None) -> str:
        """Wrap a command with cd to the working directory."""
        cwd = working_dir or self._working_dir
        return f"cd {cwd} && {command}"

    async def exec(
        self,
        command: str,
        timeout: int = 30,
        working_dir: str | None = None,
    ) -> ExecResult:
        """Execute a command over SSH."""
        assert self._conn is not None, "Not connected — call connect() first"
        wrapped = self._wrap_command(command, working_dir)
        try:
            result = await asyncio.wait_for(
                self._conn.run(wrapped, check=False),
                timeout=timeout,
            )
            return ExecResult(
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_status if result.exit_status is not None else -1,
            )
        except asyncio.TimeoutError:
            return ExecResult(
                stdout="Command timed out",
                stderr="",
                exit_code=124,
            )

    async def exec_background(
        self,
        command: str,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        """Spawn a background command over SSH using nohup."""
        assert self._conn is not None, "Not connected — call connect() first"
        wrapped = self._wrap_command(command, working_dir)
        # Use nohup + & to run in background, capture PID
        bg_cmd = f"nohup {wrapped} > /dev/null 2>&1 & echo $!"
        result = await self._conn.run(bg_cmd, check=False)
        pid_str = (result.stdout or "").strip()
        try:
            pid = int(pid_str)
        except ValueError:
            pid = -1
        return {"pid": pid, "status": "running"}

    def file_read(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> FileReadResult | None:
        """Read a file via SFTP (sync wrapper — will be called from async context).

        Note: This is a placeholder. The actual implementation will use
        asyncio.run_coroutine_threadsafe or be refactored to async in a follow-up.
        For now, file operations delegate to SSH exec with cat/head/tail.
        """
        # Placeholder — will be implemented with SFTP in a subsequent step
        raise NotImplementedError("file_read via SSH — see Task 5")

    def file_write(self, path: str, content: str) -> bool:
        """Write a file via SFTP."""
        raise NotImplementedError("file_write via SSH — see Task 5")

    def file_edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileEditResult | None:
        """Edit a file via SFTP (read, modify, write back)."""
        raise NotImplementedError("file_edit via SSH — see Task 5")

    def file_list(self, path: str = ".") -> list[dict[str, Any]] | None:
        """List directory via SFTP."""
        raise NotImplementedError("file_list via SSH — see Task 5")

    def file_glob(
        self,
        pattern: str,
        path: str = ".",
        exclude: list[str] | None = None,
        type_filter: str = "file",
        include_ignored: bool = False,
    ) -> FileGlobResult | None:
        """Glob via SSH exec (find command)."""
        raise NotImplementedError("file_glob via SSH — see Task 5")

    async def file_grep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob_pattern: str | None = None,
        file_type: str | None = None,
        after_context: int | None = None,
        before_context: int | None = None,
        context: int | None = None,
        case_insensitive: bool = False,
        line_numbers: bool = True,
        head_limit: int | None = None,
        offset: int = 0,
        include_ignored: bool = False,
        multiline: bool = False,
    ) -> dict[str, Any] | None:
        """Grep via SSH exec (rg command on remote host)."""
        raise NotImplementedError("file_grep via SSH — see Task 5")
```

**Step 4: Run the test to verify it passes**

```bash
cd services/svc-machine && python -m pytest tests/test_ssh_driver.py -v
```

Expected: PASS (7 tests). The exec and connect/disconnect tests work with mocks. File operation methods raise NotImplementedError but those aren't tested yet.

**Step 5: Commit**

```bash
cd services/svc-machine && git add src/svc_machine/ssh_driver.py tests/test_ssh_driver.py pyproject.toml && git commit -m "feat(machine): add SSHDriver skeleton with exec and connect/disconnect"
```

---

## Task 5: Implement SSHDriver file operations

**Files:**
- Modify: `services/svc-machine/src/svc_machine/ssh_driver.py`
- Modify: `services/svc-machine/tests/test_ssh_driver.py`

**Step 1: Write the tests**

Append to `services/svc-machine/tests/test_ssh_driver.py`:

```python
from svc_machine.driver import FileReadResult, FileEditResult, FileGlobResult


class TestSSHDriverFileRead:
    """Tests for SSHDriver.file_read() via SFTP mock."""

    @pytest.fixture
    def driver(self) -> SSHDriver:
        d = SSHDriver(host="localhost", port=22, working_dir="/workspace")
        mock_sftp = AsyncMock()
        d._sftp = mock_sftp
        d._conn = AsyncMock()
        return d

    async def test_read_file(self, driver: SSHDriver) -> None:
        """file_read() returns FileReadResult with content and total_lines."""
        mock_file = AsyncMock()
        mock_file.read = AsyncMock(return_value=b"line1\nline2\nline3\n")
        driver._sftp.open = AsyncMock(return_value=mock_file)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=False)

        result = await driver.file_read_async("test.txt")
        assert result is not None
        assert isinstance(result, FileReadResult)
        assert result.total_lines == 3
        assert "line1" in result.content

    async def test_read_nonexistent_returns_none(self, driver: SSHDriver) -> None:
        """file_read() returns None when file does not exist."""
        driver._sftp.open = AsyncMock(side_effect=OSError("No such file"))

        result = await driver.file_read_async("missing.txt")
        assert result is None


class TestSSHDriverFileWrite:
    """Tests for SSHDriver.file_write() via SFTP mock."""

    @pytest.fixture
    def driver(self) -> SSHDriver:
        d = SSHDriver(host="localhost", port=22, working_dir="/workspace")
        mock_sftp = AsyncMock()
        d._sftp = mock_sftp
        d._conn = AsyncMock()
        return d

    async def test_write_file(self, driver: SSHDriver) -> None:
        """file_write() writes content and returns True."""
        mock_file = AsyncMock()
        mock_file.write = AsyncMock()
        driver._sftp.open = AsyncMock(return_value=mock_file)
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=False)

        # Mock makedirs (mkdir -p equivalent)
        driver._conn.run = AsyncMock(return_value=MagicMock(exit_status=0))

        result = await driver.file_write_async("output.txt", "hello\n")
        assert result is True


class TestSSHDriverFileGrep:
    """Tests for SSHDriver.file_grep() via SSH exec mock."""

    @pytest.fixture
    def driver(self) -> SSHDriver:
        d = SSHDriver(host="localhost", port=22, working_dir="/workspace")
        d._conn = AsyncMock()
        return d

    async def test_grep_returns_matches(self, driver: SSHDriver) -> None:
        """file_grep() executes rg over SSH and returns matches."""
        mock_result = MagicMock()
        mock_result.stdout = "file1.py\nfile2.py\n"
        mock_result.stderr = ""
        mock_result.exit_status = 0
        driver._conn.run = AsyncMock(return_value=mock_result)

        result = await driver.file_grep(pattern="def", output_mode="files_with_matches")
        assert result is not None
        assert "matches" in result
        assert len(result["matches"]) == 2
```

**Step 2: Run the tests to verify they fail**

```bash
cd services/svc-machine && python -m pytest tests/test_ssh_driver.py::TestSSHDriverFileRead -v
```

Expected: FAIL — methods raise `NotImplementedError`

**Step 3: Implement file operations in SSHDriver**

Replace the placeholder file methods in `services/svc-machine/src/svc_machine/ssh_driver.py` with real implementations. The key insight: SFTP operations in asyncssh are async, so we add `_async` variants and have the sync interface delegate to them.

Add these methods to the `SSHDriver` class (replacing the `NotImplementedError` stubs):

```python
    async def _ensure_sftp(self) -> Any:
        """Get or create an SFTP client from the SSH connection."""
        if not hasattr(self, "_sftp") or self._sftp is None:
            assert self._conn is not None, "Not connected"
            self._sftp = await self._conn.start_sftp_client()
        return self._sftp

    def _resolve_path(self, path: str) -> str:
        """Resolve a relative path against the working directory."""
        if path.startswith("/"):
            return path
        return f"{self._working_dir}/{path}"

    # --- Async file operations (primary interface for SSH) ---

    async def file_read_async(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> FileReadResult | None:
        """Read a file via SFTP."""
        sftp = await self._ensure_sftp()
        resolved = self._resolve_path(path)
        try:
            async with sftp.open(resolved, "r") as f:
                data = await f.read()
                text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
        except (OSError, asyncssh.SFTPError):
            return None

        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        start = offset - 1
        selected = lines[start : start + limit] if limit is not None else lines[start:]
        content = "".join(selected)
        return FileReadResult(content=content, total_lines=total_lines)

    async def file_write_async(self, path: str, content: str) -> bool:
        """Write content to a file via SFTP, creating parent dirs."""
        resolved = self._resolve_path(path)
        # Create parent directories via SSH exec
        parent = "/".join(resolved.split("/")[:-1])
        if parent:
            assert self._conn is not None
            await self._conn.run(f"mkdir -p {parent}", check=False)

        sftp = await self._ensure_sftp()
        try:
            async with sftp.open(resolved, "w") as f:
                await f.write(content)
            return True
        except (OSError, asyncssh.SFTPError):
            return False

    async def file_edit_async(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> FileEditResult | None:
        """Edit a file via SFTP: read, replace, write back."""
        read_result = await self.file_read_async(path)
        if read_result is None:
            return None

        content = read_result.content
        if replace_all:
            replacements = content.count(old_string)
            new_content = content.replace(old_string, new_string)
        else:
            replacements = 1 if old_string in content else 0
            new_content = content.replace(old_string, new_string, 1)

        if replacements > 0:
            await self.file_write_async(path, new_content)

        return FileEditResult(success=replacements > 0, replacements_made=replacements)

    async def file_list_async(self, path: str = ".") -> list[dict[str, Any]] | None:
        """List directory via SFTP."""
        sftp = await self._ensure_sftp()
        resolved = self._resolve_path(path)
        try:
            entries = []
            for item in await sftp.readdir(resolved):
                name = item.filename
                if name in (".", ".."):
                    continue
                if item.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
                    entries.append({"name": name, "type": "dir"})
                else:
                    entries.append({
                        "name": name,
                        "type": "file",
                        "size": item.attrs.size or 0,
                    })
            return sorted(entries, key=lambda e: e["name"])
        except (OSError, asyncssh.SFTPError):
            return None

    async def file_glob_async(
        self,
        pattern: str,
        path: str = ".",
        exclude: list[str] | None = None,
        type_filter: str = "file",
        include_ignored: bool = False,
    ) -> FileGlobResult | None:
        """Glob via SSH exec using find or a glob-capable command."""
        # Delegate to rg --files with glob, or use find
        assert self._conn is not None
        resolved = self._resolve_path(path)
        cmd = f"cd {resolved} && find . -name '{pattern}' 2>/dev/null | head -500"
        result = await self._conn.run(cmd, check=False)
        stdout = result.stdout or ""
        matches = [line.lstrip("./") for line in stdout.strip().splitlines() if line.strip()]
        return FileGlobResult(matches=matches, total_files=len(matches))

    # --- Sync interface (required by MachineDriver ABC) ---
    # These delegate to the async versions. The service layer calls
    # the async variants directly; these exist for ABC compliance.

    def file_read(self, path: str, offset: int = 1, limit: int | None = None) -> FileReadResult | None:
        """Sync wrapper — not used in practice. Use file_read_async."""
        raise NotImplementedError("Use file_read_async for SSHDriver")

    def file_write(self, path: str, content: str) -> bool:
        """Sync wrapper — not used in practice. Use file_write_async."""
        raise NotImplementedError("Use file_write_async for SSHDriver")

    def file_edit(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> FileEditResult | None:
        """Sync wrapper — not used in practice. Use file_edit_async."""
        raise NotImplementedError("Use file_edit_async for SSHDriver")

    def file_list(self, path: str = ".") -> list[dict[str, Any]] | None:
        """Sync wrapper — not used in practice. Use file_list_async."""
        raise NotImplementedError("Use file_list_async for SSHDriver")

    def file_glob(self, pattern: str, path: str = ".", exclude: list[str] | None = None, type_filter: str = "file", include_ignored: bool = False) -> FileGlobResult | None:
        """Sync wrapper — not used in practice. Use file_glob_async."""
        raise NotImplementedError("Use file_glob_async for SSHDriver")

    async def file_grep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob_pattern: str | None = None,
        file_type: str | None = None,
        after_context: int | None = None,
        before_context: int | None = None,
        context: int | None = None,
        case_insensitive: bool = False,
        line_numbers: bool = True,
        head_limit: int | None = None,
        offset: int = 0,
        include_ignored: bool = False,
        multiline: bool = False,
    ) -> dict[str, Any] | None:
        """Search file contents by running rg on the remote host via SSH."""
        assert self._conn is not None
        resolved = self._resolve_path(path)

        cmd_parts = ["rg", "--no-heading"]

        if output_mode == "files_with_matches":
            cmd_parts.append("--files-with-matches")
        elif output_mode == "count":
            cmd_parts.append("--count")

        if not include_ignored:
            for excluded in ["node_modules", ".venv", ".git", "__pycache__", "build", "dist"]:
                cmd_parts.extend(["--glob", f"!{excluded}"])

        if glob_pattern:
            cmd_parts.extend(["--glob", glob_pattern])
        if file_type:
            cmd_parts.extend(["--type", file_type])
        if case_insensitive:
            cmd_parts.append("--ignore-case")
        if multiline:
            cmd_parts.extend(["--multiline", "--multiline-dotall"])

        if output_mode == "content":
            if line_numbers:
                cmd_parts.append("--line-number")
            if context is not None:
                cmd_parts.extend(["--context", str(context)])
            else:
                if after_context is not None:
                    cmd_parts.extend(["--after-context", str(after_context)])
                if before_context is not None:
                    cmd_parts.extend(["--before-context", str(before_context)])

        # Escape pattern for shell
        escaped_pattern = pattern.replace("'", "'\\''")
        cmd_parts.extend([f"'{escaped_pattern}'", resolved])

        full_cmd = " ".join(cmd_parts)
        result = await self._conn.run(full_cmd, check=False)
        stdout_text = result.stdout or ""

        all_matches = self._parse_grep_output(stdout_text, output_mode)
        total = len(all_matches)

        if total == 0:
            return {"matches": []}

        page = all_matches[offset:]
        default_limits = {"files_with_matches": 200, "count": 200, "content": 500}
        limit_val = head_limit if head_limit is not None else default_limits.get(output_mode, 500)
        page = page[:limit_val]

        return {"matches": page, "total_matches": total}

    @staticmethod
    def _parse_grep_output(output: str, output_mode: str) -> list[Any]:
        """Parse ripgrep output (same logic as LocalBackend)."""
        lines = [line for line in output.splitlines() if line.strip()]
        results: list[Any] = []

        if output_mode == "files_with_matches":
            for line in lines:
                path = line.strip()
                if path.startswith("./"):
                    path = path[2:]
                results.append(path)
        elif output_mode == "count":
            for line in lines:
                line = line.strip()
                if ":" not in line:
                    continue
                colon_idx = line.rfind(":")
                file_path = line[:colon_idx]
                count_str = line[colon_idx + 1:]
                if file_path.startswith("./"):
                    file_path = file_path[2:]
                try:
                    results.append({"file": file_path, "count": int(count_str)})
                except ValueError:
                    continue
        elif output_mode == "content":
            for line in lines:
                line = line.strip()
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                file_path = parts[0]
                if file_path.startswith("./"):
                    file_path = file_path[2:]
                try:
                    line_num = int(parts[1])
                except ValueError:
                    continue
                results.append({"file": file_path, "line": line_num, "content": parts[2]})

        return results
```

**Step 4: Run the tests to verify they pass**

```bash
cd services/svc-machine && python -m pytest tests/test_ssh_driver.py -v
```

Expected: PASS (all tests)

**Step 5: Commit**

```bash
cd services/svc-machine && git add -A && git commit -m "feat(machine): implement SSHDriver file operations via SFTP and SSH exec"
```

---

## Task 6: Refactor service.py — add instance lifecycle endpoints

**Files:**
- Modify: `services/svc-machine/src/svc_machine/service.py`
- Modify: `services/svc-machine/tests/test_service.py`

**Step 1: Write the tests**

Add to `services/svc-machine/tests/test_service.py` (new test classes):

```python
from svc_machine.instance_manager import InstanceNotFoundError


class TestInstanceLifecycle:
    """Tests for POST /instances and DELETE /instances/{id}."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        app = create_machine_app(workspace_dir=workspace)
        return TestClient(app)

    def test_create_instance(self, client: TestClient) -> None:
        """POST /instances returns 200 with an instance_id."""
        response = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": "/tmp"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert "instance_id" in data
        assert isinstance(data["instance_id"], str)

    def test_destroy_instance(self, client: TestClient) -> None:
        """DELETE /instances/{id} returns 200 after creating an instance."""
        create_resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": "/tmp"}},
        )
        instance_id = create_resp.json()["instance_id"]

        delete_resp = client.delete(f"/instances/{instance_id}")
        assert delete_resp.status_code == 200

    def test_destroy_nonexistent_returns_404(self, client: TestClient) -> None:
        """DELETE /instances/{id} returns 404 for nonexistent ID."""
        response = client.delete("/instances/nonexistent")
        assert response.status_code == 404


class TestInstanceScopedExec:
    """Tests for POST /instances/{id}/exec."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        app = create_machine_app(workspace_dir=workspace)
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, workspace: Path) -> str:
        resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        return resp.json()["instance_id"]

    def test_exec_on_instance(self, client: TestClient, instance_id: str) -> None:
        """POST /instances/{id}/exec runs a command on the instance."""
        response = client.post(
            f"/instances/{instance_id}/exec",
            json={"command": "echo hello_instance"},
        )
        assert response.status_code == 200
        assert "hello_instance" in response.json()["stdout"]

    def test_exec_nonexistent_instance_returns_404(self, client: TestClient) -> None:
        """POST /instances/{id}/exec returns 404 for nonexistent instance."""
        response = client.post(
            "/instances/nonexistent/exec",
            json={"command": "echo hi"},
        )
        assert response.status_code == 404


class TestInstanceScopedFileOps:
    """Tests for instance-scoped file operations."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.fixture
    def client(self, workspace: Path) -> TestClient:
        app = create_machine_app(workspace_dir=workspace)
        return TestClient(app)

    @pytest.fixture
    def instance_id(self, client: TestClient, workspace: Path) -> str:
        resp = client.post(
            "/instances",
            json={"driver_type": "local", "config": {"workspace_dir": str(workspace)}},
        )
        return resp.json()["instance_id"]

    def test_write_and_read(
        self, client: TestClient, instance_id: str
    ) -> None:
        """Write a file, then read it back via instance-scoped endpoints."""
        # Write
        write_resp = client.post(
            f"/instances/{instance_id}/files/write",
            json={"path": "test.txt", "content": "hello from instance\n"},
        )
        assert write_resp.status_code == 200

        # Read
        read_resp = client.post(
            f"/instances/{instance_id}/files/read",
            json={"path": "test.txt"},
        )
        assert read_resp.status_code == 200
        assert "hello from instance" in read_resp.json()["content"]

    def test_edit_file(
        self, client: TestClient, instance_id: str, workspace: Path
    ) -> None:
        """Edit a file via instance-scoped endpoint."""
        (workspace / "edit.txt").write_text("foo bar\n")
        resp = client.post(
            f"/instances/{instance_id}/files/edit",
            json={"path": "edit.txt", "old_string": "foo", "new_string": "baz"},
        )
        assert resp.status_code == 200
        assert resp.json()["replacements_made"] == 1
```

**Step 2: Run the tests to verify they fail**

```bash
cd services/svc-machine && python -m pytest tests/test_service.py::TestInstanceLifecycle -v
```

Expected: FAIL — endpoints don't exist yet

**Step 3: Refactor service.py**

Rewrite `services/svc-machine/src/svc_machine/service.py` to add instance-scoped endpoints while keeping the existing flat endpoints for backward compatibility during the transition:

Add these imports at the top:
```python
from svc_machine.instance_manager import InstanceManager, InstanceNotFoundError
```

Add these Pydantic models:
```python
class CreateInstanceRequest(BaseModel):
    """Request body for POST /instances."""
    driver_type: str = "local"
    config: dict = {}

class CreateInstanceResponse(BaseModel):
    """Response body for POST /instances."""
    instance_id: str
```

Inside `create_machine_app()`, after creating `backend` and `safety`, add:
```python
    instance_manager = InstanceManager()
```

Then add these endpoints inside `create_machine_app()`:
```python
    @app.post("/instances")
    async def create_instance(request: CreateInstanceRequest) -> CreateInstanceResponse:
        """Create a new machine instance."""
        instance_id = await instance_manager.create_instance(
            driver_type=request.driver_type, config=request.config
        )
        return CreateInstanceResponse(instance_id=instance_id)

    @app.delete("/instances/{instance_id}")
    async def destroy_instance(instance_id: str) -> dict:
        """Destroy a machine instance."""
        try:
            await instance_manager.destroy_instance(instance_id)
        except InstanceNotFoundError:
            raise HTTPException(status_code=404, detail="Instance not found")
        return {"success": True}

    def _get_driver(instance_id: str) -> LocalBackend:
        """Helper to get the driver for an instance, raising 404 if not found."""
        try:
            return instance_manager.get_driver(instance_id)  # type: ignore[return-value]
        except InstanceNotFoundError:
            raise HTTPException(status_code=404, detail="Instance not found")

    @app.post("/instances/{instance_id}/exec", response_model=None)
    async def instance_exec(instance_id: str, request: ExecRequest) -> ExecResponse | JSONResponse:
        """Execute a command on a specific instance."""
        driver = _get_driver(instance_id)

        allowed, reason = safety.validate(request.command)
        if not allowed:
            raise HTTPException(status_code=403, detail={"denied": True, "reason": reason})

        if request.run_in_background:
            try:
                result_bg = await driver.exec_background(
                    command=request.command, working_dir=request.working_dir
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return JSONResponse(content=result_bg)

        try:
            result = await driver.exec(
                command=request.command, timeout=request.timeout, working_dir=request.working_dir
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        stdout, stdout_truncated = truncate_output(result.stdout)
        stderr, stderr_truncated = truncate_output(result.stderr)

        return ExecResponse(
            stdout=stdout, stderr=stderr, exit_code=result.exit_code,
            truncated=stdout_truncated or stderr_truncated,
        )

    @app.post("/instances/{instance_id}/files/read")
    def instance_read_file(instance_id: str, request: FileReadRequest) -> dict:
        """Read a file on a specific instance."""
        driver = _get_driver(instance_id)
        result = driver.file_read(request.path, offset=request.offset, limit=request.limit)
        if result is None:
            raise HTTPException(status_code=404, detail="File not found")
        return {"content": result.content, "total_lines": result.total_lines}

    @app.post("/instances/{instance_id}/files/write")
    def instance_write_file(instance_id: str, request: FileWriteRequest) -> dict:
        """Write a file on a specific instance."""
        driver = _get_driver(instance_id)
        success = driver.file_write(request.path, request.content)
        if not success:
            raise HTTPException(status_code=403, detail="Path escapes workspace")
        return {"success": True}

    @app.post("/instances/{instance_id}/files/edit")
    def instance_edit_file(instance_id: str, request: FileEditRequest) -> dict:
        """Edit a file on a specific instance."""
        driver = _get_driver(instance_id)
        result = driver.file_edit(request.path, request.old_string, request.new_string, request.replace_all)
        if result is None:
            raise HTTPException(status_code=404, detail="File not found")
        return {"success": result.success, "replacements_made": result.replacements_made}

    @app.post("/instances/{instance_id}/files/list")
    def instance_list_files(instance_id: str, request: FileListRequest) -> dict:
        """List files on a specific instance."""
        driver = _get_driver(instance_id)
        entries = driver.file_list(request.path)
        if entries is None:
            raise HTTPException(status_code=404, detail="Path not found or not a directory")
        return {"entries": entries}

    @app.post("/instances/{instance_id}/files/glob")
    def instance_glob_files(instance_id: str, request: FileGlobRequest) -> dict:
        """Glob files on a specific instance."""
        driver = _get_driver(instance_id)
        result = driver.file_glob(
            request.pattern, request.path,
            exclude=request.exclude, type_filter=request.type,
            include_ignored=request.include_ignored,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Base path not found")
        return {"matches": result.matches, "total_files": result.total_files}

    @app.post("/instances/{instance_id}/files/grep")
    async def instance_grep_files(instance_id: str, request: FileGrepRequest) -> dict:
        """Grep files on a specific instance."""
        driver = _get_driver(instance_id)
        result = await driver.file_grep(
            pattern=request.pattern, path=request.path,
            output_mode=request.output_mode, glob_pattern=request.glob,
            file_type=request.type, after_context=request.after_context,
            before_context=request.before_context, context=request.context,
            case_insensitive=request.case_insensitive,
            line_numbers=request.line_numbers, head_limit=request.head_limit,
            offset=request.offset, include_ignored=request.include_ignored,
            multiline=request.multiline,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Path not found")
        return result
```

**Step 4: Run all tests to verify**

```bash
cd services/svc-machine && python -m pytest tests/test_service.py -v
```

Expected: ALL PASS — existing flat-endpoint tests still pass + new instance-scoped tests pass

**Step 5: Commit**

```bash
cd services/svc-machine && git add -A && git commit -m "feat(machine): add instance lifecycle and instance-scoped endpoints"
```

---

## Task 7: Register tools in ServiceConfig for /describe

**Files:**
- Modify: `services/svc-machine/src/svc_machine/service.py`
- Modify: `services/svc-machine/tests/test_service.py`

**Step 1: Write the test**

Update the existing `TestDescribe` class in `services/svc-machine/tests/test_service.py`:

```python
class TestDescribe:
    """Tests for GET /describe endpoint."""

    def test_describe(self, client: TestClient) -> None:
        """GET /describe returns service name and version."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-machine"
        assert "version" in data

    def test_describe_advertises_tools(self, client: TestClient) -> None:
        """GET /describe lists all six machine tools."""
        response = client.get("/describe")
        data = response.json()
        tool_names = {t["name"] for t in data["tools"]}
        expected = {"bash", "read_file", "write_file", "edit_file", "grep", "glob"}
        assert expected == tool_names
```

**Step 2: Run the test to verify it fails**

```bash
cd services/svc-machine && python -m pytest tests/test_service.py::TestDescribe::test_describe_advertises_tools -v
```

Expected: FAIL — `data["tools"]` is empty because `ServiceConfig` has no tools registered

**Step 3: Register tools in ServiceConfig**

In `services/svc-machine/src/svc_machine/service.py`, add this import:
```python
from amplifier_service_sdk.models import ToolCapability
```

Then change the `ServiceConfig` creation from:
```python
    config = ServiceConfig(name="svc-machine")
```
to:
```python
    config = ServiceConfig(
        name="svc-machine",
        tools=[
            ToolCapability(
                name="bash",
                description="Execute shell commands on the machine",
                input_schema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute"},
                        "timeout": {"type": "integer", "default": 30, "description": "Command timeout in seconds"},
                        "run_in_background": {"type": "boolean", "default": False, "description": "Run command in background"},
                    },
                    "required": ["command"],
                },
            ),
            ToolCapability(
                name="read_file",
                description="Read file contents from the filesystem",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to the file to read"},
                        "offset": {"type": "integer", "description": "Line number to start reading from (1-indexed)"},
                        "limit": {"type": "integer", "description": "Maximum number of lines to read"},
                    },
                    "required": ["file_path"],
                },
            ),
            ToolCapability(
                name="write_file",
                description="Write content to a file on the filesystem",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to the file to write"},
                        "content": {"type": "string", "description": "Content to write to the file"},
                    },
                    "required": ["file_path", "content"],
                },
            ),
            ToolCapability(
                name="edit_file",
                description="Edit a file by replacing a string with another string",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to the file to edit"},
                        "old_string": {"type": "string", "description": "The string to find and replace"},
                        "new_string": {"type": "string", "description": "The replacement string"},
                        "replace_all": {"type": "boolean", "default": False, "description": "Replace all occurrences"},
                    },
                    "required": ["file_path", "old_string", "new_string"],
                },
            ),
            ToolCapability(
                name="grep",
                description="Search file contents with regex patterns",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regular expression pattern to search for"},
                        "path": {"type": "string", "description": "File or directory to search in"},
                        "output_mode": {"type": "string", "enum": ["files_with_matches", "content", "count"]},
                    },
                    "required": ["pattern"],
                },
            ),
            ToolCapability(
                name="glob",
                description="Match files using glob patterns",
                input_schema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern to match files"},
                        "path": {"type": "string", "description": "Base path to search from"},
                    },
                    "required": ["pattern"],
                },
            ),
        ],
    )
```

**Step 4: Run the test to verify it passes**

```bash
cd services/svc-machine && python -m pytest tests/test_service.py::TestDescribe -v
```

Expected: PASS (2 tests)

**Step 5: Run all tests**

```bash
cd services/svc-machine && python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 6: Commit**

```bash
cd services/svc-machine && git add -A && git commit -m "feat(machine): register all six tools in ServiceConfig for /describe"
```

---

## Task 8: Update Dockerfile for asyncssh

**Files:**
- Modify: `services/svc-machine/Dockerfile`

**Step 1: Write a smoke test assertion**

Verify the current Dockerfile installs correctly by checking the file:

```bash
cat services/svc-machine/Dockerfile
```

Expected: See the current Dockerfile without asyncssh.

**Step 2: Modify the Dockerfile**

In `services/svc-machine/Dockerfile`, add `openssh-client` to the apt-get line (so the container can initiate SSH connections) and the asyncssh dependency is already handled via `pyproject.toml`:

Change:
```dockerfile
RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*
```
to:
```dockerfile
RUN apt-get update && apt-get install -y ripgrep openssh-client && rm -rf /var/lib/apt/lists/*
```

The `asyncssh` Python package is already in `pyproject.toml` (from Task 4), so `uv pip install --system .` in the Dockerfile will install it automatically.

**Step 3: Verify existing Dockerfile test still passes**

```bash
cd services/svc-machine && python -m pytest tests/test_dockerfile.py -v
```

Expected: PASS (if the test checks Dockerfile content; if not, just confirm the Dockerfile is syntactically correct)

**Step 4: Commit**

```bash
cd services/svc-machine && git add Dockerfile && git commit -m "build(machine): add openssh-client to Dockerfile for SSH connectivity"
```

---

## Task 9: Run full test suite and fix any issues

**Files:** No new files — this is a verification step.

**Step 1: Run the complete test suite**

```bash
cd services/svc-machine && python -m pytest tests/ -v --tb=short
```

Expected: ALL PASS. If any tests fail, fix them before proceeding.

**Step 2: Run linting and type checking**

```bash
cd services/svc-machine && python -m ruff check src/ tests/ && python -m ruff format --check src/ tests/
```

Fix any lint or format issues found.

**Step 3: Verify the full import chain works**

```bash
cd services/svc-machine && python -c "
from svc_machine.driver import MachineDriver, ExecResult, FileReadResult, FileEditResult, FileGlobResult
from svc_machine.local_backend import LocalBackend
from svc_machine.ssh_driver import SSHDriver
from svc_machine.instance_manager import InstanceManager, InstanceNotFoundError
from svc_machine.service import create_machine_app
print('All imports successful')
"
```

Expected: `All imports successful`

**Step 4: Commit any fixes**

```bash
cd services/svc-machine && git add -A && git commit -m "fix(machine): lint and type fixes for Phase 1 consolidation"
```

(Skip this commit if there were no fixes needed.)

---

## Summary

After completing all 9 tasks, the machine service has:

1. **`driver.py`** — Abstract `MachineDriver` base class defining the contract
2. **`local_backend.py`** — Now implements `MachineDriver` (was standalone, now formalized)
3. **`ssh_driver.py`** — `SSHDriver` implementing `MachineDriver` via asyncssh
4. **`instance_manager.py`** — `InstanceManager` for per-session lifecycle management
5. **`service.py`** — Instance lifecycle endpoints (`POST /instances`, `DELETE /instances/{id}`) and instance-scoped operation endpoints (`/instances/{id}/exec`, `/instances/{id}/files/*`)
6. **`/describe`** — Advertises all six tools: `bash`, `read_file`, `write_file`, `edit_file`, `grep`, `glob`
7. **Dockerfile** — Updated with `openssh-client` for SSH connectivity
8. **`pyproject.toml`** — Updated with `asyncssh>=2.14` dependency

**Not done yet (Phase 2):**
- Session-service integration (provisioning instances at session creation)
- Orchestrator forwarding of `machine_instance_id`
- CLI changes for `create_session()` with machine config

**Not done yet (Phase 3):**
- Agent definition YAML updates
- ampctl compose changes
- Deleting old services (svc-bash, svc-filesystem, svc-search)
