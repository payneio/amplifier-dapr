# Phase 1: Execution Layer & Core Tools — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Harden svc-machine with safety validation, output truncation, and background execution; replace Python regex grep with ripgrep; enrich glob filtering; then bring svc-bash, svc-search, and svc-filesystem to feature parity with upstream Amplifier modules.

**Architecture:** svc-machine is the execution boundary — all tool services call it for shell execution, file operations, and search. Safety and truncation live in svc-machine so every caller (svc-bash, svc-search, etc.) gets enforcement automatically. Tool services (svc-bash, svc-search, svc-filesystem) are thin HTTP wrappers that forward parameters to svc-machine endpoints via Dapr sidecar.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, pytest + pytest-asyncio (asyncio_mode="auto"), httpx, ripgrep (rg), pathlib

---

## Conventions

**Every service follows this layout:**
```
services/svc-{name}/
  src/svc_{name}/
    __init__.py
    service.py or app.py    # app factory + module-level `app`
    ...                      # domain modules
  tests/
    test_*.py
  pyproject.toml
  describe.yaml
  Dockerfile
```

**Running tests (all services):**
```bash
cd services/svc-{name} && uv run pytest tests/ -v
```

**asyncio_mode = "auto"** is set in every pyproject.toml — async test functions run without `@pytest.mark.asyncio` decorators.

**Mocking pattern:** `patch.object(tool, "_call_machine_exec", new=AsyncMock(...))` — mock the internal HTTP call method, not the HTTP transport layer.

**Commit messages:** `feat(svc-{name}): short description`

---

## Task 1: svc-machine Safety Validator — Test

**Files:**
- Create: `services/svc-machine/src/svc_machine/safety.py`
- Create: `services/svc-machine/tests/test_safety.py`

**Step 1: Write the test file**

Create `services/svc-machine/tests/test_safety.py`:

```python
"""Tests for SafetyValidator — profile-based command safety validation."""

import pytest

from svc_machine.safety import SafetyValidator


class TestStrictProfile:
    """Tests for the strict safety profile."""

    @pytest.fixture
    def validator(self) -> SafetyValidator:
        """Create a SafetyValidator with the strict profile."""
        return SafetyValidator(profile="strict")

    def test_allows_safe_commands(self, validator: SafetyValidator) -> None:
        """Benign dev commands are allowed in strict mode."""
        allowed, reason = validator.validate("echo hello")
        assert allowed is True
        assert reason is None

    def test_allows_git_commands(self, validator: SafetyValidator) -> None:
        """Git commands are allowed in strict mode."""
        allowed, _ = validator.validate("git status")
        assert allowed is True

    def test_blocks_rm_rf_root(self, validator: SafetyValidator) -> None:
        """'rm -rf /' is blocked in strict mode."""
        allowed, reason = validator.validate("rm -rf /")
        assert allowed is False
        assert reason is not None
        assert "root" in reason.lower() or "delete" in reason.lower()

    def test_blocks_rm_fr_root(self, validator: SafetyValidator) -> None:
        """'rm -fr /' variant is also blocked."""
        allowed, reason = validator.validate("rm -fr /")
        assert allowed is False

    def test_blocks_rm_rf_home(self, validator: SafetyValidator) -> None:
        """'rm -rf ~' is blocked in strict mode."""
        allowed, _ = validator.validate("rm -rf ~")
        assert allowed is False

    def test_blocks_sudo(self, validator: SafetyValidator) -> None:
        """'sudo' commands are blocked in strict mode."""
        allowed, reason = validator.validate("sudo apt install vim")
        assert allowed is False
        assert "sudo" in reason.lower() or "privilege" in reason.lower()

    def test_blocks_mkfs(self, validator: SafetyValidator) -> None:
        """'mkfs' commands are blocked in strict mode."""
        allowed, _ = validator.validate("mkfs.ext4 /dev/sda1")
        assert allowed is False

    def test_blocks_dd_dev_zero(self, validator: SafetyValidator) -> None:
        """'dd if=/dev/zero' is blocked in strict mode."""
        allowed, _ = validator.validate("dd if=/dev/zero of=/dev/sda")
        assert allowed is False

    def test_blocks_chmod_777_root(self, validator: SafetyValidator) -> None:
        """'chmod 777 /' is blocked in strict mode."""
        allowed, _ = validator.validate("chmod 777 /")
        assert allowed is False

    def test_blocks_fork_bomb(self, validator: SafetyValidator) -> None:
        """Fork bomb is blocked in strict mode."""
        allowed, _ = validator.validate(":(){ :|:& };:")
        assert allowed is False

    def test_allows_rm_rf_on_project_dir(self, validator: SafetyValidator) -> None:
        """'rm -rf ./build' on a project subdirectory is NOT blocked."""
        allowed, _ = validator.validate("rm -rf ./build")
        assert allowed is True

    def test_sudo_in_quoted_string_not_blocked(
        self, validator: SafetyValidator
    ) -> None:
        """'echo \"use sudo\"' should NOT be blocked — sudo is inside a string."""
        allowed, _ = validator.validate("echo 'use sudo carefully'")
        assert allowed is True


class TestStandardProfile:
    """Tests for the standard safety profile."""

    @pytest.fixture
    def validator(self) -> SafetyValidator:
        """Create a SafetyValidator with the standard profile."""
        return SafetyValidator(profile="standard")

    def test_blocks_rm_rf_root(self, validator: SafetyValidator) -> None:
        """'rm -rf /' is blocked in standard mode."""
        allowed, _ = validator.validate("rm -rf /")
        assert allowed is False

    def test_blocks_sudo(self, validator: SafetyValidator) -> None:
        """'sudo' commands are blocked in standard mode."""
        allowed, _ = validator.validate("sudo rm something")
        assert allowed is False

    def test_allows_safe_commands(self, validator: SafetyValidator) -> None:
        """Benign dev commands are allowed."""
        allowed, _ = validator.validate("pytest tests/ -v")
        assert allowed is True


class TestPermissiveProfile:
    """Tests for the permissive safety profile."""

    @pytest.fixture
    def validator(self) -> SafetyValidator:
        """Create a SafetyValidator with the permissive profile."""
        return SafetyValidator(profile="permissive")

    def test_allows_sudo(self, validator: SafetyValidator) -> None:
        """'sudo' is allowed in permissive mode."""
        allowed, _ = validator.validate("sudo apt install vim")
        assert allowed is True

    def test_blocks_rm_rf_root(self, validator: SafetyValidator) -> None:
        """'rm -rf /' is still blocked even in permissive mode."""
        allowed, _ = validator.validate("rm -rf /")
        assert allowed is False

    def test_blocks_fork_bomb(self, validator: SafetyValidator) -> None:
        """Fork bomb is still blocked even in permissive mode."""
        allowed, _ = validator.validate(":(){ :|:& };:")
        assert allowed is False

    def test_allows_mkfs(self, validator: SafetyValidator) -> None:
        """'mkfs' is allowed in permissive mode."""
        allowed, _ = validator.validate("mkfs.ext4 /dev/sda1")
        assert allowed is True


class TestDefaultProfile:
    """Tests for profile resolution and env-var default."""

    def test_default_profile_is_standard(self) -> None:
        """SafetyValidator() with no args uses 'standard' profile."""
        validator = SafetyValidator()
        # Standard profile blocks sudo
        allowed, _ = validator.validate("sudo echo hi")
        assert allowed is False

    def test_invalid_profile_raises(self) -> None:
        """SafetyValidator with unknown profile name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown.*profile"):
            SafetyValidator(profile="nonexistent")
```

**Step 2: Run test to verify it fails**

```bash
cd services/svc-machine && uv run pytest tests/test_safety.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'svc_machine.safety'`

---

## Task 2: svc-machine Safety Validator — Implement

**Files:**
- Create: `services/svc-machine/src/svc_machine/safety.py`

**Step 1: Write the implementation**

Create `services/svc-machine/src/svc_machine/safety.py`:

```python
"""Safety validation for command execution in svc-machine.

Profile-based system ported from upstream amplifier-module-tool-bash.
Three profiles: strict, standard, permissive — set via SAFETY_PROFILE env var.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class _BlockPattern:
    """A pattern to match against commands for blocking."""

    pattern: str
    reason: str
    check_type: Literal["command", "substring", "regex"] = "substring"


# -- Profiles ---------------------------------------------------------------

_STRICT_PATTERNS: list[_BlockPattern] = [
    _BlockPattern("rm -rf /", "Prevents root filesystem deletion", "command"),
    _BlockPattern("rm -rf ~", "Prevents home directory deletion", "command"),
    _BlockPattern("rm -fr /", "Prevents root filesystem deletion", "command"),
    _BlockPattern("rm -fr ~", "Prevents home directory deletion", "command"),
    _BlockPattern("sudo", "Privilege escalation not allowed in strict mode", "command"),
    _BlockPattern("su -", "User switching not allowed", "command"),
    _BlockPattern("dd if=/dev/zero", "Dangerous disk overwrite", "substring"),
    _BlockPattern("dd if=/dev/random", "Dangerous disk overwrite", "substring"),
    _BlockPattern("mkfs", "Filesystem creation not allowed", "command"),
    _BlockPattern(r">\s*/dev/(?!null)", "Writing to devices not allowed", "regex"),
    _BlockPattern("passwd", "Password changes not allowed", "command"),
    _BlockPattern("chmod 777 /", "Dangerous root permissions", "substring"),
    _BlockPattern("chown -R /", "Recursive ownership of root not allowed", "substring"),
    _BlockPattern(":(){ :|:& };:", "Fork bomb", "substring"),
]

_STANDARD_PATTERNS: list[_BlockPattern] = list(_STRICT_PATTERNS)  # same set

_PERMISSIVE_PATTERNS: list[_BlockPattern] = [
    _BlockPattern("rm -rf /", "Prevents root filesystem deletion", "command"),
    _BlockPattern("rm -fr /", "Prevents root filesystem deletion", "command"),
    _BlockPattern(":(){ :|:& };:", "Fork bomb", "substring"),
]

_PROFILES: dict[str, list[_BlockPattern]] = {
    "strict": _STRICT_PATTERNS,
    "standard": _STANDARD_PATTERNS,
    "permissive": _PERMISSIVE_PATTERNS,
}


class SafetyValidator:
    """Validate commands against a configurable safety profile.

    Profiles set via constructor or ``SAFETY_PROFILE`` env var (default: ``"standard"``).

    Args:
        profile: One of ``"strict"``, ``"standard"``, ``"permissive"``.

    Raises:
        ValueError: If profile name is not recognised.
    """

    def __init__(self, profile: str | None = None) -> None:
        if profile is None:
            profile = os.environ.get("SAFETY_PROFILE", "standard")
        if profile not in _PROFILES:
            valid = ", ".join(_PROFILES)
            raise ValueError(f"Unknown safety profile '{profile}'. Valid: {valid}")
        self._profile_name = profile
        self._patterns = _PROFILES[profile]

    def validate(self, command: str) -> tuple[bool, str | None]:
        """Check whether *command* is safe to execute.

        Returns:
            ``(True, None)`` when allowed, ``(False, reason_string)`` when denied.
        """
        for bp in self._patterns:
            if self._check(command, bp):
                return False, bp.reason
        return True, None

    # -- internal matching ---------------------------------------------------

    def _check(self, command: str, bp: _BlockPattern) -> bool:
        if bp.check_type == "substring":
            return bp.pattern.lower() in command.lower()
        if bp.check_type == "regex":
            try:
                return bool(re.search(bp.pattern, command))
            except re.error:
                return False
        # "command" — must appear at a command position, not inside a string
        return self._at_command_position(command, bp.pattern)

    def _at_command_position(self, command: str, pattern: str) -> bool:
        """Return True if *pattern* appears at a command position in *command*.

        A command position is: start-of-string, or after a shell operator
        (``; | && || ( `` `  ``$(``), but NOT inside single/double quotes.
        """
        quoted = self._find_quoted_regions(command)
        cmd_lower = command.lower()
        pat_lower = pattern.lower()
        start = 0
        while True:
            idx = cmd_lower.find(pat_lower, start)
            if idx == -1:
                return False
            if not self._in_quoted(idx, quoted) and self._is_cmd_start(command, idx):
                # Extra guard: if the pattern contains '/', make sure it's
                # not embedded in a longer path token (e.g. ~/dev/project).
                if "/" in pattern and idx > 0 and command[idx - 1] not in " \t;|&()>`":
                    start = idx + 1
                    continue
                return True
            start = idx + 1

    @staticmethod
    def _find_quoted_regions(command: str) -> list[tuple[int, int]]:
        regions: list[tuple[int, int]] = []
        i = 0
        while i < len(command):
            if command[i] in ('"', "'"):
                quote = command[i]
                s = i
                i += 1
                while i < len(command):
                    if command[i] == "\\" and i + 1 < len(command):
                        i += 2
                        continue
                    if command[i] == quote:
                        regions.append((s, i + 1))
                        break
                    i += 1
            i += 1
        return regions

    @staticmethod
    def _in_quoted(pos: int, regions: list[tuple[int, int]]) -> bool:
        return any(s < pos < e for s, e in regions)

    @staticmethod
    def _is_cmd_start(command: str, idx: int) -> bool:
        before = command[:idx].rstrip()
        if not before:
            return True
        for op in ("$(", "&&", "||", ";", "|", "(", "`"):
            if before.endswith(op):
                return True
        return False
```

**Step 2: Run tests to verify they pass**

```bash
cd services/svc-machine && uv run pytest tests/test_safety.py -v
```
Expected: All tests PASS.

**Step 3: Commit**

```bash
cd services/svc-machine && git add src/svc_machine/safety.py tests/test_safety.py && git commit -m "feat(svc-machine): add SafetyValidator with strict/standard/permissive profiles"
```

---

## Task 3: svc-machine Output Truncation — Test

**Files:**
- Create: `services/svc-machine/src/svc_machine/truncation.py`
- Create: `services/svc-machine/tests/test_truncation.py`

**Step 1: Write the test file**

Create `services/svc-machine/tests/test_truncation.py`:

```python
"""Tests for output truncation logic."""

from svc_machine.truncation import truncate_output


class TestTruncateOutput:
    """Tests for truncate_output()."""

    def test_short_output_unchanged(self) -> None:
        """Output under the limit is returned unchanged."""
        text = "hello world\n"
        result, was_truncated = truncate_output(text, max_bytes=1000)
        assert result == text
        assert was_truncated is False

    def test_exact_limit_unchanged(self) -> None:
        """Output exactly at the byte limit is returned unchanged."""
        text = "a" * 100
        result, was_truncated = truncate_output(text, max_bytes=100)
        assert result == text
        assert was_truncated is False

    def test_over_limit_is_truncated(self) -> None:
        """Output over the limit is truncated with a marker."""
        lines = [f"line {i}" for i in range(200)]
        text = "\n".join(lines) + "\n"
        result, was_truncated = truncate_output(text, max_bytes=500)
        assert was_truncated is True
        assert "[...truncated" in result

    def test_truncated_has_head_and_tail(self) -> None:
        """Truncated output contains lines from both the start and end."""
        lines = [f"line-{i:04d}" for i in range(500)]
        text = "\n".join(lines) + "\n"
        result, was_truncated = truncate_output(text, max_bytes=2000)
        assert was_truncated is True
        # Head lines (first lines present)
        assert "line-0000" in result
        # Tail lines (last lines present)
        assert "line-0499" in result

    def test_truncated_marker_has_byte_counts(self) -> None:
        """The truncation marker includes total and shown byte counts."""
        text = "x" * 10_000
        result, was_truncated = truncate_output(text, max_bytes=1000)
        assert was_truncated is True
        assert "10,000" in result or "10000" in result  # total bytes

    def test_empty_string(self) -> None:
        """Empty string is returned unchanged."""
        result, was_truncated = truncate_output("", max_bytes=100)
        assert result == ""
        assert was_truncated is False

    def test_default_max_bytes(self) -> None:
        """Default max_bytes is 100_000."""
        small = "x" * 100
        result, was_truncated = truncate_output(small)
        assert was_truncated is False
```

**Step 2: Run test to verify it fails**

```bash
cd services/svc-machine && uv run pytest tests/test_truncation.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'svc_machine.truncation'`

---

## Task 4: svc-machine Output Truncation — Implement

**Files:**
- Create: `services/svc-machine/src/svc_machine/truncation.py`

**Step 1: Write the implementation**

Create `services/svc-machine/src/svc_machine/truncation.py`:

```python
"""Output truncation for subprocess results.

Ported from upstream amplifier-module-tool-bash.  When output exceeds
*max_bytes*, show the first ~40 % of lines + a marker + the last ~20 % of
lines so the caller retains both the beginning (most useful) and the end
(final status) of the output.
"""

from __future__ import annotations

_DEFAULT_MAX_BYTES = 100_000  # ~100 KB


def truncate_output(
    text: str,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> tuple[str, bool]:
    """Truncate *text* if it exceeds *max_bytes*.

    Returns:
        ``(possibly_truncated_text, was_truncated)``
    """
    original_bytes = len(text.encode("utf-8"))
    if original_bytes <= max_bytes:
        return text, False

    head_budget = int(max_bytes * 0.4)
    tail_budget = int(max_bytes * 0.2)

    lines = text.split("\n")

    # Build head
    head_lines: list[str] = []
    head_size = 0
    for line in lines:
        line_bytes = len((line + "\n").encode("utf-8"))
        if head_size + line_bytes > head_budget:
            break
        head_lines.append(line)
        head_size += line_bytes

    # Build tail
    tail_lines: list[str] = []
    tail_size = 0
    for line in reversed(lines):
        line_bytes = len((line + "\n").encode("utf-8"))
        if tail_size + line_bytes > tail_budget:
            break
        tail_lines.insert(0, line)
        tail_size += line_bytes

    head_content = "\n".join(head_lines)
    tail_content = "\n".join(tail_lines)
    shown_bytes = len(head_content.encode("utf-8")) + len(tail_content.encode("utf-8"))

    marker = (
        f"\n[...truncated {original_bytes:,} bytes, showing {shown_bytes:,} bytes...]\n"
    )

    return head_content + marker + tail_content, True
```

**Step 2: Run tests to verify they pass**

```bash
cd services/svc-machine && uv run pytest tests/test_truncation.py -v
```
Expected: All tests PASS.

**Step 3: Commit**

```bash
cd services/svc-machine && git add src/svc_machine/truncation.py tests/test_truncation.py && git commit -m "feat(svc-machine): add output truncation with head+tail preservation"
```

---

## Task 5: svc-machine /exec Integration — Test

Wire safety validation, output truncation, and background execution into the existing `/exec` endpoint.

**Files:**
- Modify: `services/svc-machine/src/svc_machine/service.py`
- Modify: `services/svc-machine/src/svc_machine/local_backend.py`
- Modify: `services/svc-machine/tests/test_service.py` (add new test classes)
- Modify: `services/svc-machine/tests/test_local_backend.py` (add new test class)

**Step 1: Write the tests**

Append to `services/svc-machine/tests/test_service.py` (after the existing `TestExecEndpoint` class, near end of file):

```python


class TestExecSafety:
    """Tests for safety validation on POST /exec."""

    @pytest.fixture
    def client(self, tmp_path: Path) -> TestClient:
        """Create a TestClient with strict safety profile."""
        import os

        os.environ["SAFETY_PROFILE"] = "strict"
        application = create_machine_app(workspace_dir=tmp_path)
        yield TestClient(application)
        os.environ.pop("SAFETY_PROFILE", None)

    def test_blocked_command_returns_403(self, client: TestClient) -> None:
        """POST /exec with a blocked command returns 403 with denial reason."""
        response = client.post("/exec", json={"command": "rm -rf /"})
        assert response.status_code == 403
        data = response.json()["detail"]
        assert data["denied"] is True
        assert "reason" in data

    def test_allowed_command_passes(self, client: TestClient) -> None:
        """POST /exec with a safe command still works normally."""
        response = client.post("/exec", json={"command": "echo safe"})
        assert response.status_code == 200
        assert "safe" in response.json()["stdout"]


class TestExecTruncation:
    """Tests for output truncation on POST /exec."""

    @pytest.fixture
    def client(self, tmp_path: Path) -> TestClient:
        """Create a TestClient for truncation tests."""
        application = create_machine_app(workspace_dir=tmp_path)
        return TestClient(application)

    def test_large_output_is_truncated(self, client: TestClient) -> None:
        """POST /exec truncates stdout that exceeds 100KB."""
        # Generate ~200KB of output
        response = client.post(
            "/exec",
            json={"command": "python3 -c \"print('x' * 200_000)\"", "timeout": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("truncated") is True


class TestExecBackground:
    """Tests for background execution on POST /exec."""

    @pytest.fixture
    def client(self, tmp_path: Path) -> TestClient:
        """Create a TestClient for background tests."""
        application = create_machine_app(workspace_dir=tmp_path)
        return TestClient(application)

    def test_background_returns_pid(self, client: TestClient) -> None:
        """POST /exec with run_in_background=True returns PID immediately."""
        response = client.post(
            "/exec",
            json={"command": "sleep 60", "run_in_background": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert "pid" in data
        assert isinstance(data["pid"], int)
        assert data["status"] == "running"
```

Append to `services/svc-machine/tests/test_local_backend.py` (after the existing test classes):

```python


class TestExecBackground:
    """Tests for LocalBackend.exec_background()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    async def test_exec_background_returns_pid(self, backend: LocalBackend) -> None:
        """exec_background() returns a dict with pid and 'running' status."""
        result = await backend.exec_background("sleep 60")
        assert "pid" in result
        assert isinstance(result["pid"], int)
        assert result["status"] == "running"
        # Clean up: kill the background process
        import os
        import signal

        try:
            os.kill(result["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-machine && uv run pytest tests/test_service.py::TestExecSafety -v
```
Expected: FAIL (no safety check in /exec yet, so `rm -rf /` returns 200 instead of 403).

```bash
cd services/svc-machine && uv run pytest tests/test_service.py::TestExecBackground -v
```
Expected: FAIL (no `run_in_background` field in ExecRequest yet).

```bash
cd services/svc-machine && uv run pytest tests/test_local_backend.py::TestExecBackground -v
```
Expected: FAIL (`exec_background` method doesn't exist on LocalBackend).

---

## Task 6: svc-machine /exec Integration — Implement

**Files:**
- Modify: `services/svc-machine/src/svc_machine/service.py`
- Modify: `services/svc-machine/src/svc_machine/local_backend.py`

**Step 1: Add exec_background to LocalBackend**

In `services/svc-machine/src/svc_machine/local_backend.py`, add this import at the top (alongside the existing `import asyncio`):

```python
import subprocess as _subprocess_module
```

Then add this method to the `LocalBackend` class, right after the existing `exec` method (after line ~105):

```python
    async def exec_background(
        self,
        command: str,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        """Spawn a command in the background and return immediately.

        Args:
            command: Shell command to run.
            working_dir: Working directory (must be within workspace_dir).

        Returns:
            Dict with ``pid`` (int) and ``status`` (``"running"``).
        """
        cwd = self._resolve_working_dir(working_dir)
        process = _subprocess_module.Popen(
            command,
            shell=True,
            executable="/bin/bash",
            stdout=_subprocess_module.DEVNULL,
            stderr=_subprocess_module.DEVNULL,
            cwd=str(cwd),
            start_new_session=True,
        )
        return {"pid": process.pid, "status": "running"}
```

> **Note:** The existing `local_backend.py` has a `_resolve_working_dir` helper that validates `working_dir` and falls back to `self._workspace_dir`. It's at line 65. The new method reuses it.

**Step 2: Wire safety, truncation, and background into service.py**

In `services/svc-machine/src/svc_machine/service.py`:

**2a.** Add imports near the top (after `from svc_machine.local_backend import LocalBackend` on line 9):

```python
from svc_machine.safety import SafetyValidator
from svc_machine.truncation import truncate_output
```

**2b.** Add `run_in_background` field to `ExecRequest`. Replace lines 18-22:

```python
class ExecRequest(BaseModel):
    """Request body for POST /exec."""

    command: str
    timeout: int = 30
    working_dir: str | None = None
    run_in_background: bool = False
```

**2c.** Add `truncated` field to `ExecResponse`. Replace lines 25-31:

```python
class ExecResponse(BaseModel):
    """Response body for POST /exec."""

    stdout: str
    stderr: str
    exit_code: int
    truncated: bool = False
```

**2d.** Inside `create_machine_app()`, instantiate the safety validator (right after `backend = LocalBackend(...)`, around line 91):

```python
    safety = SafetyValidator()
```

**2e.** Replace the `exec_command` route handler (lines ~93-108) with:

```python
    @app.post("/exec")
    async def exec_command(request: ExecRequest) -> dict:
        """Execute a shell command within the workspace directory."""
        # Safety check
        allowed, reason = safety.validate(request.command)
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail={"denied": True, "reason": reason},
            )

        # Background execution
        if request.run_in_background:
            result = await backend.exec_background(
                command=request.command,
                working_dir=request.working_dir,
            )
            return result

        try:
            result = await backend.exec(
                command=request.command,
                timeout=request.timeout,
                working_dir=request.working_dir,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Truncation
        stdout, stdout_truncated = truncate_output(result.stdout)
        stderr, stderr_truncated = truncate_output(result.stderr)
        truncated = stdout_truncated or stderr_truncated

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": result.exit_code,
            "truncated": truncated,
        }
```

**Step 3: Run all tests to verify they pass**

```bash
cd services/svc-machine && uv run pytest tests/ -v
```
Expected: All tests PASS (existing + new).

**Step 4: Commit**

```bash
cd services/svc-machine && git add -A && git commit -m "feat(svc-machine): wire safety, truncation, and background exec into /exec endpoint"
```

---

## Task 7: svc-machine Dockerfile — Add ripgrep

**Files:**
- Modify: `services/svc-machine/Dockerfile`

**Step 1: Add ripgrep installation**

In `services/svc-machine/Dockerfile`, add a `RUN` line in Stage 2 (after the `FROM amplifier-service-base` line on line 12, before the `COPY` lines):

```dockerfile
RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*
```

The full Stage 2 becomes:

```dockerfile
# ── Stage 2: svc-machine ───────────────────────────────────────────────
FROM amplifier-service-base
RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*
# Copy SDK to the path [tool.uv.sources] expects: ../../amplifier-service-sdk
# from /build/svc-machine/ resolves to /amplifier-service-sdk/
COPY amplifier-service-sdk/ /amplifier-service-sdk/
COPY services/svc-machine/ /build/svc-machine/
RUN cd /build/svc-machine && uv pip install --system . && rm -rf /build /amplifier-service-sdk

ENV WORKSPACE_DIR=/workspace

CMD ["uvicorn", "svc_machine.service:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 2: Commit**

```bash
cd services/svc-machine && git add Dockerfile && git commit -m "feat(svc-machine): install ripgrep in Dockerfile for fast grep"
```

---

## Task 8: svc-machine Ripgrep Grep — Test

Replace the Python `re`-based `file_grep` in `local_backend.py` with a ripgrep subprocess. The new method accepts the full parameter set.

**Files:**
- Modify: `services/svc-machine/src/svc_machine/local_backend.py`
- Modify: `services/svc-machine/src/svc_machine/service.py` (update FileGrepRequest + endpoint)
- Modify: `services/svc-machine/tests/test_local_backend.py`

**Step 1: Write the tests**

Replace the existing `TestFileGrep` class in `services/svc-machine/tests/test_local_backend.py` with the following. (The old class starts around the `TestFileGrep` marker — find it and replace entirely.)

```python
class TestFileGrep:
    """Tests for LocalBackend.file_grep() using ripgrep."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    @pytest.fixture(autouse=True)
    def populated_dir(self, tmp_path: Path) -> Path:
        """Create files with known content for grep testing."""
        (tmp_path / "funcs.py").write_text(
            "def foo():\n    pass\n\ndef bar():\n    return 1\n"
        )
        (tmp_path / "notes.txt").write_text("no functions here\n")
        # Create a node_modules dir that should be excluded by default
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "pkg.js").write_text("def fake():\n")
        return tmp_path

    async def test_grep_files_with_matches_default(
        self, backend: LocalBackend
    ) -> None:
        """file_grep returns file paths by default (files_with_matches mode)."""
        result = await backend.file_grep(pattern=r"def \w+")
        assert result is not None
        file_list = result["matches"]
        assert any("funcs.py" in f for f in file_list)

    async def test_grep_content_mode(self, backend: LocalBackend) -> None:
        """file_grep with output_mode='content' returns line content."""
        result = await backend.file_grep(pattern=r"def \w+", output_mode="content")
        assert result is not None
        assert len(result["matches"]) == 2

    async def test_grep_count_mode(self, backend: LocalBackend) -> None:
        """file_grep with output_mode='count' returns match counts per file."""
        result = await backend.file_grep(pattern=r"def \w+", output_mode="count")
        assert result is not None
        assert len(result["matches"]) >= 1

    async def test_grep_excludes_node_modules(self, backend: LocalBackend) -> None:
        """file_grep excludes node_modules by default."""
        result = await backend.file_grep(pattern="def fake", output_mode="content")
        assert result is not None
        assert len(result["matches"]) == 0

    async def test_grep_include_ignored(self, backend: LocalBackend) -> None:
        """file_grep with include_ignored=True searches excluded dirs."""
        result = await backend.file_grep(
            pattern="def fake", output_mode="content", include_ignored=True
        )
        assert result is not None
        assert len(result["matches"]) >= 1

    async def test_grep_glob_filter(self, backend: LocalBackend) -> None:
        """file_grep with glob_pattern='*.py' only searches Python files."""
        result = await backend.file_grep(
            pattern="def", output_mode="content", glob_pattern="*.py"
        )
        assert result is not None
        # All matches should be from .py files
        for match in result["matches"]:
            if isinstance(match, dict) and "file" in match:
                assert match["file"].endswith(".py")

    async def test_grep_case_insensitive(self, backend: LocalBackend) -> None:
        """file_grep with case_insensitive=True matches regardless of case."""
        result = await backend.file_grep(
            pattern="DEF", output_mode="content", case_insensitive=True
        )
        assert result is not None
        assert len(result["matches"]) >= 2

    async def test_grep_head_limit(self, backend: LocalBackend) -> None:
        """file_grep with head_limit limits the number of results."""
        result = await backend.file_grep(
            pattern=r"def \w+", output_mode="content", head_limit=1
        )
        assert result is not None
        assert len(result["matches"]) <= 1

    async def test_grep_no_matches(self, backend: LocalBackend) -> None:
        """file_grep returns empty matches when pattern has no hits."""
        result = await backend.file_grep(pattern="ZZZZZ_NO_MATCH")
        assert result is not None
        assert result["matches"] == []

    async def test_grep_invalid_path(self, backend: LocalBackend) -> None:
        """file_grep returns None when path escapes workspace."""
        result = await backend.file_grep(pattern="test", path="../../../etc")
        assert result is None
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-machine && uv run pytest tests/test_local_backend.py::TestFileGrep -v
```
Expected: FAIL — signature mismatch (`file_grep` doesn't accept the new parameters).

---

## Task 9: svc-machine Ripgrep Grep — Implement

**Files:**
- Modify: `services/svc-machine/src/svc_machine/local_backend.py`
- Modify: `services/svc-machine/src/svc_machine/service.py`

**Step 1: Replace file_grep in local_backend.py**

Replace the entire existing `file_grep` method in `LocalBackend` with the following. The old method is around lines 249-297 (look for `async def file_grep`).

```python
    # Default directories to exclude from grep
    _GREP_EXCLUDED_DIRS: list[str] = [
        "node_modules", ".venv", ".git", "__pycache__", "build", "dist",
        ".mypy_cache", ".pytest_cache", ".tox", ".eggs",
    ]

    _GREP_HEAD_LIMITS: dict[str, int] = {
        "files_with_matches": 200,
        "count": 200,
        "content": 500,
    }

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
        """Search file contents using ripgrep.

        Returns:
            Dict with 'matches' and 'total_matches', or None if path
            escapes workspace.
        """
        resolved = self._resolve_path(path)
        if resolved is None:
            return None

        if head_limit is None:
            head_limit = self._GREP_HEAD_LIMITS.get(output_mode, 200)

        cmd = ["rg", "--no-heading"]

        # Output mode flags
        if output_mode == "files_with_matches":
            cmd.append("--files-with-matches")
        elif output_mode == "count":
            cmd.append("--count")

        # Default exclusions
        if not include_ignored:
            for d in self._GREP_EXCLUDED_DIRS:
                cmd.extend(["--glob", f"!{d}"])

        # Filters
        if glob_pattern:
            cmd.extend(["--glob", glob_pattern])
        if file_type:
            cmd.extend(["--type", file_type])

        # Flags
        if case_insensitive:
            cmd.append("--ignore-case")
        if multiline:
            cmd.extend(["--multiline", "--multiline-dotall"])

        # Context lines (content mode only)
        if output_mode == "content":
            if line_numbers:
                cmd.append("--line-number")
            if context is not None:
                cmd.extend(["--context", str(context)])
            else:
                if after_context is not None:
                    cmd.extend(["--after-context", str(after_context)])
                if before_context is not None:
                    cmd.extend(["--before-context", str(before_context)])

        cmd.extend(["--", pattern, str(resolved)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await proc.communicate()
        raw = stdout_bytes.decode("utf-8", errors="replace").strip()

        if not raw:
            return {"matches": [], "total_matches": 0}

        all_items = self._parse_grep_output(raw, output_mode, resolved)
        total = len(all_items)
        page = all_items[offset : offset + head_limit]
        return {"matches": page, "total_matches": total}

    def _parse_grep_output(
        self, raw: str, output_mode: str, base_path: Path
    ) -> list[Any]:
        """Parse ripgrep output into structured matches."""
        lines = raw.split("\n")

        if output_mode == "files_with_matches":
            result: list[Any] = []
            for line in lines:
                if line:
                    try:
                        rel = Path(line).relative_to(base_path)
                        result.append(rel.as_posix())
                    except ValueError:
                        result.append(line)
            return result

        if output_mode == "count":
            result = []
            for line in lines:
                if ":" in line:
                    parts = line.rsplit(":", 1)
                    try:
                        fpath = Path(parts[0]).relative_to(base_path)
                        result.append({"file": fpath.as_posix(), "count": int(parts[1])})
                    except (ValueError, IndexError):
                        result.append({"raw": line})
            return result

        # content mode
        result = []
        for line in lines:
            # rg format: /abs/path:line_num:content
            parts = line.split(":", 2)
            if len(parts) >= 3:
                try:
                    fpath = Path(parts[0]).relative_to(base_path)
                    result.append({
                        "file": fpath.as_posix(),
                        "line": int(parts[1]),
                        "content": parts[2],
                    })
                except (ValueError, IndexError):
                    result.append({"raw": line})
            elif line.strip():
                result.append({"raw": line})
        return result
```

**Step 2: Update FileGrepRequest and endpoint in service.py**

Replace `FileGrepRequest` in `services/svc-machine/src/svc_machine/service.py` (find the class around line 69) with:

```python
class FileGrepRequest(BaseModel):
    """Request body for POST /files/grep."""

    pattern: str
    path: str = "."
    output_mode: str = "files_with_matches"
    glob: str | None = None
    type: str | None = None
    after_context: int | None = None
    before_context: int | None = None
    context: int | None = None
    case_insensitive: bool = False
    line_numbers: bool = True
    head_limit: int | None = None
    offset: int = 0
    include_ignored: bool = False
    multiline: bool = False
```

Replace the `grep_files` endpoint (find `@app.post("/files/grep")`) with:

```python
    @app.post("/files/grep")
    async def grep_files(request: FileGrepRequest) -> dict:
        """Search file contents with a regex pattern within the workspace."""
        result = await backend.file_grep(
            pattern=request.pattern,
            path=request.path,
            output_mode=request.output_mode,
            glob_pattern=request.glob,
            file_type=request.type,
            after_context=request.after_context,
            before_context=request.before_context,
            context=request.context,
            case_insensitive=request.case_insensitive,
            line_numbers=request.line_numbers,
            head_limit=request.head_limit,
            offset=request.offset,
            include_ignored=request.include_ignored,
            multiline=request.multiline,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Path not found")
        return result
```

**Step 3: Run tests to verify they pass**

> **Prerequisite:** `rg` (ripgrep) must be installed locally. Check with `which rg`. If missing: `sudo apt-get update && sudo apt-get install -y ripgrep`

```bash
cd services/svc-machine && uv run pytest tests/test_local_backend.py::TestFileGrep -v
```
Expected: All tests PASS.

```bash
cd services/svc-machine && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 4: Commit**

```bash
cd services/svc-machine && git add -A && git commit -m "feat(svc-machine): replace Python re grep with ripgrep subprocess and full param set"
```

---

## Task 10: svc-machine Enriched Glob — Test

Add exclude patterns, type filter, and include_ignored to `file_glob`.

**Files:**
- Modify: `services/svc-machine/src/svc_machine/local_backend.py`
- Modify: `services/svc-machine/src/svc_machine/service.py`
- Modify: `services/svc-machine/tests/test_local_backend.py`

**Step 1: Write the tests**

Replace the existing `TestFileGlob` class in `services/svc-machine/tests/test_local_backend.py` with:

```python
class TestFileGlob:
    """Tests for LocalBackend.file_glob() with enriched filtering."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    @pytest.fixture(autouse=True)
    def populated_dir(self, tmp_path: Path) -> Path:
        """Create a directory tree for glob testing."""
        (tmp_path / "main.py").write_text("def main(): pass\n")
        (tmp_path / "readme.txt").write_text("readme\n")
        nested = tmp_path / "pkg"
        nested.mkdir()
        (nested / "utils.py").write_text("def helper(): pass\n")
        # Excluded by default
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "dep.js").write_text("module.exports = {}\n")
        subdir = tmp_path / "mydir"
        subdir.mkdir()
        return tmp_path

    def test_glob_pattern(self, backend: LocalBackend) -> None:
        """file_glob('*.py') finds .py files but not .txt files."""
        result = backend.file_glob("*.py")
        assert result is not None
        matches = result["matches"]
        assert any(p.endswith(".py") for p in matches)
        assert not any(p.endswith(".txt") for p in matches)

    def test_glob_recursive(self, backend: LocalBackend) -> None:
        """file_glob('**/*.py') finds nested .py files."""
        result = backend.file_glob("**/*.py")
        assert result is not None
        matches = result["matches"]
        assert len(matches) >= 2
        assert any("utils.py" in p for p in matches)

    def test_glob_excludes_node_modules(self, backend: LocalBackend) -> None:
        """file_glob excludes node_modules by default."""
        result = backend.file_glob("**/*.js")
        assert result is not None
        matches = result["matches"]
        assert not any("node_modules" in p for p in matches)

    def test_glob_include_ignored(self, backend: LocalBackend) -> None:
        """file_glob with include_ignored=True includes node_modules."""
        result = backend.file_glob("**/*.js", include_ignored=True)
        assert result is not None
        matches = result["matches"]
        assert any("node_modules" in p for p in matches)

    def test_glob_exclude_pattern(self, backend: LocalBackend) -> None:
        """file_glob with exclude=['*.txt'] omits .txt files."""
        result = backend.file_glob("*", exclude=["*.txt"])
        assert result is not None
        matches = result["matches"]
        assert not any(p.endswith(".txt") for p in matches)

    def test_glob_type_dir(self, backend: LocalBackend) -> None:
        """file_glob with type_filter='dir' returns only directories."""
        result = backend.file_glob("*", type_filter="dir")
        assert result is not None
        matches = result["matches"]
        assert any("pkg" in p for p in matches)
        assert any("mydir" in p for p in matches)
        # Regular files should not be present
        assert not any(p.endswith(".py") for p in matches)
        assert not any(p.endswith(".txt") for p in matches)

    def test_glob_type_file(self, backend: LocalBackend) -> None:
        """file_glob with type_filter='file' returns only files (default)."""
        result = backend.file_glob("*", type_filter="file")
        assert result is not None
        matches = result["matches"]
        # Only files
        for m in matches:
            assert "." in m  # files have extensions in this fixture

    def test_glob_nonexistent_base(self, backend: LocalBackend) -> None:
        """file_glob returns None when base path is not a directory."""
        result = backend.file_glob("*.py", path="nonexistent_dir")
        assert result is None
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-machine && uv run pytest tests/test_local_backend.py::TestFileGlob -v
```
Expected: FAIL — signature mismatch (old `file_glob` doesn't accept `exclude`, `type_filter`, `include_ignored`).

---

## Task 11: svc-machine Enriched Glob — Implement

**Files:**
- Modify: `services/svc-machine/src/svc_machine/local_backend.py`
- Modify: `services/svc-machine/src/svc_machine/service.py`

**Step 1: Replace file_glob in local_backend.py**

Add this import at the top of `local_backend.py` (if not already present):

```python
import fnmatch
```

Replace the entire existing `file_glob` method in `LocalBackend` with:

```python
    _GLOB_EXCLUDED_DIRS: list[str] = [
        "node_modules", ".venv", ".git", "__pycache__", "build", "dist",
        ".mypy_cache", ".pytest_cache", ".tox", ".eggs",
    ]

    _GLOB_MAX_RESULTS = 500

    def file_glob(
        self,
        pattern: str,
        path: str = ".",
        exclude: list[str] | None = None,
        type_filter: str = "file",
        include_ignored: bool = False,
    ) -> dict[str, Any] | None:
        """Match files using a glob pattern with filtering.

        Args:
            pattern: Glob pattern (e.g. ``'*.py'``, ``'**/*.py'``).
            path: Relative path to the base directory (default ``'.'``).
            exclude: Glob patterns to exclude from results.
            type_filter: ``'file'``, ``'dir'``, or ``'any'``.
            include_ignored: When True, don't apply default directory exclusions.

        Returns:
            Dict with ``'matches'`` (list of posix paths) and ``'total_files'``,
            or None if the base path escapes the workspace or doesn't exist.
        """
        resolved = self._resolve_path(path)
        if resolved is None or not resolved.is_dir():
            return None

        excluded_dirs = set() if include_ignored else set(self._GLOB_EXCLUDED_DIRS)
        exclude_patterns = exclude or []

        matches: list[str] = []
        for match in sorted(resolved.glob(pattern)):
            # Skip entries inside excluded directories
            rel = match.relative_to(resolved)
            parts = rel.parts
            if any(part in excluded_dirs for part in parts):
                continue

            # Apply custom exclude patterns
            rel_str = rel.as_posix()
            if any(fnmatch.fnmatch(rel_str, ep) for ep in exclude_patterns):
                continue
            if any(fnmatch.fnmatch(rel.name, ep) for ep in exclude_patterns):
                continue

            # Type filter
            if type_filter == "file" and not match.is_file():
                continue
            if type_filter == "dir" and not match.is_dir():
                continue

            matches.append(rel_str)

        total = len(matches)
        return {"matches": matches[: self._GLOB_MAX_RESULTS], "total_files": total}
```

**Step 2: Update FileGlobRequest and endpoint in service.py**

Replace `FileGlobRequest` in `services/svc-machine/src/svc_machine/service.py` (find the class near `FileGrepRequest`) with:

```python
class FileGlobRequest(BaseModel):
    """Request body for POST /files/glob."""

    pattern: str
    path: str = "."
    exclude: list[str] | None = None
    type: str = "file"
    include_ignored: bool = False
```

Replace the `glob_files` endpoint (find `@app.post("/files/glob")`) with:

```python
    @app.post("/files/glob")
    def glob_files(request: FileGlobRequest) -> dict:
        """Match files using a glob pattern within the workspace."""
        result = backend.file_glob(
            pattern=request.pattern,
            path=request.path,
            exclude=request.exclude,
            type_filter=request.type,
            include_ignored=request.include_ignored,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Base path not found")
        return result
```

**Step 3: Run tests to verify they pass**

```bash
cd services/svc-machine && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 4: Commit**

```bash
cd services/svc-machine && git add -A && git commit -m "feat(svc-machine): enrich file_glob with exclude, type filter, and default directory exclusions"
```

---

## Task 12: svc-bash Feature Parity — Test

Forward `run_in_background` to svc-machine, add approval metadata to tool schema.

**Files:**
- Modify: `services/svc-bash/src/svc_bash/tool.py`
- Modify: `services/svc-bash/describe.yaml`
- Modify: `services/svc-bash/tests/test_tool.py`

**Step 1: Write the tests**

Append to `services/svc-bash/tests/test_tool.py`, inside the `TestBashTool` class (before the class ends):

```python
    async def test_execute_forwards_run_in_background(self, tool: BashTool) -> None:
        """execute() with run_in_background=True forwards it to machine service."""
        mock_result: dict[str, Any] = {"pid": 12345, "status": "running"}
        with patch.object(
            tool, "_call_machine_exec", new=AsyncMock(return_value=mock_result)
        ) as mock_call:
            result = await tool.execute(
                {"command": "sleep 60", "run_in_background": True}
            )

        assert result.success is True
        assert result.output is not None
        assert result.output["pid"] == 12345
        # Verify run_in_background was forwarded in the JSON payload
        mock_call.assert_awaited_once()

    async def test_schema_has_run_in_background(self, tool: BashTool) -> None:
        """input_schema includes run_in_background property."""
        props = tool.input_schema["properties"]
        assert "run_in_background" in props
        assert props["run_in_background"]["type"] == "boolean"

    async def test_metadata_includes_approval_info(self, tool: BashTool) -> None:
        """get_metadata() returns approval metadata for the hooks system."""
        meta = tool.get_metadata()
        assert meta["requires_approval"] is True
        assert meta["risk_level"] == "high"
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-bash && uv run pytest tests/test_tool.py -v -k "test_execute_forwards_run_in_background or test_metadata_includes_approval_info"
```
Expected: FAIL — `_call_machine_exec` doesn't accept/forward `run_in_background`, and `get_metadata()` doesn't exist.

---

## Task 13: svc-bash Feature Parity — Implement

**Files:**
- Modify: `services/svc-bash/src/svc_bash/tool.py`

**Step 1: Add get_metadata method to BashTool**

In `services/svc-bash/src/svc_bash/tool.py`, add after the `input_schema` definition (around line 38):

```python
    def get_metadata(self) -> dict[str, Any]:
        """Return tool metadata for the approval hook system."""
        return {
            "requires_approval": True,
            "risk_level": "high",
        }
```

**Step 2: Update execute to handle background mode and safety denials**

Replace the `execute` method (lines 48-88) with:

```python
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a bash command via the machine service.

        Args:
            input: Tool input dict. Must contain ``command``.

        Returns:
            ToolResult with execution results.
        """
        command = input.get("command")
        if not command:
            return ToolResult(
                success=False,
                error={"message": "command is required"},
            )

        timeout = int(input.get("timeout", _DEFAULT_TIMEOUT_SECONDS))
        run_in_background = input.get("run_in_background", False)

        try:
            machine_result = await self._call_machine_exec(
                command, timeout, run_in_background=run_in_background
            )
        except httpx.HTTPStatusError as exc:
            # Check for 403 safety denial
            if exc.response.status_code == 403:
                detail = exc.response.json().get("detail", {})
                reason = detail.get("reason", "Command denied for safety")
                return ToolResult(
                    success=False,
                    error={"message": f"Command denied: {reason}"},
                )
            return ToolResult(
                success=False,
                error={"message": f"machine service error: {exc.response.status_code}"},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service unreachable: {exc}"},
            )

        # Background mode returns pid
        if run_in_background:
            return ToolResult(
                success=True,
                output={
                    "pid": machine_result.get("pid"),
                    "status": machine_result.get("status", "running"),
                },
            )

        exit_code: int = machine_result.get("exit_code", 1)
        output: dict[str, Any] = {
            "stdout": machine_result.get("stdout", ""),
            "stderr": machine_result.get("stderr", ""),
            "returncode": exit_code,
        }
        if machine_result.get("truncated"):
            output["truncated"] = True

        return ToolResult(
            success=(exit_code == 0),
            output=output,
        )
```

**Step 3: Update _call_machine_exec to forward run_in_background**

Replace `_call_machine_exec` (lines ~90-110) with:

```python
    async def _call_machine_exec(
        self,
        command: str,
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
        run_in_background: bool = False,
    ) -> dict[str, Any]:
        """POST to the machine service /exec endpoint.

        Args:
            command: Shell command string.
            timeout: Command-level timeout in seconds.
            run_in_background: If True, run in background mode.

        Returns:
            Parsed JSON response dict from the machine service.
        """
        http_timeout = timeout + 10
        payload: dict[str, Any] = {"command": command, "timeout": timeout}
        if run_in_background:
            payload["run_in_background"] = True
        async with httpx.AsyncClient(timeout=http_timeout) as client:
            response = await client.post(
                f"{self._base_url}/exec",
                json=payload,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-bash && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd services/svc-bash && git add -A && git commit -m "feat(svc-bash): forward run_in_background to svc-machine, add approval metadata"
```

---

## Task 14: svc-search Feature Parity — Test

Forward the full grep and glob parameter sets to svc-machine.

**Files:**
- Modify: `services/svc-search/src/svc_search/tools.py`
- Modify: `services/svc-search/describe.yaml`
- Modify: `services/svc-search/tests/test_tools.py`

**Step 1: Write the tests**

Append to `services/svc-search/tests/test_tools.py`, inside `TestGrepTool`:

```python
    async def test_execute_forwards_output_mode(self, tool: GrepTool) -> None:
        """execute() forwards output_mode to the machine service."""
        mock_result: dict[str, Any] = {"matches": [], "total_matches": 0}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ) as mock_call:
            await tool.execute({"pattern": "hello", "output_mode": "content"})

        mock_call.assert_awaited_once()
        payload = mock_call.call_args[0][1]  # second positional arg is payload
        assert payload["output_mode"] == "content"

    async def test_execute_forwards_context_params(self, tool: GrepTool) -> None:
        """execute() forwards -A, -B, -C context params to the machine service."""
        mock_result: dict[str, Any] = {"matches": [], "total_matches": 0}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ) as mock_call:
            await tool.execute({
                "pattern": "hello",
                "after_context": 3,
                "before_context": 2,
                "case_insensitive": True,
            })

        payload = mock_call.call_args[0][1]
        assert payload["after_context"] == 3
        assert payload["before_context"] == 2
        assert payload["case_insensitive"] is True

    async def test_schema_has_full_params(self, tool: GrepTool) -> None:
        """GrepTool schema declares all upstream parameters."""
        props = tool.input_schema["properties"]
        for key in ["pattern", "path", "output_mode", "glob", "type",
                     "after_context", "before_context", "context",
                     "case_insensitive", "line_numbers", "head_limit",
                     "offset", "include_ignored", "multiline"]:
            assert key in props, f"Missing schema property: {key}"
```

Append to `TestGlobTool`:

```python
    async def test_execute_forwards_exclude(self, tool: GlobTool) -> None:
        """execute() forwards exclude patterns to the machine service."""
        mock_result: dict[str, Any] = {"matches": [], "total_files": 0}
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ) as mock_call:
            await tool.execute({
                "pattern": "**/*.py",
                "exclude": ["*.test.py"],
                "type": "file",
            })

        payload = mock_call.call_args[0][1]
        assert payload["exclude"] == ["*.test.py"]
        assert payload["type"] == "file"

    async def test_schema_has_full_params(self, tool: GlobTool) -> None:
        """GlobTool schema declares all upstream parameters."""
        props = tool.input_schema["properties"]
        for key in ["pattern", "path", "exclude", "type", "include_ignored"]:
            assert key in props, f"Missing schema property: {key}"
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-search && uv run pytest tests/test_tools.py -v
```
Expected: FAIL — new params not in schema, `execute()` doesn't forward them.

---

## Task 15: svc-search Feature Parity — Implement

**Files:**
- Modify: `services/svc-search/src/svc_search/tools.py`
- Modify: `services/svc-search/describe.yaml`

**Step 1: Update GrepTool input_schema and execute**

In `services/svc-search/src/svc_search/tools.py`, replace the `GrepTool` class entirely with:

```python
class GrepTool(BaseMachineTool):
    """Tool that searches file contents using grep via svc-machine."""

    _timeout_seconds: float = _GREP_TIMEOUT_SECONDS
    _endpoint_path: str = "/files/grep"

    name: str = "grep"
    description: str = (
        "Search file contents with regex patterns. Uses ripgrep when available."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The regular expression pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in (defaults to cwd)",
            },
            "output_mode": {
                "type": "string",
                "enum": ["files_with_matches", "content", "count"],
                "description": "Output mode (default: files_with_matches)",
            },
            "glob": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. '*.js')",
            },
            "type": {
                "type": "string",
                "description": "File type to search (e.g. 'py', 'js')",
            },
            "after_context": {
                "type": "integer",
                "description": "Lines to show after each match (-A)",
            },
            "before_context": {
                "type": "integer",
                "description": "Lines to show before each match (-B)",
            },
            "context": {
                "type": "integer",
                "description": "Lines around each match (-C)",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case insensitive search (-i)",
            },
            "line_numbers": {
                "type": "boolean",
                "description": "Show line numbers (default: true)",
            },
            "head_limit": {
                "type": "integer",
                "description": "Limit output to first N entries",
            },
            "offset": {
                "type": "integer",
                "description": "Skip first N entries (for pagination)",
            },
            "include_ignored": {
                "type": "boolean",
                "description": "Search excluded directories (node_modules, .venv, etc.)",
            },
            "multiline": {
                "type": "boolean",
                "description": "Enable multiline matching",
            },
        },
        "required": ["pattern"],
    }

    # Keys forwarded from input to the svc-machine payload
    _FORWARD_KEYS: list[str] = [
        "output_mode", "glob", "type", "after_context", "before_context",
        "context", "case_insensitive", "line_numbers", "head_limit",
        "offset", "include_ignored", "multiline",
    ]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Forward grep request with full parameter set to svc-machine."""
        pattern = params.get("pattern")
        if not pattern:
            return ToolResult(
                success=False,
                error={"message": "pattern is required"},
            )

        payload: dict[str, Any] = {"pattern": pattern}
        if "path" in params:
            payload["path"] = params["path"]
        for key in self._FORWARD_KEYS:
            if key in params:
                payload[key] = params[key]

        result = await self._call_machine(self._endpoint_path, payload)
        return ToolResult(success=True, output=result)
```

**Step 2: Update GlobTool input_schema and execute**

Replace the `GlobTool` class entirely with:

```python
class GlobTool(BaseMachineTool):
    """Tool that matches files using glob patterns via svc-machine."""

    _timeout_seconds: float = _GLOB_TIMEOUT_SECONDS
    _endpoint_path: str = "/files/glob"

    name: str = "glob"
    description: str = "Fast file pattern matching tool."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files (e.g. '**/*.py')",
            },
            "path": {
                "type": "string",
                "description": "Base path to search from (defaults to cwd)",
            },
            "exclude": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Patterns to exclude from results",
            },
            "type": {
                "type": "string",
                "enum": ["file", "dir", "any"],
                "description": "Filter by type (default: file)",
            },
            "include_ignored": {
                "type": "boolean",
                "description": "Search in excluded directories",
            },
        },
        "required": ["pattern"],
    }

    _FORWARD_KEYS: list[str] = ["exclude", "type", "include_ignored"]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Forward glob request with full parameter set to svc-machine."""
        pattern = params.get("pattern")
        if not pattern:
            return ToolResult(
                success=False,
                error={"message": "pattern is required"},
            )

        payload: dict[str, Any] = {"pattern": pattern}
        if "path" in params:
            payload["path"] = params["path"]
        for key in self._FORWARD_KEYS:
            if key in params:
                payload[key] = params[key]

        result = await self._call_machine(self._endpoint_path, payload)
        return ToolResult(success=True, output=result)
```

**Step 3: Update describe.yaml**

Replace `services/svc-search/describe.yaml` entirely with:

```yaml
name: svc-search
version: '0.1.0'
tools:
  - name: grep
    description: Search file contents with regex patterns via ripgrep
    input_schema:
      type: object
      properties:
        pattern:
          type: string
          description: The regular expression pattern to search for
        path:
          type: string
          description: File or directory to search in (defaults to current directory)
        output_mode:
          type: string
          enum: [files_with_matches, content, count]
          description: "Output mode (default: files_with_matches)"
        glob:
          type: string
          description: Glob pattern to filter files (e.g. '*.js')
        type:
          type: string
          description: File type to search (e.g. 'py', 'js')
        after_context:
          type: integer
          description: Lines after each match (-A)
        before_context:
          type: integer
          description: Lines before each match (-B)
        context:
          type: integer
          description: Lines around each match (-C)
        case_insensitive:
          type: boolean
          description: Case insensitive search
        line_numbers:
          type: boolean
          description: Show line numbers (default true)
        head_limit:
          type: integer
          description: Limit output to first N entries
        offset:
          type: integer
          description: Skip first N entries
        include_ignored:
          type: boolean
          description: Search excluded directories
        multiline:
          type: boolean
          description: Enable multiline matching
      required:
        - pattern
  - name: glob
    description: Fast file pattern matching
    input_schema:
      type: object
      properties:
        pattern:
          type: string
          description: Glob pattern to match files (e.g., '**/*.py')
        path:
          type: string
          description: Base path to search from (defaults to current directory)
        exclude:
          type: array
          items:
            type: string
          description: Patterns to exclude from results
        type:
          type: string
          enum: [file, dir, any]
          description: "Filter by type (default: file)"
        include_ignored:
          type: boolean
          description: Search in excluded directories
      required:
        - pattern
```

**Step 4: Run tests to verify they pass**

```bash
cd services/svc-search && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd services/svc-search && git add -A && git commit -m "feat(svc-search): forward full grep/glob parameter sets to svc-machine"
```

---

## Task 16: svc-filesystem Feature Parity — Test

Add directory listing support, `cat -n` line number formatting, and line truncation to `ReadFileTool`.

**Files:**
- Modify: `services/svc-filesystem/src/svc_filesystem/tools.py`
- Modify: `services/svc-filesystem/describe.yaml`
- Modify: `services/svc-filesystem/tests/test_tools.py`

**Step 1: Write the tests**

Append to `services/svc-filesystem/tests/test_tools.py` (after existing test classes):

```python


class TestReadFileToolDirectoryListing:
    """Tests for ReadFileTool directory listing support."""

    @pytest.fixture
    def tool(self) -> ReadFileTool:
        """Create a ReadFileTool pointed at a fake machine URL."""
        return ReadFileTool(machine_base_url="http://fake-machine:8080")

    async def test_directory_returns_listing(self, tool: ReadFileTool) -> None:
        """execute() on a directory returns formatted DIR/FILE listing."""
        mock_result: dict[str, Any] = {
            "entries": [
                {"name": "src", "type": "dir"},
                {"name": "main.py", "type": "file", "size": 100},
            ]
        }
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"file_path": "some_dir/"})

        assert result.success is True
        assert result.output is not None
        content = result.output.get("content", "")
        assert "DIR" in content
        assert "FILE" in content
        assert "src" in content
        assert "main.py" in content


class TestReadFileToolLineFormatting:
    """Tests for cat -n line formatting and line truncation."""

    @pytest.fixture
    def tool(self) -> ReadFileTool:
        """Create a ReadFileTool pointed at a fake machine URL."""
        return ReadFileTool(machine_base_url="http://fake-machine:8080")

    async def test_output_has_line_numbers(self, tool: ReadFileTool) -> None:
        """execute() formats content with cat -n style line numbers."""
        mock_result: dict[str, Any] = {
            "content": "line1\nline2\nline3\n",
            "total_lines": 3,
        }
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"file_path": "test.txt"})

        assert result.success is True
        content = result.output["content"]
        # Should have line numbers like "     1\tline1"
        assert "1\t" in content
        assert "line1" in content

    async def test_long_lines_truncated(self, tool: ReadFileTool) -> None:
        """execute() truncates lines longer than 2000 characters."""
        long_line = "x" * 3000
        mock_result: dict[str, Any] = {
            "content": long_line + "\n",
            "total_lines": 1,
        }
        with patch.object(
            tool, "_call_machine", new=AsyncMock(return_value=mock_result)
        ):
            result = await tool.execute({"file_path": "test.txt"})

        assert result.success is True
        # The line should be truncated — content should be shorter than 3000 chars
        # (accounting for line number prefix)
        lines = result.output["content"].split("\n")
        first_line = lines[0]
        # Line number prefix + 2000 chars + "..." = well under 2200
        assert len(first_line) < 2200
```

**Step 2: Run tests to verify they fail**

```bash
cd services/svc-filesystem && uv run pytest tests/test_tools.py::TestReadFileToolDirectoryListing -v
cd services/svc-filesystem && uv run pytest tests/test_tools.py::TestReadFileToolLineFormatting -v
```
Expected: FAIL — directory listing support and line formatting don't exist yet.

---

## Task 17: svc-filesystem Feature Parity — Implement

**Files:**
- Modify: `services/svc-filesystem/src/svc_filesystem/tools.py`
- Modify: `services/svc-filesystem/describe.yaml`

**Step 1: Update ReadFileTool.execute**

In `services/svc-filesystem/src/svc_filesystem/tools.py`, replace the `ReadFileTool` class's `execute` method with the following. The existing `execute` is around lines 116-142 (look for `async def execute` inside `ReadFileTool`).

```python
    _MAX_LINE_LENGTH = 2000

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Read file contents or list a directory via the machine service.

        If the machine returns an ``entries`` key (directory listing) or the
        path ends with ``/``, format as ``DIR``/``FILE`` entries.  Otherwise
        format file content with ``cat -n`` style line numbers and truncate
        long lines at 2000 characters.

        Args:
            params: Tool input dict.  Must contain ``file_path``.
                    Optional: ``offset`` (1-indexed start line), ``limit``.

        Returns:
            ToolResult with formatted content.
        """
        file_path = params.get("file_path")
        if not file_path:
            return ToolResult(
                success=False,
                error={"message": "file_path is required"},
            )

        payload: dict[str, Any] = {"path": file_path}
        if "offset" in params:
            payload["offset"] = params["offset"]
        if "limit" in params:
            payload["limit"] = params["limit"]

        try:
            data = await self._call_machine("/files/read", payload)
        except Exception:
            # If file read fails and path looks like a directory, try listing
            if isinstance(file_path, str) and file_path.endswith("/"):
                return await self._try_directory_listing(file_path)
            raise

        # Check if machine returned a directory listing
        if "entries" in data:
            return self._format_directory_listing(data, file_path)

        # Format file content with cat -n line numbers
        raw_content = data.get("content", "")
        total_lines = data.get("total_lines", 0)
        offset = params.get("offset", 1)
        formatted = self._format_with_line_numbers(raw_content, offset)

        return ToolResult(
            success=True,
            output={
                "content": formatted,
                "total_lines": total_lines,
            },
        )

    async def _try_directory_listing(self, file_path: str) -> ToolResult:
        """Attempt to list a directory via the machine service."""
        path = file_path.rstrip("/") if file_path.endswith("/") else file_path
        try:
            data = await self._call_machine("/files/list", {"path": path})
        except Exception as exc:
            return ToolResult(
                success=False,
                error={"message": f"Could not read path: {exc}"},
            )
        return self._format_directory_listing(data, file_path)

    @staticmethod
    def _format_directory_listing(data: dict[str, Any], path: str) -> ToolResult:
        """Format directory entries as DIR/FILE text."""
        entries = data.get("entries", [])
        lines = [f"Directory: {path}\n"]
        for entry in entries:
            kind = "DIR " if entry.get("type") == "dir" else "FILE"
            lines.append(f"  {kind} {entry['name']}")
        content = "\n".join(lines) + "\n"
        return ToolResult(
            success=True,
            output={"content": content, "is_directory": True},
        )

    def _format_with_line_numbers(self, content: str, start_line: int = 1) -> str:
        """Format content with cat -n style line numbers, truncating long lines."""
        if not content:
            return content
        lines = content.splitlines(keepends=True)
        formatted: list[str] = []
        for i, line in enumerate(lines, start=start_line):
            stripped = line.rstrip("\n")
            if len(stripped) > self._MAX_LINE_LENGTH:
                stripped = stripped[: self._MAX_LINE_LENGTH] + "..."
            formatted.append(f"{i:>6}\t{stripped}")
        return "\n".join(formatted) + "\n" if formatted else ""
```

**Step 2: Update describe.yaml**

Replace `services/svc-filesystem/describe.yaml` entirely with:

```yaml
name: svc-filesystem
version: '0.1.0'
tools:
  - name: read_file
    description: >
      Reads a file or lists a directory from the filesystem. Returns content
      with cat -n style line numbers. Lines longer than 2000 characters are
      truncated. When file_path is a directory (or ends with /), returns a
      formatted listing showing DIR/FILE entries.
    input_schema:
      type: object
      properties:
        file_path:
          type: string
          description: Path to the file or directory to read
        offset:
          type: integer
          description: Line number to start reading from (1-indexed)
        limit:
          type: integer
          description: Maximum number of lines to read
      required:
        - file_path
  - name: write_file
    description: >
      Write content to a file on the filesystem. Creates parent directories
      if needed. Overwrites existing files.
    input_schema:
      type: object
      properties:
        file_path:
          type: string
          description: Path to the file to write
        content:
          type: string
          description: Content to write to the file
      required:
        - file_path
        - content
  - name: edit_file
    description: >
      Edit a file by replacing a string with another string. Performs exact
      string replacement. Use replace_all for bulk renaming.
    input_schema:
      type: object
      properties:
        file_path:
          type: string
          description: Path to the file to edit
        old_string:
          type: string
          description: The exact string to find and replace
        new_string:
          type: string
          description: The replacement string
        replace_all:
          type: boolean
          default: false
          description: If true, replace all occurrences; otherwise first only
      required:
        - file_path
        - old_string
        - new_string
```

**Step 3: Run tests to verify they pass**

```bash
cd services/svc-filesystem && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 4: Commit**

```bash
cd services/svc-filesystem && git add -A && git commit -m "feat(svc-filesystem): add directory listing, cat -n formatting, and line truncation"
```

---

## Task 18: Full Test Suite Verification

Run the complete test suite for all four services to confirm nothing is broken.

**Step 1: Run all svc-machine tests**

```bash
cd services/svc-machine && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 2: Run all svc-bash tests**

```bash
cd services/svc-bash && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 3: Run all svc-search tests**

```bash
cd services/svc-search && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 4: Run all svc-filesystem tests**

```bash
cd services/svc-filesystem && uv run pytest tests/ -v
```
Expected: All tests PASS.

**Step 5: Final commit (if any fixups needed)**

```bash
git add -A && git commit -m "test: verify all Phase 1 services pass full test suite"
```

---

## Summary

| Task | Service | What | Files Changed |
|------|---------|------|--------------|
| 1-2 | svc-machine | Safety validator (3 profiles) | `safety.py`, `test_safety.py` |
| 3-4 | svc-machine | Output truncation (head+tail) | `truncation.py`, `test_truncation.py` |
| 5-6 | svc-machine | Wire safety+truncation+background into /exec | `service.py`, `local_backend.py`, tests |
| 7 | svc-machine | Install ripgrep in Dockerfile | `Dockerfile` |
| 8-9 | svc-machine | Replace Python grep with ripgrep + full params | `local_backend.py`, `service.py`, tests |
| 10-11 | svc-machine | Enrich glob with exclude/type/ignored | `local_backend.py`, `service.py`, tests |
| 12-13 | svc-bash | Forward run_in_background, approval metadata | `tool.py`, `describe.yaml`, tests |
| 14-15 | svc-search | Forward full grep/glob param sets | `tools.py`, `describe.yaml`, tests |
| 16-17 | svc-filesystem | Directory listing, line numbers, truncation | `tools.py`, `describe.yaml`, tests |
| 18 | All | Full test suite verification | — |
