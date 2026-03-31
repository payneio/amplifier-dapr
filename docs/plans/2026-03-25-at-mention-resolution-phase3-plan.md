# At-Mention Resolution Phase 3: CLI Integration

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Wire the `working_dir` parameter from the CLI `run` command through `launch_session()` to `Host()`, so that `WorkingDirResolver` is active in CLI sessions and `@~/`, `@user:`, `@project:` mentions resolve correctly.

**Architecture:** Phase 2 already added `working_dir: Path | None = None` to `Host.__init__()` and auto-wires a `WorkingDirResolver` onto `self.mention_resolver` when it's provided. The only gap is plumbing: `launch_session()` doesn't accept or forward `working_dir`, and `_run_agent()` in `run.py` doesn't pass it to `launch_session()`. This plan adds that plumbing (~20 lines of production code).

**Tech Stack:** Python 3.12+, pytest with `asyncio_mode = "auto"`, Click, uv

**Design Document:** `docs/plans/2026-03-25-at-mention-resolution-design.md`

**Prior phases:** Phase 1-2 plan at `docs/plans/2026-03-25-at-mention-resolution-plan.md` (all 12 tasks complete, 903 tests passing).

---

### Task 1: Add `working_dir` Parameter to `launch_session()` + Forward to `Host()`

**Files:**
- Modify: `src/amplifier_ipc/cli/session_launcher.py` (lines 201, 338)
- Modify: `tests/cli/test_session_launcher.py`

**Step 1: Write the failing test**

Append to the bottom of `tests/cli/test_session_launcher.py`:

```python
# ---------------------------------------------------------------------------
# Test 10: launch_session forwards working_dir to Host
# ---------------------------------------------------------------------------


class TestLaunchSessionForwardsWorkingDir:
    def test_launch_session_forwards_working_dir_to_host(
        self, tmp_path: Path
    ) -> None:
        """launch_session passes working_dir kwarg through to Host constructor."""
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: wd-agent
  uuid: dddddddd-0000-0000-0000-000000000001
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    stack: my-stack
"""
        registry.register_definition(agent_yaml)

        mock_host_instance = MagicMock()
        fake_working_dir = tmp_path / "my-project"
        fake_working_dir.mkdir()

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            asyncio.run(
                launch_session(
                    "wd-agent",
                    registry=registry,
                    working_dir=fake_working_dir,
                )
            )

        assert mock_host_class.call_count == 1
        call_args = mock_host_class.call_args
        host_kwargs = call_args.kwargs if call_args.kwargs else {}

        assert "working_dir" in host_kwargs, (
            "launch_session must pass working_dir= to Host() "
            "so WorkingDirResolver is wired in CLI sessions"
        )
        assert host_kwargs["working_dir"] == fake_working_dir

    def test_launch_session_omits_working_dir_when_none(
        self, tmp_path: Path
    ) -> None:
        """launch_session does not pass working_dir when it is None."""
        from amplifier_ipc.host.definition_registry import Registry
        from amplifier_ipc.cli.session_launcher import launch_session

        registry = Registry(home=tmp_path / "amplifier_home")
        registry.ensure_home()

        agent_yaml = """\
agent:
  ref: no-wd-agent
  uuid: dddddddd-0000-0000-0000-000000000002
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    stack: my-stack
"""
        registry.register_definition(agent_yaml)

        mock_host_instance = MagicMock()

        with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
            mock_host_class.return_value = mock_host_instance

            asyncio.run(launch_session("no-wd-agent", registry=registry))

        call_args = mock_host_class.call_args
        host_kwargs = call_args.kwargs if call_args.kwargs else {}

        # working_dir should either be absent or explicitly None
        assert host_kwargs.get("working_dir") is None
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/cli/test_session_launcher.py::TestLaunchSessionForwardsWorkingDir -v`

Expected: FAIL — `TypeError: launch_session() got an unexpected keyword argument 'working_dir'`

**Step 3: Update `session_launcher.py`**

Make two changes to `src/amplifier_ipc/cli/session_launcher.py`:

**Change 1:** Add `working_dir` parameter to the `launch_session()` signature (line 201). Add after `verbose: bool = False,`:

```python
    working_dir: Path | None = None,
```

The full signature becomes (lines 201-212):
```python
async def launch_session(
    agent_name: str,
    extra_behaviors: list[str] | None = None,
    registry: Registry | None = None,
    user_settings_path: Path | None = None,
    project_settings_path: Path | None = None,
    provider_override: str | None = None,
    model_override: str | None = None,
    max_tokens: int | None = None,
    verbose: bool = False,
    working_dir: Path | None = None,
) -> Host:
```

**Change 2:** Forward `working_dir` to the `Host()` constructor on line 338. Change:

```python
    return Host(config, settings, service_configs=resolved.service_configs)
```

to:

```python
    return Host(config, settings, service_configs=resolved.service_configs, working_dir=working_dir)
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/cli/test_session_launcher.py -v`

Expected: All tests PASS (existing + 2 new)

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/cli/session_launcher.py tests/cli/test_session_launcher.py && git commit -m "feat(cli): add working_dir parameter to launch_session and forward to Host"
```

---

### Task 2: Pass `working_dir` from `_run_agent()` in `run.py`

**Files:**
- Modify: `src/amplifier_ipc/cli/commands/run.py` (lines 1-10, 173-180)

**Context:** The `_run_agent()` function already receives `working_dir: str | None` from the Click command (line 104). It currently drops this value. We need to pass it to `launch_session()`, defaulting to `Path.cwd()` when `None` (user confirmed Option A — always active).

**Step 1: Write the failing test**

There is no separate test file for `run.py` commands (they are tested via integration). Instead, we verify this works by inspecting the code change directly. The test from Task 1 already validates the `launch_session()` → `Host()` plumbing. To verify the `run.py` → `launch_session()` plumbing, add a focused test to `tests/cli/test_session_launcher.py`:

Append to the bottom of `tests/cli/test_session_launcher.py`:

```python
# ---------------------------------------------------------------------------
# Test 11: run.py passes working_dir to launch_session
# ---------------------------------------------------------------------------


class TestRunCommandPassesWorkingDir:
    def test_run_agent_passes_working_dir_to_launch_session(self) -> None:
        """_run_agent passes Path(working_dir) or Path.cwd() to launch_session."""
        from pathlib import Path as StdPath

        with (
            patch("amplifier_ipc.cli.commands.run._resolve_agent_name") as mock_resolve,
            patch("amplifier_ipc.cli.commands.run.launch_session") as mock_launch,
            patch("amplifier_ipc.cli.commands.run.KeyManager"),
        ):
            mock_resolve.return_value = "test-agent"
            mock_host = MagicMock()
            mock_host.run = MagicMock(return_value=AsyncIteratorMock([]))
            mock_host.session_id = "test-session-id"
            mock_launch.return_value = mock_host

            from amplifier_ipc.cli.commands.run import _run_agent

            # Case 1: explicit working_dir string
            asyncio.run(
                _run_agent(
                    "test-agent", "hello", [], None, None,
                    "/tmp/my-project",  # working_dir
                    None, None, None, False, "text",
                )
            )

            call_kwargs = mock_launch.call_args.kwargs
            assert call_kwargs["working_dir"] == StdPath("/tmp/my-project")

            mock_launch.reset_mock()

            # Case 2: working_dir=None defaults to cwd
            asyncio.run(
                _run_agent(
                    "test-agent", "hello", [], None, None,
                    None,  # working_dir
                    None, None, None, False, "text",
                )
            )

            call_kwargs = mock_launch.call_args.kwargs
            assert call_kwargs["working_dir"] == StdPath.cwd()
```

Also add this helper class at the top of the test file (after the existing imports):

```python
class AsyncIteratorMock:
    """Minimal async iterator for mocking host.run()."""

    def __init__(self, items: list[Any]) -> None:
        self._items = iter(items)

    def __aiter__(self) -> AsyncIteratorMock:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration
```

**Step 2: Run tests to verify they fail**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/cli/test_session_launcher.py::TestRunCommandPassesWorkingDir -v`

Expected: FAIL — `launch_session` mock not called with `working_dir`

**Step 3: Update `run.py`**

Make two changes to `src/amplifier_ipc/cli/commands/run.py`:

**Change 1:** Add `Path` import. At line 1-10, after `from typing import Any`, add:

```python
from pathlib import Path
```

**Change 2:** Update the `launch_session()` call in `_run_agent()` (lines 173-180). Change:

```python
        host = await launch_session(
            agent_name,
            extra_behaviors=behaviors if behaviors else None,
            provider_override=provider,
            model_override=model,
            max_tokens=max_tokens,
            verbose=verbose,
        )
```

to:

```python
        host = await launch_session(
            agent_name,
            extra_behaviors=behaviors if behaviors else None,
            provider_override=provider,
            model_override=model,
            max_tokens=max_tokens,
            verbose=verbose,
            working_dir=Path(working_dir) if working_dir else Path.cwd(),
        )
```

**Step 4: Run tests to verify they pass**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/cli/test_session_launcher.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
cd /data/labs/amplifier-ipc && git add src/amplifier_ipc/cli/commands/run.py tests/cli/test_session_launcher.py && git commit -m "feat(cli): pass working_dir from run command to launch_session (default cwd)"
```

---

### Task 3: Full Regression Verification

**Files:**
- No file changes

**Step 1: Run Phase 2 mention tests**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_mentions.py -v`

Expected: All tests PASS (no regressions)

**Step 2: Run host tests**

Run: `cd /data/labs/amplifier-ipc && uv run pytest tests/host/test_host.py -v`

Expected: All tests PASS

**Step 3: Run the full test suite**

Run: `cd /data/labs/amplifier-ipc && uv run pytest --timeout=60 -x -q`

Expected: All 905+ tests PASS (903 from Phase 2 + 3 new from this plan)

**Step 4: Commit (no changes — verification only)**

No commit needed. This task is verification only.