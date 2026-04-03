"""Tests for services/svc-content-superpowers content — validates ported files and describe.yaml.

Acceptance criteria for task-8: Port content to svc-content-superpowers.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Resolve the repo root relative to this test file (tests/ → project root)
REPO_ROOT = Path(__file__).parent.parent
SVC_DIR = REPO_ROOT / "services" / "svc-content-superpowers"
CONTENT_DIR = SVC_DIR / "content"
DESCRIBE_YAML_PATH = SVC_DIR / "describe.yaml"

EXPECTED_CONTENT_FILES = [
    "debugging-techniques.md",
    "instructions.md",
    "philosophy.md",
    "shared-anti-rationalization.md",
    "tdd-depth.md",
    "using-superpowers-amplifier.md",
]

EXPECTED_AGENT_NAMES = [
    "brainstormer",
    "code-quality-reviewer",
    "implementer",
    "plan-writer",
    "spec-reviewer",
]


def _load_describe() -> dict:
    """Load and return parsed describe.yaml content."""
    assert DESCRIBE_YAML_PATH.exists(), (
        f"describe.yaml not found at {DESCRIBE_YAML_PATH}. "
        "Create services/svc-content-superpowers/describe.yaml per spec."
    )
    return yaml.safe_load(DESCRIBE_YAML_PATH.read_text())


# ── Content files ─────────────────────────────────────────────────────────────


def test_all_content_files_present() -> None:
    """All 6 expected content files must be present in content/."""
    missing = [f for f in EXPECTED_CONTENT_FILES if not (CONTENT_DIR / f).exists()]
    assert not missing, f"Missing content files: {missing}"


def test_no_gitkeep_remains() -> None:
    """No .gitkeep placeholder should remain in content/."""
    gitkeep = CONTENT_DIR / ".gitkeep"
    assert not gitkeep.exists(), f"Stale placeholder {gitkeep} should have been removed"


# ── describe.yaml ──────────────────────────────────────────────────────────────


def test_yaml_parses_without_error() -> None:
    """describe.yaml must be valid YAML and parse without exception."""
    data = _load_describe()
    assert isinstance(data, dict), "describe.yaml must parse to a mapping"


def test_describe_yaml_name() -> None:
    """describe.yaml name must be 'svc-content-superpowers'."""
    data = _load_describe()
    assert data.get("name") == "svc-content-superpowers", (
        f"Expected name='svc-content-superpowers', got {data.get('name')!r}"
    )


def test_describe_yaml_content_dir() -> None:
    """describe.yaml content_dir must be 'content'."""
    data = _load_describe()
    assert data.get("content_dir") == "content", (
        f"Expected content_dir='content', got {data.get('content_dir')!r}"
    )


# ── Agent definitions ──────────────────────────────────────────────────────────


def test_exactly_5_agents() -> None:
    """describe.yaml must declare exactly 5 agents."""
    data = _load_describe()
    agents = data.get("agents", [])
    assert len(agents) == 5, (
        f"Expected exactly 5 agents, got {len(agents)}: "
        f"{[a.get('name') for a in agents]}"
    )


def test_all_expected_agent_names_present() -> None:
    """All 5 expected agent names must appear in the agents list."""
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
