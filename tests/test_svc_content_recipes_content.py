"""Tests for services/svc-content-recipes content — validates ported files and describe.yaml.

Acceptance criteria for task-7: Port content to svc-content-recipes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Resolve the repo root relative to this test file (tests/ → project root)
REPO_ROOT = Path(__file__).parent.parent
SVC_DIR = REPO_ROOT / "services" / "svc-content-recipes"
CONTENT_DIR = SVC_DIR / "content"
DESCRIBE_YAML_PATH = SVC_DIR / "describe.yaml"

EXPECTED_CONTENT_FILES = [
    "recipe-awareness.md",
    "recipe-instructions.md",
]

EXPECTED_AGENT_NAMES = [
    "recipe-author",
    "result-validator",
]


def _load_describe() -> dict:
    """Load and return parsed describe.yaml content."""
    assert DESCRIBE_YAML_PATH.exists(), (
        f"describe.yaml not found at {DESCRIBE_YAML_PATH}. "
        "Create services/svc-content-recipes/describe.yaml per spec."
    )
    return yaml.safe_load(DESCRIBE_YAML_PATH.read_text())


# ── Content files ─────────────────────────────────────────────────────────────


def test_recipe_awareness_md_exists() -> None:
    """recipe-awareness.md must be present in content/."""
    target = CONTENT_DIR / "recipe-awareness.md"
    assert target.exists(), f"Expected {target} to exist"


def test_recipe_instructions_md_exists() -> None:
    """recipe-instructions.md must be present in content/."""
    target = CONTENT_DIR / "recipe-instructions.md"
    assert target.exists(), f"Expected {target} to exist"


def test_all_content_files_present() -> None:
    """All 2 expected content files must be present in content/."""
    missing = [f for f in EXPECTED_CONTENT_FILES if not (CONTENT_DIR / f).exists()]
    assert not missing, f"Missing content files: {missing}"


def test_no_gitkeep_remains() -> None:
    """No .gitkeep placeholder should remain in content/."""
    gitkeep = CONTENT_DIR / ".gitkeep"
    assert not gitkeep.exists(), f"Stale placeholder {gitkeep} should have been removed"


# ── describe.yaml ─────────────────────────────────────────────────────────────


def test_yaml_parses_without_error() -> None:
    """describe.yaml must be valid YAML and parse without exception."""
    data = _load_describe()
    assert isinstance(data, dict), "describe.yaml must parse to a mapping"


def test_describe_yaml_name() -> None:
    """describe.yaml name must be 'svc-content-recipes'."""
    data = _load_describe()
    assert data.get("name") == "svc-content-recipes", (
        f"Expected name='svc-content-recipes', got {data.get('name')!r}"
    )


def test_describe_yaml_version() -> None:
    """describe.yaml version must be '0.1.0'."""
    data = _load_describe()
    assert data.get("version") == "0.1.0", (
        f"Expected version='0.1.0', got {data.get('version')!r}"
    )


def test_describe_yaml_content_dir() -> None:
    """describe.yaml content_dir must be 'content'."""
    data = _load_describe()
    assert data.get("content_dir") == "content", (
        f"Expected content_dir='content', got {data.get('content_dir')!r}"
    )


# ── Agent definitions ─────────────────────────────────────────────────────────


def test_exactly_2_agents() -> None:
    """describe.yaml must declare exactly 2 agents."""
    data = _load_describe()
    agents = data.get("agents", [])
    assert len(agents) == 2, (
        f"Expected exactly 2 agents, got {len(agents)}: "
        f"{[a.get('name') for a in agents]}"
    )


def test_all_expected_agent_names_present() -> None:
    """All 2 expected agent names must appear in the agents list."""
    data = _load_describe()
    actual_names = {a.get("name") for a in data.get("agents", [])}
    missing = set(EXPECTED_AGENT_NAMES) - actual_names
    extra = actual_names - set(EXPECTED_AGENT_NAMES)
    assert not missing, f"Missing agents: {sorted(missing)}"
    assert not extra, f"Unexpected agents: {sorted(extra)}"


def test_each_agent_has_description() -> None:
    """Every agent entry must have a non-empty description field."""
    data = _load_describe()
    for agent in data.get("agents", []):
        name = agent.get("name", "<unnamed>")
        desc = agent.get("description", "")
        assert desc, f"Agent '{name}' has no description"
