# Agent Definition System & ampctl Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the agent definition system and `ampctl` management CLI so that agents are defined in YAML files instead of hardcoded Python, and `docker-compose.yaml` is a generated artifact produced from those definitions.

**Architecture:** A new `ampctl` CLI package validates agent definition YAML files, caches them under `~/.amplifier/agents/`, generates deterministic docker-compose service names via SHA-256 hashing of image URIs, maintains a `service-map.yaml` mapping behavior keys to Dapr app-ids, and generates a complete `docker-compose.yaml`. The session-service is updated to load agent config from these YAML files instead of the hardcoded `agents.py` registry.

**Tech Stack:** Python 3.12, Click (CLI), Pydantic v2 (models), PyYAML, hatchling (build)

**Design Reference:** `docs/design/agent-definitions-and-ampctl.md`

---

## File Structure

### New Package: `ampctl/`

| File | Responsibility |
|------|---------------|
| `ampctl/pyproject.toml` | Package config, `ampctl` CLI entry point |
| `ampctl/src/ampctl/__init__.py` | Package init |
| `ampctl/src/ampctl/main.py` | Click CLI group and command wiring |
| `ampctl/src/ampctl/models.py` | Pydantic v2 models for agent definitions and service-map |
| `ampctl/src/ampctl/parser.py` | YAML loading, validation, fetching from URI |
| `ampctl/src/ampctl/hasher.py` | Deterministic service name generation |
| `ampctl/src/ampctl/service_map.py` | Service-map CRUD (read/write/update `service-map.yaml`) |
| `ampctl/src/ampctl/compose.py` | Docker-compose YAML generation from all installed agents |
| `ampctl/src/ampctl/paths.py` | `~/.amplifier/` path conventions |
| `ampctl/tests/test_models.py` | Model validation tests |
| `ampctl/tests/test_parser.py` | Parser tests |
| `ampctl/tests/test_hasher.py` | Hash determinism and format tests |
| `ampctl/tests/test_service_map.py` | Service-map read/write tests |
| `ampctl/tests/test_compose.py` | Compose generation tests |
| `ampctl/tests/test_cli.py` | CLI integration tests |

### Modified: `services/session-service/`

| File | Change |
|------|--------|
| `services/session-service/src/session_service/agents.py` | Rewrite: load from YAML + service-map, fallback to hardcoded |
| `services/session-service/tests/test_agents.py` | New: tests for YAML-based resolution |

### New: `agents/`

| File | Purpose |
|------|---------|
| `agents/foundation.yaml` | Foundation agent definition (mirrors current hardcoded config) |
| `agents/default.yaml` | Default agent with mock provider for testing |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `ampctl/pyproject.toml`
- Create: `ampctl/src/ampctl/__init__.py`
- Create: `ampctl/src/ampctl/paths.py`
- Create: `ampctl/tests/__init__.py`

- [ ] **Step 1: Create ampctl package directory structure**

```bash
mkdir -p ampctl/src/ampctl ampctl/tests
```

- [ ] **Step 2: Write pyproject.toml**

Create `ampctl/pyproject.toml`:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ampctl"
version = "0.1.0"
description = "Management CLI for Amplifier agent definitions and infrastructure"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "httpx>=0.28",
    "rich>=13.0.0",
]

[project.scripts]
ampctl = "ampctl.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src/ampctl"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.12"
extraPaths = ["src"]

[dependency-groups]
dev = [
    "pytest>=8.0",
]
```

- [ ] **Step 3: Write `__init__.py`**

Create `ampctl/src/ampctl/__init__.py`:
```python
"""ampctl -- Management CLI for Amplifier agent definitions."""
```

- [ ] **Step 4: Write paths module**

Create `ampctl/src/ampctl/paths.py`:
```python
"""Conventional paths under ~/.amplifier/ for ampctl artifacts."""

from __future__ import annotations

from pathlib import Path


def amplifier_home() -> Path:
    """Return the Amplifier home directory, defaulting to ~/.amplifier."""
    import os
    return Path(os.environ.get("AMPLIFIER_HOME", Path.home() / ".amplifier"))


def agents_dir() -> Path:
    """Return the directory where cached agent definitions live."""
    return amplifier_home() / "agents"


def service_map_path() -> Path:
    """Return the path to the service-map.yaml file."""
    return amplifier_home() / "service-map.yaml"
```

- [ ] **Step 5: Create empty test init**

Create `ampctl/tests/__init__.py` (empty file).

- [ ] **Step 6: Verify the package structure**

```bash
cd ampctl && uv sync && uv run python -c "from ampctl.paths import agents_dir; print(agents_dir())"
```

Expected: prints `~/.amplifier/agents` equivalent path.

- [ ] **Step 7: Commit**

```bash
git add ampctl/
git commit -m "feat(ampctl): scaffold ampctl package with paths module"
```

---

## Task 2: Agent Definition Models

**Files:**
- Create: `ampctl/src/ampctl/models.py`
- Create: `ampctl/tests/test_models.py`

- [ ] **Step 1: Write failing tests for agent definition models**

Create `ampctl/tests/test_models.py`:
```python
"""Tests for agent definition Pydantic models."""

import pytest
from ampctl.models import AgentDefinition, ServiceEntry, ServiceMapEntry, ServiceMap


def test_minimal_agent_definition():
    """An agent with only required fields should validate."""
    defn = AgentDefinition(
        ref="test-agent",
        orchestrator=ServiceEntry(image="ghcr.io/test/orch:latest"),
        context_manager=ServiceEntry(image="ghcr.io/test/ctx:latest"),
        providers=ServiceEntry(image="ghcr.io/test/prov:latest"),
    )
    assert defn.ref == "test-agent"
    assert defn.description is None
    assert defn.instruction is None
    assert defn.behaviors == {}


def test_full_agent_definition():
    """An agent with all fields should validate."""
    defn = AgentDefinition(
        ref="foundation",
        description="Full-featured foundation agent",
        instruction="You are Amplifier.",
        orchestrator=ServiceEntry(image="ghcr.io/test/orch:latest"),
        context_manager=ServiceEntry(image="ghcr.io/test/ctx:latest"),
        providers=ServiceEntry(
            image="ghcr.io/test/prov:latest",
            environment={"ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"},
        ),
        behaviors={
            "bash": ServiceEntry(image="ghcr.io/test/bash:latest"),
            "skills": ServiceEntry(
                image="ghcr.io/test/skills:latest",
                config={"visibility": "full"},
            ),
        },
    )
    assert defn.ref == "foundation"
    assert len(defn.behaviors) == 2
    assert defn.behaviors["skills"].config == {"visibility": "full"}


def test_service_entry_with_build():
    """A service entry with build instead of image should validate."""
    entry = ServiceEntry(build="./services/my-tool")
    assert entry.build == "./services/my-tool"
    assert entry.image is None


def test_service_entry_with_build_dict():
    """A service entry with build as dict (context + dockerfile) should validate."""
    entry = ServiceEntry(build={"context": "../experiments", "dockerfile": "hooks/Dockerfile"})
    assert entry.build["context"] == "../experiments"


def test_service_entry_requires_image_or_build():
    """A service entry with neither image nor build should fail."""
    with pytest.raises(ValueError):
        ServiceEntry()


def test_service_map_round_trip():
    """A service map should serialize and deserialize."""
    sm = ServiceMap(agents={
        "foundation": ServiceMapEntry(
            orchestrator="svc-orchestrator-c7f9a3e2",
            context_manager="svc-context-d8b4c5f6",
            providers="svc-providers-e9c1a2b3",
            behaviors={"bash": "svc-bash-a3f2b1c4"},
        ),
    })
    assert sm.agents["foundation"].orchestrator == "svc-orchestrator-c7f9a3e2"
    d = sm.model_dump()
    sm2 = ServiceMap.model_validate(d)
    assert sm2.agents["foundation"].behaviors["bash"] == "svc-bash-a3f2b1c4"


def test_all_service_entries_from_definition():
    """all_service_entries() should yield every service in the definition."""
    defn = AgentDefinition(
        ref="test",
        orchestrator=ServiceEntry(image="ghcr.io/test/orch:latest"),
        context_manager=ServiceEntry(image="ghcr.io/test/ctx:latest"),
        providers=ServiceEntry(image="ghcr.io/test/prov:latest"),
        behaviors={"bash": ServiceEntry(image="ghcr.io/test/bash:latest")},
    )
    entries = list(defn.all_service_entries())
    # Should have: orchestrator, context_manager, providers, bash = 4
    assert len(entries) == 4
    roles = [role for role, _ in entries]
    assert "orchestrator" in roles
    assert "bash" in roles
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ampctl && uv run pytest tests/test_models.py -v
```

Expected: ImportError -- `ampctl.models` does not exist.

- [ ] **Step 3: Implement the models**

Create `ampctl/src/ampctl/models.py`:
```python
"""Pydantic v2 models for agent definitions and service maps."""

from __future__ import annotations

from typing import Iterator

from pydantic import BaseModel, model_validator


class ServiceEntry(BaseModel):
    """A single service reference in an agent definition."""

    image: str | None = None
    build: str | dict | None = None
    config: dict | None = None
    environment: dict[str, str] | None = None
    volumes: list[str] | None = None

    @model_validator(mode="after")
    def _require_image_or_build(self) -> ServiceEntry:
        if not self.image and not self.build:
            raise ValueError("ServiceEntry requires either 'image' or 'build'")
        return self

    @property
    def source_key(self) -> str:
        """Return the image URI or build path used for hashing."""
        if self.image:
            return self.image
        if isinstance(self.build, str):
            return self.build
        if isinstance(self.build, dict):
            return self.build.get("context", "") + ":" + self.build.get("dockerfile", "Dockerfile")
        raise ValueError("No image or build source")


class AgentDefinition(BaseModel):
    """Top-level agent definition -- the only definition file type."""

    ref: str
    description: str | None = None
    instruction: str | None = None
    orchestrator: ServiceEntry
    context_manager: ServiceEntry
    providers: ServiceEntry
    behaviors: dict[str, ServiceEntry] = {}

    def all_service_entries(self) -> Iterator[tuple[str, ServiceEntry]]:
        """Yield (role_name, entry) for every service in this definition."""
        yield "orchestrator", self.orchestrator
        yield "context_manager", self.context_manager
        yield "providers", self.providers
        for key, entry in self.behaviors.items():
            yield key, entry


class AgentDefinitionFile(BaseModel):
    """Wrapper for the top-level YAML structure: ``agent: {...}``."""

    agent: AgentDefinition


class ServiceMapEntry(BaseModel):
    """Maps an agent's roles/behaviors to generated Dapr app-ids."""

    orchestrator: str
    context_manager: str
    providers: str
    behaviors: dict[str, str] = {}

    def all_app_ids(self) -> list[str]:
        """Return all Dapr app-ids for this agent."""
        return [self.orchestrator, self.context_manager, self.providers] + list(self.behaviors.values())


class ServiceMap(BaseModel):
    """Top-level service-map.yaml structure."""

    agents: dict[str, ServiceMapEntry] = {}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ampctl && uv run pytest tests/test_models.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ampctl/src/ampctl/models.py ampctl/tests/test_models.py
git commit -m "feat(ampctl): add Pydantic models for agent definitions and service maps"
```

---

## Task 3: YAML Parser and Validator

**Files:**
- Create: `ampctl/src/ampctl/parser.py`
- Create: `ampctl/tests/test_parser.py`

- [ ] **Step 1: Write failing tests for parser**

Create `ampctl/tests/test_parser.py`:
```python
"""Tests for YAML parsing and validation."""

import pytest
from pathlib import Path
from ampctl.parser import parse_agent_definition, fetch_definition
from ampctl.models import AgentDefinition

VALID_YAML = """\
agent:
  ref: test-agent
  description: A test agent
  instruction: You are a test agent.
  orchestrator:
    image: ghcr.io/test/orch:latest
  context_manager:
    image: ghcr.io/test/ctx:latest
  providers:
    image: ghcr.io/test/prov:latest
  behaviors:
    bash:
      image: ghcr.io/test/bash:latest
    skills:
      image: ghcr.io/test/skills:latest
      config:
        visibility: full
"""

INVALID_YAML_NO_AGENT = """\
ref: test-agent
orchestrator:
  image: ghcr.io/test/orch:latest
"""

INVALID_YAML_MISSING_ORCH = """\
agent:
  ref: test-agent
  context_manager:
    image: ghcr.io/test/ctx:latest
  providers:
    image: ghcr.io/test/prov:latest
"""


def test_parse_valid_definition():
    defn = parse_agent_definition(VALID_YAML)
    assert defn.ref == "test-agent"
    assert defn.instruction == "You are a test agent."
    assert "bash" in defn.behaviors
    assert defn.behaviors["skills"].config == {"visibility": "full"}


def test_parse_missing_agent_key():
    with pytest.raises(ValueError, match="agent"):
        parse_agent_definition(INVALID_YAML_NO_AGENT)


def test_parse_missing_required_field():
    with pytest.raises(Exception):
        parse_agent_definition(INVALID_YAML_MISSING_ORCH)


def test_fetch_definition_from_file(tmp_path: Path):
    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text(VALID_YAML)
    defn = fetch_definition(str(yaml_file))
    assert defn.ref == "test-agent"


def test_fetch_definition_missing_file():
    with pytest.raises(FileNotFoundError):
        fetch_definition("/nonexistent/path.yaml")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ampctl && uv run pytest tests/test_parser.py -v
```

- [ ] **Step 3: Implement the parser**

Create `ampctl/src/ampctl/parser.py`:
```python
"""YAML parsing and validation for agent definitions."""

from __future__ import annotations

from pathlib import Path

import yaml

from ampctl.models import AgentDefinition, AgentDefinitionFile


def parse_agent_definition(yaml_content: str) -> AgentDefinition:
    """Parse YAML content into a validated AgentDefinition."""
    data = yaml.safe_load(yaml_content)
    if not isinstance(data, dict) or "agent" not in data:
        raise ValueError("Agent definition YAML must have a top-level 'agent' key")
    wrapper = AgentDefinitionFile.model_validate(data)
    return wrapper.agent


def fetch_definition(uri: str) -> AgentDefinition:
    """Fetch and parse an agent definition from a URI (file path or HTTPS URL).

    Supports:
      - Local file paths (absolute or relative)
      - HTTPS URLs (fetched via httpx)
    """
    if uri.startswith("https://") or uri.startswith("http://"):
        import httpx
        resp = httpx.get(uri, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        return parse_agent_definition(resp.text)

    path = Path(uri).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Agent definition not found: {path}")
    return parse_agent_definition(path.read_text())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ampctl && uv run pytest tests/test_parser.py -v
```

- [ ] **Step 5: Commit**

```bash
git add ampctl/src/ampctl/parser.py ampctl/tests/test_parser.py
git commit -m "feat(ampctl): add YAML parser and validator for agent definitions"
```

---

## Task 4: Deterministic Service Name Hashing

**Files:**
- Create: `ampctl/src/ampctl/hasher.py`
- Create: `ampctl/tests/test_hasher.py`

- [ ] **Step 1: Write failing tests for hasher**

Create `ampctl/tests/test_hasher.py`:
```python
"""Tests for deterministic service name hashing."""

from ampctl.hasher import generate_service_name, hash_source


def test_hash_determinism():
    """Same input always produces same hash."""
    h1 = hash_source("ghcr.io/payneio/amplifier-svc-bash:latest")
    h2 = hash_source("ghcr.io/payneio/amplifier-svc-bash:latest")
    assert h1 == h2
    assert len(h1) == 8


def test_hash_different_inputs():
    """Different inputs produce different hashes."""
    h1 = hash_source("ghcr.io/payneio/amplifier-svc-bash:latest")
    h2 = hash_source("ghcr.io/payneio/amplifier-svc-search:latest")
    assert h1 != h2


def test_generate_service_name_format():
    """Service names should be human-readable: svc-<prefix>-<hash>."""
    name = generate_service_name("bash", "ghcr.io/payneio/amplifier-svc-bash:latest")
    assert name.startswith("svc-bash-")
    assert len(name.split("-")) >= 3
    # Hash suffix should be 8 hex chars
    suffix = name.split("-", 2)[-1]
    assert len(suffix) == 8
    int(suffix, 16)  # Should not raise -- it's valid hex


def test_generate_service_name_with_build_path():
    """Build paths should also produce valid service names."""
    name = generate_service_name("my-tool", "./services/my-tool")
    assert name.startswith("svc-my-tool-")


def test_same_image_same_name():
    """Two behaviors using the same image get the same service name."""
    n1 = generate_service_name("bash", "ghcr.io/test/bash:latest")
    n2 = generate_service_name("shell", "ghcr.io/test/bash:latest")
    # The hash part is the same (same image), but the prefix differs
    hash1 = n1.rsplit("-", 1)[-1]
    hash2 = n2.rsplit("-", 1)[-1]
    assert hash1 == hash2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ampctl && uv run pytest tests/test_hasher.py -v
```

- [ ] **Step 3: Implement the hasher**

Create `ampctl/src/ampctl/hasher.py`:
```python
"""Deterministic service name generation via SHA-256 hashing."""

from __future__ import annotations

import hashlib


def hash_source(source_key: str) -> str:
    """Return first 8 hex chars of SHA-256 hash of the source key."""
    return hashlib.sha256(source_key.encode()).hexdigest()[:8]


def generate_service_name(role_key: str, source_key: str) -> str:
    """Generate a human-readable docker-compose service name.

    Format: ``svc-<role_key>-<hash>``

    Args:
        role_key: Human-readable label (e.g. "bash", "orchestrator").
        source_key: The image URI or build path to hash.
    """
    h = hash_source(source_key)
    return f"svc-{role_key}-{h}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ampctl && uv run pytest tests/test_hasher.py -v
```

- [ ] **Step 5: Commit**

```bash
git add ampctl/src/ampctl/hasher.py ampctl/tests/test_hasher.py
git commit -m "feat(ampctl): add deterministic service name hashing"
```

---

## Task 5: Service Map Management

**Files:**
- Create: `ampctl/src/ampctl/service_map.py`
- Create: `ampctl/tests/test_service_map.py`

- [ ] **Step 1: Write failing tests for service map**

Create `ampctl/tests/test_service_map.py`:
```python
"""Tests for service-map CRUD operations."""

from pathlib import Path
from ampctl.service_map import load_service_map, save_service_map, build_service_map_entry
from ampctl.models import ServiceMap, ServiceMapEntry, AgentDefinition, ServiceEntry


def _make_agent() -> AgentDefinition:
    return AgentDefinition(
        ref="test-agent",
        orchestrator=ServiceEntry(image="ghcr.io/test/orch:latest"),
        context_manager=ServiceEntry(image="ghcr.io/test/ctx:latest"),
        providers=ServiceEntry(image="ghcr.io/test/prov:latest"),
        behaviors={
            "bash": ServiceEntry(image="ghcr.io/test/bash:latest"),
            "skills": ServiceEntry(image="ghcr.io/test/skills:latest"),
        },
    )


def test_build_service_map_entry():
    agent = _make_agent()
    entry = build_service_map_entry(agent)
    assert entry.orchestrator.startswith("svc-orchestrator-")
    assert entry.context_manager.startswith("svc-context-manager-")
    assert entry.providers.startswith("svc-providers-")
    assert "bash" in entry.behaviors
    assert entry.behaviors["bash"].startswith("svc-bash-")


def test_load_empty_service_map(tmp_path: Path):
    sm = load_service_map(tmp_path / "nonexistent.yaml")
    assert sm.agents == {}


def test_save_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "service-map.yaml"
    sm = ServiceMap(agents={
        "test": ServiceMapEntry(
            orchestrator="svc-orch-12345678",
            context_manager="svc-ctx-12345678",
            providers="svc-prov-12345678",
            behaviors={"bash": "svc-bash-12345678"},
        ),
    })
    save_service_map(sm, path)
    loaded = load_service_map(path)
    assert loaded.agents["test"].orchestrator == "svc-orch-12345678"
    assert loaded.agents["test"].behaviors["bash"] == "svc-bash-12345678"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ampctl && uv run pytest tests/test_service_map.py -v
```

- [ ] **Step 3: Implement service map module**

Create `ampctl/src/ampctl/service_map.py`:
```python
"""Service-map CRUD -- maps agent behavior keys to Dapr app-ids."""

from __future__ import annotations

from pathlib import Path

import yaml

from ampctl.hasher import generate_service_name
from ampctl.models import AgentDefinition, ServiceMap, ServiceMapEntry


def build_service_map_entry(agent: AgentDefinition) -> ServiceMapEntry:
    """Build a ServiceMapEntry by hashing all service sources in an agent definition."""
    behaviors = {}
    for key, entry in agent.behaviors.items():
        behaviors[key] = generate_service_name(key, entry.source_key)

    return ServiceMapEntry(
        orchestrator=generate_service_name("orchestrator", agent.orchestrator.source_key),
        context_manager=generate_service_name("context-manager", agent.context_manager.source_key),
        providers=generate_service_name("providers", agent.providers.source_key),
        behaviors=behaviors,
    )


def load_service_map(path: Path) -> ServiceMap:
    """Load a service map from YAML. Returns empty ServiceMap if file doesn't exist."""
    if not path.exists():
        return ServiceMap()
    data = yaml.safe_load(path.read_text())
    if not data:
        return ServiceMap()
    return ServiceMap.model_validate(data)


def save_service_map(sm: ServiceMap, path: Path) -> None:
    """Write a service map to YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(sm.model_dump(), default_flow_style=False, sort_keys=False))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ampctl && uv run pytest tests/test_service_map.py -v
```

- [ ] **Step 5: Commit**

```bash
git add ampctl/src/ampctl/service_map.py ampctl/tests/test_service_map.py
git commit -m "feat(ampctl): add service-map CRUD operations"
```

---

## Task 6: Docker Compose Generator

**Files:**
- Create: `ampctl/src/ampctl/compose.py`
- Create: `ampctl/tests/test_compose.py`

- [ ] **Step 1: Write failing tests for compose generation**

Create `ampctl/tests/test_compose.py`. Tests should verify: a generated compose dict has redis, session-service, all agent services with Dapr sidecars, deduplication of shared images, and correct env/volume pass-through.

Key test cases:
- `test_generate_compose_single_agent` -- one agent produces correct services + sidecars
- `test_generate_compose_deduplication` -- two agents sharing the same image produce only one service entry
- `test_compose_includes_redis` -- redis always present
- `test_compose_includes_session_service` -- session-service always present with correct depends_on
- `test_compose_environment_passthrough` -- env vars from definition appear on service
- `test_compose_volume_passthrough` -- volumes from definition appear on service
- `test_compose_dapr_sidecar` -- each service gets a matching `-dapr` sidecar entry

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ampctl && uv run pytest tests/test_compose.py -v
```

- [ ] **Step 3: Implement compose generator**

Create `ampctl/src/ampctl/compose.py`. The `generate_compose()` function takes a dict of `{name: (AgentDefinition, ServiceMapEntry)}` and produces a complete docker-compose dict. Key logic:

- Start with redis service (image: redis:7-alpine, port 6379)
- Iterate all agents, all their service entries. For each unique source_key (dedup by hash):
  - Generate app service entry (image or build, environment, volumes, depends_on redis)
  - Generate dapr sidecar entry (image: daprio/daprd:1.14.4, command with --app-id, network_mode: service:<app>)
- Add session-service entry (build from local, exposed port, depends_on all services, env vars for AMPLIFIER_AGENTS_DIR and ORCHESTRATOR_DIRECT_URL)
- Add session-service dapr sidecar
- Write as `docker-compose.yaml` via `yaml.dump()`

The function signature:
```python
def generate_compose(
    agents: dict[str, tuple[AgentDefinition, ServiceMapEntry]],
    session_service_build: str = ".",
    dapr_image: str = "daprio/daprd:1.14.4",
) -> dict:
    """Generate a complete docker-compose dict from installed agents."""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ampctl && uv run pytest tests/test_compose.py -v
```

- [ ] **Step 5: Commit**

```bash
git add ampctl/src/ampctl/compose.py ampctl/tests/test_compose.py
git commit -m "feat(ampctl): add docker-compose generator with deduplication"
```

---

## Task 7: ampctl CLI Commands

**Files:**
- Create: `ampctl/src/ampctl/main.py`
- Create: `ampctl/tests/test_cli.py`

- [ ] **Step 1: Write failing tests for CLI commands**

Create `ampctl/tests/test_cli.py` using Click's `CliRunner`. Test:
- `ampctl add ./path.yaml agent-name` -- caches definition, updates service-map
- `ampctl add` with existing name -- error message
- `ampctl list` -- shows installed agents in a table
- `ampctl remove agent-name` -- removes from cache and service-map
- `ampctl compose` -- generates docker-compose.yaml
- `ampctl inspect agent-name` -- shows services for an agent

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ampctl && uv run pytest tests/test_cli.py -v
```

- [ ] **Step 3: Implement CLI commands**

Create `ampctl/src/ampctl/main.py` with Click commands:

```python
"""ampctl -- Management CLI for Amplifier agent definitions."""

from __future__ import annotations

import click
# Commands: add, list, remove, compose, inspect, update
```

Each command should:
- `add <uri> <name>`: fetch_definition(uri), validate, copy to agents_dir()/<name>.yaml, build_service_map_entry, update service-map.yaml
- `list`: read agents_dir(), show table with ref, description, service count
- `remove <name>`: delete from agents_dir() and service-map
- `compose`: load all agent definitions + service-map, call generate_compose(), write docker-compose.yaml
- `inspect <name>`: load definition, show all services and their images
- `update <name>`: re-fetch from original URI (store URI in metadata), re-validate, regenerate

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ampctl && uv run pytest tests/test_cli.py -v
```

- [ ] **Step 5: Verify CLI works end-to-end**

```bash
cd ampctl && uv run ampctl --help
```

Expected: shows all subcommands.

- [ ] **Step 6: Commit**

```bash
git add ampctl/src/ampctl/main.py ampctl/tests/test_cli.py
git commit -m "feat(ampctl): add CLI commands -- add, list, remove, compose, inspect"
```

---

## Task 8: Agent Definition Files

**Files:**
- Create: `agents/foundation.yaml`
- Create: `agents/default.yaml`

- [ ] **Step 1: Create foundation.yaml**

Create `agents/foundation.yaml` matching the current hardcoded foundation agent in `services/session-service/src/session_service/agents.py`, but using the new YAML format. Map each `svc-*` service to its `build:` path (since we're in local dev, not using registry images yet):

```yaml
agent:
  ref: foundation
  description: Full-featured foundation agent
  instruction: |
    You are Amplifier, an AI-powered CLI tool that helps users accomplish tasks.
    You have access to tools for file operations, web search, code execution, and more.
    Focus on being helpful, accurate, and efficient.

  orchestrator:
    build: ./services/svc-orchestrator

  context_manager:
    build: ./services/svc-context

  providers:
    build: ./services/svc-providers
    environment:
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"
      OPENAI_API_KEY: "${OPENAI_API_KEY:-}"

  behaviors:
    bash:
      build: ./services/svc-bash
    filesystem:
      build: ./services/svc-filesystem
    search:
      build: ./services/svc-search
    web:
      build: ./services/svc-web
    machine:
      build: ./services/svc-machine
      volumes:
        - "${WORKSPACE_PATH:-.}:/workspace"
      environment:
        WORKSPACE_DIR: /workspace
    skills:
      build: ./services/svc-skills
    todo:
      build: ./services/svc-todo
    modes:
      build: ./services/svc-modes
    delegation:
      build: ./services/svc-delegation
    hooks-approval:
      build: ./services/svc-hooks-approval
    hooks-routing:
      build: ./services/svc-hooks-routing
    hooks-async:
      build: ./services/svc-hooks-async
    hooks-shell:
      build: ./services/svc-hooks-shell
    content-core:
      build: ./services/svc-content-core
    content-amplifier:
      build: ./services/svc-content-amplifier
    content-browser-tester:
      build: ./services/svc-content-browser-tester
    content-design-intelligence:
      build: ./services/svc-content-design-intelligence
    content-filesystem:
      build: ./services/svc-content-filesystem
    content-recipes:
      build: ./services/svc-content-recipes
    content-superpowers:
      build: ./services/svc-content-superpowers
    content-system-design-intelligence:
      build: ./services/svc-content-system-design-intelligence
```

- [ ] **Step 2: Create default.yaml**

Create `agents/default.yaml` -- same as foundation but with mock provider and svc-mock-provider included.

- [ ] **Step 3: Validate both definitions parse correctly**

```bash
cd ampctl && uv run python -c "
from ampctl.parser import fetch_definition
d = fetch_definition('../agents/foundation.yaml')
print(f'Agent: {d.ref}, behaviors: {len(d.behaviors)}')
d2 = fetch_definition('../agents/default.yaml')
print(f'Agent: {d2.ref}, behaviors: {len(d2.behaviors)}')
"
```

Expected: Both parse without errors, foundation has 22 behaviors, default has 23.

- [ ] **Step 4: Commit**

```bash
git add agents/
git commit -m "feat: add foundation and default agent definition YAML files"
```

---

## Task 9: Session-Service Definition Loader

**Files:**
- Modify: `services/session-service/src/session_service/agents.py`
- Create: `services/session-service/tests/test_agents.py`

- [ ] **Step 1: Write failing tests for the new agent resolution**

Create `services/session-service/tests/test_agents.py`:

Test cases:
- `test_resolve_agent_from_yaml` -- with YAML file present, returns correct services list, default_provider, system_prompt
- `test_resolve_agent_fallback_to_hardcoded` -- when no YAML exists, falls back to current hardcoded registry
- `test_resolve_agent_unknown_falls_back_to_default` -- unknown agent_ref returns "default" config
- `test_service_list_from_service_map` -- services list is built from service-map app-ids

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/test_agents.py -v
```

- [ ] **Step 3: Rewrite agents.py**

Rewrite `services/session-service/src/session_service/agents.py` to:
1. Check for `AMPLIFIER_AGENTS_DIR` env var (set by compose) or `~/.amplifier/agents/`
2. If `{agents_dir}/{agent_ref}.yaml` exists, parse it with PyYAML + Pydantic
3. Read service-map from `AMPLIFIER_SERVICE_MAP` env var or `~/.amplifier/service-map.yaml`
4. Build the `services` list from service-map app-ids
5. Extract `instruction` as `system_prompt`, determine `default_provider`
6. If no YAML exists, fall back to the hardcoded `AGENTS` dict (preserves dev workflow)

The return shape stays the same: `{"services": [...], "default_provider": str, "system_prompt": str}`.

Additionally add `context_app_id` and `orchestrator_app_id` to the returned dict so `app.py` can resolve these from the service-map instead of hardcoding.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/test_agents.py -v
```

- [ ] **Step 5: Verify existing session-service tests still pass**

```bash
cd /data/labs/amplifier-ipc/services/session-service && uv run pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add services/session-service/src/session_service/agents.py services/session-service/tests/test_agents.py
git commit -m "feat(session-service): load agent definitions from YAML with hardcoded fallback"
```

---

## Task 10: Integration Test -- End to End

**Files:**
- Create: `ampctl/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

Test the full flow:
1. Create a temp directory as `AMPLIFIER_HOME`
2. `ampctl add agents/foundation.yaml foundation`
3. Verify `~/.amplifier/agents/foundation.yaml` exists
4. Verify `~/.amplifier/service-map.yaml` has the foundation entry
5. `ampctl compose`
6. Verify generated `docker-compose.yaml` has all expected services
7. Verify session-service entry has correct AMPLIFIER_AGENTS_DIR and ORCHESTRATOR_DIRECT_URL
8. Verify deduplication: services shared across agents appear only once

- [ ] **Step 2: Run integration test**

```bash
cd ampctl && uv run pytest tests/test_integration.py -v
```

- [ ] **Step 3: Run full test suite**

```bash
cd ampctl && uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add ampctl/tests/test_integration.py
git commit -m "test(ampctl): add end-to-end integration test for add/compose flow"
```

---

## Post-Implementation

After all tasks complete:

1. **Update AGENTS.md** -- Mark "Implement ampctl" and "Implement the definition system in session-service" as done. Update the "Current Status" section.

2. **Verify the full flow works**:
   ```bash
   cd /data/labs/amplifier-ipc
   cd ampctl && uv pip install -e .
   ampctl add ../agents/foundation.yaml foundation
   ampctl add ../agents/default.yaml default
   ampctl list
   ampctl inspect foundation
   ampctl compose --output ../docker-compose.generated.yaml
   ```

3. **Compare generated compose with current**: Diff `docker-compose.generated.yaml` against the existing `docker-compose.yaml` to verify equivalence.