# Phase 3: Agent Definitions & Cleanup — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Remove svc-bash, svc-filesystem, and svc-search from agent definitions, regenerate docker-compose, delete the old service directories, clean up all references across the codebase, update documentation, and verify the full stack works end-to-end with the consolidated machine service.

**Architecture:** After Phase 1 (machine service consolidation) and Phase 2 (session lifecycle wiring), the machine service now handles all six tool operations (bash, read_file, write_file, edit_file, grep, glob) through per-session instances. Phase 3 completes the migration by removing the now-redundant proxy services from agent YAML definitions, regenerating the docker-compose stack, deleting the old service code, and cleaning up every reference to the old services across the codebase — tests, docs, configs, and the root pyproject.toml.

**Tech Stack:** YAML (agent definitions), Python (tests, session-service configs), Docker Compose, `ampctl` CLI

**Design document:** `docs/design/machine-service-consolidation-design.md`
**Phase 1 plan:** `docs/plans/phase1-machine-service-consolidation.md`
**Phase 2 plan:** `docs/plans/phase2-session-lifecycle-and-integration.md`

---

## Task 1: Update `agents/foundation.yaml` — remove bash, filesystem, search behaviors

**Files:**
- Modify: `agents/foundation.yaml` (lines 31–44)

**Step 1: Read the current file to confirm structure**

```bash
cat agents/foundation.yaml
```

Expected: The file contains `bash:`, `filesystem:`, and `search:` entries under `behaviors:` (lines 31–44), each with `build:` and `depends_on:` keys.

**Step 2: Remove the bash, filesystem, and search behavior blocks**

In `agents/foundation.yaml`, delete the following three blocks (lines 31–44):

```yaml
    bash:
      build: ./services/svc-bash
      depends_on:
        - machine

    filesystem:
      build: ./services/svc-filesystem
      depends_on:
        - machine

    search:
      build: ./services/svc-search
      depends_on:
        - machine
```

After this edit, the `behaviors:` section should go directly from `machine:` to `web:`:

```yaml
  behaviors:
    machine:
      build: ./services/svc-machine
      environment:
        WORKSPACE_DIR: /workspace
      volumes:
        - "${WORKSPACE_PATH:-.}:/workspace"

    web:
      build: ./services/svc-web
```

**Step 3: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('agents/foundation.yaml')); print('YAML valid')"
```

Expected: `YAML valid`

**Step 4: Verify bash/filesystem/search are gone**

```bash
grep -n 'svc-bash\|svc-filesystem\|svc-search' agents/foundation.yaml
```

Expected: No output (no matches).

**Step 5: Commit**

```bash
git add agents/foundation.yaml && git commit -m "refactor(agents): remove bash/filesystem/search behaviors from foundation.yaml"
```

---

## Task 2: Update `agents/default.yaml` — remove bash, filesystem, search behaviors

**Files:**
- Modify: `agents/default.yaml` (lines 22–35)

**Step 1: Remove the bash, filesystem, and search behavior blocks**

In `agents/default.yaml`, delete the following three blocks (lines 22–35):

```yaml
    bash:
      build: ./services/svc-bash
      depends_on:
        - machine

    filesystem:
      build: ./services/svc-filesystem
      depends_on:
        - machine

    search:
      build: ./services/svc-search
      depends_on:
        - machine
```

After this edit, the `behaviors:` section should go directly from `machine:` to `web:`:

```yaml
  behaviors:
    machine:
      build: ./services/svc-machine
      environment:
        WORKSPACE_DIR: /workspace
      volumes:
        - "${WORKSPACE_PATH:-.}:/workspace"

    web:
      build: ./services/svc-web
```

**Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('agents/default.yaml')); print('YAML valid')"
```

Expected: `YAML valid`

**Step 3: Verify bash/filesystem/search are gone**

```bash
grep -n 'svc-bash\|svc-filesystem\|svc-search' agents/default.yaml
```

Expected: No output (no matches).

**Step 4: Commit**

```bash
git add agents/default.yaml && git commit -m "refactor(agents): remove bash/filesystem/search behaviors from default.yaml"
```

---

## Task 3: Regenerate docker-compose.yaml via ampctl compose

**Files:**
- Regenerate: `docker-compose.yaml` (entire file — this is the canonical generated output)
- Regenerate: `agents/service-map.yaml` (if ampctl compose generates it)

**Step 1: Run ampctl compose to regenerate docker-compose.yaml**

```bash
cd /data/labs/amplifier-ipc && python -m ampctl compose
```

If `ampctl compose` writes to a different path, copy the output to `docker-compose.yaml`:

```bash
cp ampctl/docker-compose.yaml docker-compose.yaml
```

**Step 2: Verify the generated docker-compose.yaml does NOT contain old services**

```bash
grep -n 'svc-bash\|svc-filesystem\|svc-search' docker-compose.yaml
```

Expected: No output (no matches). The old services should be absent because they were removed from the agent YAML definitions.

**Step 3: Verify svc-machine IS still present**

```bash
grep -c 'svc-machine' docker-compose.yaml
```

Expected: A count > 0 (machine service is still in the compose file).

**Step 4: Verify the service-map also excludes old services**

```bash
grep -n 'svc-bash\|svc-filesystem\|svc-search' agents/service-map.yaml
```

Expected: No output.

**Step 5: Commit**

```bash
git add docker-compose.yaml agents/service-map.yaml && git commit -m "build: regenerate docker-compose.yaml without bash/filesystem/search services"
```

---

## Task 4: Delete old service directories

**Files:**
- Delete: `services/svc-bash/` (entire directory — 12 files)
- Delete: `services/svc-filesystem/` (entire directory — 13 files)
- Delete: `services/svc-search/` (entire directory — 13 files)

**Step 1: Verify no other service imports from these directories**

```bash
grep -r 'from svc_bash\|import svc_bash' services/ --include='*.py' | grep -v 'services/svc-bash/'
grep -r 'from svc_filesystem\|import svc_filesystem' services/ --include='*.py' | grep -v 'services/svc-filesystem/'
grep -r 'from svc_search\|import svc_search' services/ --include='*.py' | grep -v 'services/svc-search/'
```

Expected: No output for all three. No other service imports from the old services' Python packages.

**Step 2: Also check the root `tests/` directory for imports**

```bash
grep -rn 'from svc_bash\|import svc_bash\|from svc_filesystem\|import svc_filesystem\|from svc_search\|import svc_search' tests/
```

Expected: `tests/test_microservices_integration.py` imports `from svc_bash.app` and `from svc_bash.tool`. These references will be fixed in Task 6. Note them for now.

**Step 3: Delete the directories**

```bash
rm -rf services/svc-bash/
rm -rf services/svc-filesystem/
rm -rf services/svc-search/
```

**Step 4: Verify deletion**

```bash
ls services/svc-bash/ 2>&1
ls services/svc-filesystem/ 2>&1
ls services/svc-search/ 2>&1
```

Expected: `No such file or directory` for all three.

**Step 5: Commit**

```bash
git add -A && git commit -m "refactor: delete svc-bash, svc-filesystem, svc-search service directories"
```

---

## Task 5: Update session-service hardcoded service lists

**Files:**
- Modify: `services/session-service/src/session_service/agents.py` (lines 18–20, 47–49)
- Modify: `services/session-service/src/session_service/app.py` (lines 63–65)

**Step 1: Write a failing test to verify the old services are gone**

This test already exists from Phase 2 (Task 6 in `docs/plans/phase2-session-lifecycle-and-integration.md`). If it was implemented in Phase 2, skip ahead. If not, create `services/session-service/tests/test_consolidation_cleanup.py`:

```python
"""Tests verifying svc-bash/filesystem/search are removed from hardcoded lists."""

from __future__ import annotations


class TestOldServicesRemoved:
    """Verify svc-bash, svc-filesystem, svc-search are removed from hardcoded lists."""

    def test_default_services_excludes_old_proxy_services(self) -> None:
        """DEFAULT_SERVICES does not include svc-bash, svc-filesystem, svc-search."""
        from session_service.app import DEFAULT_SERVICES

        removed = {"svc-bash", "svc-filesystem", "svc-search"}
        for svc in removed:
            assert svc not in DEFAULT_SERVICES, f"{svc} should be removed from DEFAULT_SERVICES"

    def test_default_services_includes_svc_machine(self) -> None:
        """DEFAULT_SERVICES includes svc-machine as the replacement."""
        from session_service.app import DEFAULT_SERVICES

        assert "svc-machine" in DEFAULT_SERVICES

    def test_agents_dict_excludes_old_proxy_services(self) -> None:
        """AGENTS dict entries do not include svc-bash, svc-filesystem, svc-search."""
        from session_service.agents import AGENTS

        removed = {"svc-bash", "svc-filesystem", "svc-search"}
        for agent_name, agent_config in AGENTS.items():
            services = agent_config.get("services", [])
            for svc in removed:
                assert svc not in services, (
                    f"{svc} should be removed from AGENTS['{agent_name}']['services']"
                )

    def test_agents_dict_includes_svc_machine(self) -> None:
        """AGENTS dict entries include svc-machine as the replacement."""
        from session_service.agents import AGENTS

        for agent_name, agent_config in AGENTS.items():
            services = agent_config.get("services", [])
            assert "svc-machine" in services, (
                f"AGENTS['{agent_name}']['services'] should include svc-machine"
            )
```

**Step 2: Run the test to verify it fails**

```bash
cd services/session-service && uv run pytest tests/test_consolidation_cleanup.py -v
```

Expected: FAIL — `svc-bash` is still in the lists.

**Step 3: Update `services/session-service/src/session_service/app.py`**

Change `DEFAULT_SERVICES` (lines 62–78) from:

```python
DEFAULT_SERVICES: list[str] = [
    "svc-bash",
    "svc-filesystem",
    "svc-search",
    "svc-web",
```

to:

```python
DEFAULT_SERVICES: list[str] = [
    "svc-machine",
    "svc-web",
```

**Step 4: Update `services/session-service/src/session_service/agents.py`**

In the `AGENTS` dict, for both `"default"` and `"foundation"` entries, replace the three lines:

```python
            "svc-bash",
            "svc-filesystem",
            "svc-search",
```

with the single line:

```python
            "svc-machine",
```

The `"default"` entry services list (starting at line 17) should become:

```python
        "services": [
            "svc-machine",
            "svc-web",
            "svc-skills",
            "svc-todo",
            "svc-modes",
            "svc-providers",
            "svc-mock-provider",
            "svc-context",
            "svc-orchestrator",
            "svc-delegation",
            ...
```

Do the same for the `"foundation"` entry (starting at line 46).

**Step 5: Run the test to verify it passes**

```bash
cd services/session-service && uv run pytest tests/test_consolidation_cleanup.py -v
```

Expected: PASS (4 tests)

**Step 6: Run all session-service tests to check for regressions**

```bash
cd services/session-service && uv run pytest tests/ -v --tb=short
```

Expected: Some tests may fail due to hardcoded `"svc-bash"` references in test fixtures. Fix them in Task 6.

**Step 7: Commit**

```bash
git add services/session-service/src/session_service/agents.py services/session-service/src/session_service/app.py services/session-service/tests/test_consolidation_cleanup.py && git commit -m "refactor(session): replace svc-bash/filesystem/search with svc-machine in service lists"
```

---

## Task 6: Fix session-service test references to old services

**Files:**
- Modify: `services/session-service/tests/test_agents.py`
- Modify: `services/session-service/tests/test_app_agent.py`
- Modify: `services/session-service/tests/test_discovery.py`
- Modify: `services/session-service/tests/test_discovery_phase3a.py`
- Modify: `services/session-service/tests/test_metadata.py`

**Step 1: Fix `test_agents.py`**

In `services/session-service/tests/test_agents.py`:

- Line 66–68: Replace `"svc-bash"`, `"svc-filesystem"`, `"svc-search"` with `"svc-machine"` in the expected services list.
- Line 101: Change `build: ./services/svc-bash` to `build: ./services/svc-machine` in test YAML fixture.
- Line 103: Change `build: ./services/svc-filesystem` to remove it (or change to another valid service).
- Lines 113–114: Change `bash: svc-bash-456fghij` and `filesystem: svc-filesystem-789klmno` to `machine: svc-machine-xxxx` in the service-map fixture.
- Line 130: Change `assert "svc-bash-456fghij" in config["services"]` to `assert "svc-machine-` in assertion.

Read the file first to see exact context, then make targeted replacements to update the test fixtures from the old service names to `svc-machine`.

**Step 2: Fix `test_app_agent.py`**

In `services/session-service/tests/test_app_agent.py`:

- Line 193: Change `custom_services = ["svc-bash", "svc-filesystem"]` to `custom_services = ["svc-machine", "svc-web"]`.
- Line 213: Change `"services": ["svc-bash"]` to `"services": ["svc-machine"]`.
- Line 237: Change `"services": ["svc-bash"]` to `"services": ["svc-machine"]`.

**Step 3: Fix `test_discovery.py`**

In `services/session-service/tests/test_discovery.py`:

- Line 146: Change `"svc-bash": _make_describe(` to `"svc-machine": _make_describe(`.
- Line 261: Same change.

**Step 4: Fix `test_discovery_phase3a.py`**

This file has extensive references to the old services. The tests validate routing of `svc-filesystem` and `svc-search` tools. Since these tools now live in `svc-machine`, update all test assertions:

- Lines 29–43: Change the `_describe_filesystem()` mock to use `"name": "svc-machine"` and include all six tools (bash, read_file, write_file, edit_file, grep, glob).
- Lines 45–55: Remove the separate `_describe_search()` mock entirely — search tools are now in the machine describe response.
- Lines 87–101: Update assertions to check that all tool names map to `svc-machine` instead of `svc-filesystem`/`svc-search`.
- Lines 139–150: Same — update the combined routing test.
- Lines 175–177, 270–272: Remove `"svc-bash"`, `"svc-filesystem"`, `"svc-search"` from service lists; add `"svc-machine"` if not present.

**Step 5: Fix `test_metadata.py`**

In `services/session-service/tests/test_metadata.py`:

- Line 28: Change `"tools": {"bash": "svc-bash", "read_file": "svc-filesystem"}` to `"tools": {"bash": "svc-machine", "read_file": "svc-machine"}`.

**Step 6: Run all session-service tests**

```bash
cd services/session-service && uv run pytest tests/ -v --tb=short
```

Expected: ALL PASS

**Step 7: Commit**

```bash
cd services/session-service && git add tests/ && git commit -m "test(session): update test fixtures to use svc-machine instead of svc-bash/filesystem/search"
```

---

## Task 7: Fix root integration test references

**Files:**
- Modify: `tests/test_microservices_integration.py`
- Modify: `tests/test_docker_compose_phase2.py`
- Modify: `tests/test_docker_compose_phase3a.py`

**Step 1: Rewrite `tests/test_microservices_integration.py`**

This file tests the `svc-bash -> svc-machine` proxy chain, which no longer exists. The tests should be rewritten to test the consolidated machine service directly. The file currently imports `from svc_bash.app import create_bash_app` and `from svc_bash.tool import BashTool` — these modules no longer exist.

Rewrite the file to remove all svc-bash references. Keep the machine service contract tests (`TestServiceContracts`) and the machine file operations tests (`TestEndToEndExecution.test_machine_file_operations`). Remove or rewrite the bash proxy tests.

Replace the file content with:

```python
"""Integration tests for the consolidated svc-machine service.

After Phase 3, svc-bash/filesystem/search are gone. The machine service
handles all six tool operations directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_machine.service import create_machine_app


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with hello.txt and src/main.py."""
    (tmp_path / "hello.txt").write_text("Hello, World!")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')")
    return tmp_path


@pytest.fixture
def machine_client(workspace: Path) -> TestClient:
    """TestClient wrapping create_machine_app(workspace)."""
    app = create_machine_app(workspace)
    return TestClient(app)


class TestMachineServiceContract:
    """Verify that svc-machine implements the standard service contract."""

    def test_machine_healthz(self, machine_client: TestClient) -> None:
        """GET /healthz on svc-machine returns 200 with status='healthy'."""
        response = machine_client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_machine_describe(self, machine_client: TestClient) -> None:
        """GET /describe on svc-machine returns 200 with name='svc-machine'."""
        response = machine_client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "svc-machine"

    def test_machine_describe_advertises_all_tools(
        self, machine_client: TestClient
    ) -> None:
        """GET /describe lists all six consolidated machine tools."""
        response = machine_client.get("/describe")
        data = response.json()
        tool_names = {t["name"] for t in data.get("tools", [])}
        expected = {"bash", "read_file", "write_file", "edit_file", "grep", "glob"}
        assert expected == tool_names


class TestMachineFileOperations:
    """End-to-end tests for machine service file operations."""

    def test_exec(self, machine_client: TestClient) -> None:
        """POST /exec runs a command and returns stdout."""
        response = machine_client.post(
            "/exec", json={"command": "echo hello from machine"}
        )
        assert response.status_code == 200
        assert "hello from machine" in response.json()["stdout"]

    def test_file_read(
        self, machine_client: TestClient, workspace: Path
    ) -> None:
        """POST /files/read returns file content."""
        response = machine_client.post("/files/read", json={"path": "hello.txt"})
        assert response.status_code == 200
        assert "Hello, World!" in response.json()["content"]

    def test_file_write_and_read_back(
        self, machine_client: TestClient, workspace: Path
    ) -> None:
        """POST /files/write creates a file, POST /files/read reads it back."""
        machine_client.post(
            "/files/write",
            json={"path": "output.txt", "content": "written by test\n"},
        )
        assert (workspace / "output.txt").read_text() == "written by test\n"

    def test_file_list(self, machine_client: TestClient) -> None:
        """POST /files/list returns directory entries."""
        response = machine_client.post("/files/list", json={"path": "."})
        assert response.status_code == 200
        entry_names = [e["name"] for e in response.json()["entries"]]
        assert "hello.txt" in entry_names
        assert "src" in entry_names

    def test_file_glob(self, machine_client: TestClient) -> None:
        """POST /files/glob matches files by pattern."""
        response = machine_client.post(
            "/files/glob", json={"pattern": "**/*.py", "path": "."}
        )
        assert response.status_code == 200
        matches = response.json()["matches"]
        assert any("main.py" in m for m in matches)

    def test_file_grep(self, machine_client: TestClient) -> None:
        """POST /files/grep searches file contents."""
        response = machine_client.post(
            "/files/grep", json={"pattern": "print", "path": "src/main.py"}
        )
        assert response.status_code == 200
        grep_matches = response.json()["matches"]
        assert len(grep_matches) >= 1
        assert any("print" in m["content"] for m in grep_matches)

    def test_file_edit(
        self, machine_client: TestClient, workspace: Path
    ) -> None:
        """POST /files/edit replaces text in a file."""
        response = machine_client.post(
            "/files/edit",
            json={
                "path": "hello.txt",
                "old_string": "World",
                "new_string": "Microservices",
            },
        )
        assert response.status_code == 200
        assert response.json()["replacements_made"] >= 1
        assert "Microservices" in (workspace / "hello.txt").read_text()
```

**Step 2: Update `tests/test_docker_compose_phase2.py`**

This file references `svc-bash` in `PHASE2_SERVICES` and in several dependency assertions. Since the generated docker-compose.yaml now uses hash-suffixed names (e.g., `svc-machine-6719a84c`), these Phase 2 tests check a docker-compose structure that no longer matches reality.

The simplest fix: remove `"svc-bash"` from `PHASE2_SERVICES` (line 20) and update the dependency assertions:

- Line 20: Remove `"svc-bash",` from the list.
- Line 242: Change `for required in ["svc-context-dapr", "svc-mock-provider-dapr", "svc-bash-dapr"]:` to `for required in ["svc-context-dapr", "svc-mock-provider-dapr", "svc-machine-dapr"]:`.
- Lines 266–278: The `test_svc_bash_dapr_http_port_env` test checks `svc-bash` environment. Rename it to `test_svc_machine_dapr_http_port_env` and change `services["svc-bash"]` to `services["svc-machine"]`.

**Note:** The Phase 2 docker-compose tests use bare names like `svc-machine` — but the actual generated compose uses hash-suffixed names like `svc-machine-6719a84c`. If these tests were passing before by reading a hand-maintained docker-compose.yaml, they may now fail because `ampctl compose` generates hash-suffixed names. If so, update the test to look up services by prefix match instead of exact name match, or skip these legacy tests.

**Step 3: Update `tests/test_docker_compose_phase3a.py`**

Remove `"svc-filesystem"` and `"svc-search"` from the `TOOL_SERVICES` list (lines 19–20) and `MACHINE_DEPENDENT_TOOL_SERVICES` (lines 29–30). Update the `test_filesystem_and_search_depend_on_machine_dapr` test (line 192) to remove these assertions or replace them with a machine service assertion.

**Step 4: Run all root-level integration tests**

```bash
cd /data/labs/amplifier-ipc && uv run pytest tests/ -v --tb=short
```

Expected: ALL PASS (after the fixes above)

**Step 5: Commit**

```bash
git add tests/ && git commit -m "test: update integration tests for machine service consolidation"
```

---

## Task 8: Fix orchestrator and CLI test references

**Files:**
- Modify: `services/svc-orchestrator/tests/test_orchestrator.py`
- Modify: `services/svc-orchestrator/tests/test_orchestrator_usage.py`
- Modify: `amplifier-cli/tests/test_client_agent.py`

**Step 1: Update orchestrator tests**

In `services/svc-orchestrator/tests/test_orchestrator.py`, replace all occurrences of `"svc-bash"` with `"svc-machine"`. These are in routing table fixtures and mock invocation handlers:

```bash
cd services/svc-orchestrator && grep -n 'svc-bash' tests/test_orchestrator.py
```

Expected: ~15 matches. Use find-and-replace:

- Change `tools={"bash": "svc-bash"}` to `tools={"bash": "svc-machine"}` (multiple occurrences)
- Change `if app_id == "svc-bash"` to `if app_id == "svc-machine"` (multiple occurrences)
- Change `"svc-bash" not in invocation_log` to `"svc-machine" not in invocation_log`
- Change `http://svc-bash/tools/bash/execute` to `http://svc-machine/tools/bash/execute`
- Change `"Tool service 'svc-bash'` to `"Tool service 'svc-machine'`

**Step 2: Update orchestrator usage tests**

In `services/svc-orchestrator/tests/test_orchestrator_usage.py`:

- Line 43: Change `tools={"bash": "svc-bash"}` to `tools={"bash": "svc-machine"}`
- Line 195: Change `if app_id == "svc-bash"` to `if app_id == "svc-machine"`

**Step 3: Run orchestrator tests**

```bash
cd services/svc-orchestrator && uv run pytest tests/ -v --tb=short
```

Expected: ALL PASS

**Step 4: Update CLI agent tests**

In `amplifier-cli/tests/test_client_agent.py`:

- Line 60: Change `services=[{"id": "svc-bash"}]` to `services=[{"id": "svc-machine"}]`
- Line 66: Change `assert body["services"] == [{"id": "svc-bash"}]` to `assert body["services"] == [{"id": "svc-machine"}]`

**Step 5: Run CLI tests**

```bash
cd amplifier-cli && uv run pytest tests/ -v --tb=short
```

Expected: ALL PASS

**Step 6: Commit**

```bash
git add services/svc-orchestrator/tests/ amplifier-cli/tests/ && git commit -m "test: replace svc-bash references with svc-machine in orchestrator and CLI tests"
```

---

## Task 9: Fix ampctl test references

**Files:**
- Modify: `ampctl/tests/test_hasher.py`
- Modify: `ampctl/tests/test_compose.py`
- Modify: `ampctl/tests/test_service_map.py`

**Step 1: Update test_hasher.py**

In `ampctl/tests/test_hasher.py`:

- Line 24: Change `assert name.startswith("svc-bash-")` to `assert name.startswith("svc-machine-")` (and update the input to the hash function accordingly — the test generates a name from a role key and build path). Read the test first to understand what input is used.

**Step 2: Update test_compose.py**

In `ampctl/tests/test_compose.py`:

- Line 200: Change `orchestrator=ServiceEntry(build="./services/svc-bash")` to `orchestrator=ServiceEntry(build="./services/svc-machine")`.
- Line 212: Change the dockerfile assertion to match `services/svc-machine/Dockerfile`.
- Line 268: Change `"bash": ServiceEntry(build="./services/svc-bash", depends_on=["machine"])` to remove it or change the build path.

Read the file fully first to understand the test context before making changes — these are testing ampctl's compose generation logic with specific fixtures.

**Step 3: Update test_service_map.py**

In `ampctl/tests/test_service_map.py`:

- Line 76: Change `behaviors={"search": "svc-search-11223344"}` to `behaviors={"machine": "svc-machine-11223344"}`.
- Line 87: Change `assert loaded.agents["my-agent"].behaviors["search"] == "svc-search-11223344"` to `assert loaded.agents["my-agent"].behaviors["machine"] == "svc-machine-11223344"`.

**Step 4: Run ampctl tests**

```bash
cd ampctl && uv run pytest tests/ -v --tb=short
```

Expected: ALL PASS

**Step 5: Commit**

```bash
cd ampctl && git add tests/ && git commit -m "test(ampctl): replace old service references in test fixtures"
```

---

## Task 10: Update root pyproject.toml — remove old service pythonpath entries

**Files:**
- Modify: `pyproject.toml` (root)

**Step 1: Read the relevant sections**

```bash
grep -n 'svc-bash\|svc-filesystem\|svc-search' pyproject.toml
```

Expected: 6 matches — 3 in the `pythonpath` list and 3 in another `pythonpath` or `sources` list.

**Step 2: Remove the old service paths**

Remove these lines from `pyproject.toml`:

```
    "services/svc-bash/src",
    "services/svc-filesystem/src",
    "services/svc-search/src",
```

There are two sets (around lines 34 and 63–69). Remove all six lines.

**Step 3: Verify pyproject.toml is still valid**

```bash
python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('TOML valid')"
```

Expected: `TOML valid`

**Step 4: Commit**

```bash
git add pyproject.toml && git commit -m "build: remove svc-bash/filesystem/search from root pyproject.toml pythonpath"
```

---

## Task 11: Update AGENTS.md

**Files:**
- Modify: `.amplifier/AGENTS.md`

**Step 1: Update the architecture diagram**

In `.amplifier/AGENTS.md`, change line 99 from:

```
    --> svc-bash, svc-filesystem, svc-search, svc-web, etc. (tools) --> svc-machine (filesystem)
```

to:

```
    --> svc-machine (bash, filesystem, search), svc-web, etc. (tools)
```

**Step 2: Update the workspace layout**

In the workspace layout section (lines 68–71), replace:

```
  svc-machine/            Machine abstraction (filesystem + command execution). Volume-mounted workspace in local mode.
  svc-bash/               BashTool -- calls svc-machine /exec.
  svc-filesystem/         ReadFileTool, WriteFileTool, EditFileTool -- calls svc-machine /files/*.
  svc-search/             GrepTool, GlobTool -- calls svc-machine /files/grep, /files/glob.
```

with:

```
  svc-machine/            Consolidated machine service (bash, read_file, write_file, edit_file, grep, glob). Per-session instances via SSH/SFTP or local driver.
```

**Step 3: Update the key patterns section**

In line 108, change:

```
- **Tool services** call svc-machine via Dapr SI for filesystem/command access. They never touch the filesystem directly.
```

to:

```
- **Machine tools** (bash, read_file, write_file, edit_file, grep, glob) are consolidated in svc-machine with per-session instance management. Other tool services (web, skills, etc.) are standalone.
```

**Step 4: Update the container count**

In line 11, change `~29 services` to `~26 services` (3 services removed: svc-bash, svc-filesystem, svc-search).

**Step 5: Commit**

```bash
git add .amplifier/AGENTS.md && git commit -m "docs: update AGENTS.md for machine service consolidation"
```

---

## Task 12: Update README.md

**Files:**
- Modify: `README.md`

**Step 1: Update the architecture diagram**

In `README.md`, find the line (around line 14):

```
    --> svc-bash, svc-filesystem, svc-search, svc-web, etc. (tools) --> svc-machine (filesystem)
```

Replace with:

```
    --> svc-machine (bash, filesystem, search), svc-web, etc. (tools)
```

**Step 2: Update the workspace layout section**

Find the lines (around lines 65–67):

```
  svc-bash/               BashTool -- calls svc-machine /exec.
  svc-filesystem/         ReadFileTool, WriteFileTool, EditFileTool -- calls svc-machine /files/*.
  svc-search/             GrepTool, GlobTool -- calls svc-machine /files/grep, /files/glob.
```

Replace with:

```
  svc-machine/            Consolidated machine service (bash, read_file, write_file, edit_file, grep, glob).
```

**Step 3: Update any `cd services/svc-bash` example**

Find line 146 (`cd services/svc-bash`) and change it to `cd services/svc-machine`.

**Step 4: Commit**

```bash
git add README.md && git commit -m "docs: update README.md for machine service consolidation"
```

---

## Task 13: Update the spec document

**Files:**
- Modify: `docs/specs/amplifier-spec.md`

**Step 1: Update the /describe example**

At line 175, change:

```json
  "name": "svc-filesystem",
```

to:

```json
  "name": "svc-machine",
```

And update the tools list in the example to include all six machine tools: `bash`, `read_file`, `write_file`, `edit_file`, `grep`, `glob`.

**Step 2: Update the service invocation pattern**

At lines 295–298, change:

```
Orchestrator --[Dapr SI]--> svc-bash /tools/bash/execute
Orchestrator --[Dapr SI]--> svc-providers /providers/anthropic/complete
Orchestrator --[Dapr SI]--> svc-modes /hooks/mode/invoke
svc-bash     --[Dapr SI]--> svc-machine /exec
```

to:

```
Orchestrator --[Dapr SI]--> svc-machine /tools/bash/execute
Orchestrator --[Dapr SI]--> svc-providers /providers/anthropic/complete
Orchestrator --[Dapr SI]--> svc-modes /hooks/mode/invoke
```

(Remove the `svc-bash --> svc-machine` line entirely — the proxy hop no longer exists.)

**Step 3: Update the service inventory table**

At lines 385–387, remove the three rows:

```
| `svc-bash` | (tool) | BashTool |
| `svc-filesystem` | (tool) | ReadTool, WriteTool, EditTool |
| `svc-search` | (tool) | GrepTool, GlobTool |
```

And update the `svc-machine` entry in the Infrastructure section (line 422) to:

```
| `svc-machine` | Consolidated machine service: bash, read_file, write_file, edit_file, grep, glob. Per-session instances via SSH/SFTP driver. |
```

**Step 4: Update the individual service sections**

At lines 521–543, replace the three sections:

```
#### svc-bash
Shell command execution (calls Machine Service).
| Component Type | Names |
|---|---|
| Tool | `bash` |

#### svc-filesystem
File read/write/edit (calls Machine Service).
| Component Type | Names |
|---|---|
| Tools | `read_file`, `write_file`, `edit_file` |

#### svc-search
File search and discovery (calls Machine Service).
| Component Type | Names |
|---|---|
| Tools | `grep`, `glob` |
```

with a single consolidated section:

```
#### svc-machine

Consolidated machine service — shell execution, file operations, and search.
Provides per-session instances via an abstract driver interface (SSH/SFTP for
local and remote, future S3 for cloud storage).

| Component Type | Names |
|---|---|
| Tools | `bash`, `read_file`, `write_file`, `edit_file`, `grep`, `glob` |
```

**Step 5: Update the container count**

At line 426, change `~29 application containers` to `~26 application containers`.

**Step 6: Commit**

```bash
git add docs/specs/amplifier-spec.md && git commit -m "docs: update amplifier-spec.md for machine service consolidation"
```

---

## Task 14: Final grep and comprehensive verification

**Files:** No new files — verification step.

**Step 1: Grep for any remaining references to old services in source code**

```bash
grep -rn 'svc-bash\|svc-filesystem\|svc-search' --include='*.py' --include='*.yaml' --include='*.toml' --include='*.md' . \
  | grep -v 'docs/plans/' \
  | grep -v 'docs/design/' \
  | grep -v 'working/' \
  | grep -v 'related-projects/' \
  | grep -v 'ampctl/docker-compose.yaml' \
  | grep -v '.git/'
```

Expected: No matches in active source code. Matches in `docs/plans/` and `docs/design/` are acceptable (historical records). Matches in `ampctl/docker-compose.yaml` should have been cleared by Task 3's regeneration; if not, regenerate again.

**Step 2: Run the full test suite across all services**

```bash
cd /data/labs/amplifier-ipc

# Machine service
cd services/svc-machine && uv run pytest tests/ -v --tb=short && cd ../..

# Session service
cd services/session-service && uv run pytest tests/ -v --tb=short && cd ../..

# Orchestrator
cd services/svc-orchestrator && uv run pytest tests/ -v --tb=short && cd ../..

# CLI
cd amplifier-cli && uv run pytest tests/ -v --tb=short && cd ..

# ampctl
cd ampctl && uv run pytest tests/ -v --tb=short && cd ..

# Root integration tests
uv run pytest tests/ -v --tb=short
```

Expected: ALL PASS across all test suites.

**Step 3: Run linting on all changed files**

```bash
cd /data/labs/amplifier-ipc
ruff check services/session-service/src/ services/session-service/tests/ \
  services/svc-orchestrator/tests/ amplifier-cli/tests/ ampctl/tests/ tests/ \
  && ruff format --check services/session-service/src/ services/session-service/tests/ \
  services/svc-orchestrator/tests/ amplifier-cli/tests/ ampctl/tests/ tests/
```

Fix any lint or format issues found.

**Step 4: Commit any fixes**

```bash
git add -A && git commit -m "fix: final lint and reference cleanup for Phase 3 consolidation"
```

(Skip this commit if no fixes were needed.)

---

## Summary

After completing all 14 tasks, the machine service consolidation is complete:

1. **Agent definitions** (`foundation.yaml`, `default.yaml`) — bash, filesystem, and search behaviors removed. Machine is the only behavior for exec/file/search operations.

2. **Docker compose** — Regenerated without svc-bash, svc-filesystem, svc-search. Net reduction of 6 containers (3 services + 3 Dapr sidecars).

3. **Service directories** — `services/svc-bash/`, `services/svc-filesystem/`, `services/svc-search/` deleted entirely.

4. **Session-service** — `DEFAULT_SERVICES` and `AGENTS` dict updated to reference `svc-machine` instead of the three old services.

5. **All tests** — Updated across session-service, orchestrator, CLI, ampctl, and root integration tests to use `svc-machine` instead of `svc-bash`/`svc-filesystem`/`svc-search`.

6. **Root config** — `pyproject.toml` pythonpath entries cleaned up.

7. **Documentation** — `AGENTS.md`, `README.md`, and `amplifier-spec.md` updated to reflect the consolidated architecture.

8. **Zero stale references** — No remaining references to `svc-bash`, `svc-filesystem`, or `svc-search` in active source code.

**The system is now fully consolidated.** The machine service handles all six tool operations through per-session instances, the docker-compose stack is 6 containers lighter, and the codebase has no dead references to the removed services.