"""Tests for services/svc-content-design-intelligence/describe.yaml — validates service manifest.

These tests verify YAML validity, service metadata, agent count, and agent name completeness.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Resolve the repo root relative to this test file (tests/ → project root)
REPO_ROOT = Path(__file__).parent.parent
DESCRIBE_YAML_PATH = (
    REPO_ROOT / "services" / "svc-content-design-intelligence" / "describe.yaml"
)

EXPECTED_AGENT_NAMES = [
    "animation-choreographer",
    "art-director",
    "component-designer",
    "design-system-architect",
    "layout-architect",
    "responsive-strategist",
    "voice-strategist",
]


def _load_describe() -> dict:
    """Load and return parsed describe.yaml content."""
    assert DESCRIBE_YAML_PATH.exists(), (
        f"describe.yaml not found at {DESCRIBE_YAML_PATH}. "
        "Create services/svc-content-design-intelligence/describe.yaml per spec."
    )
    return yaml.safe_load(DESCRIBE_YAML_PATH.read_text())


# ── YAML validity ──────────────────────────────────────────────────────────────


def test_yaml_parses_without_error() -> None:
    """describe.yaml must be valid YAML and parse without exception."""
    data = _load_describe()
    assert isinstance(data, dict), "describe.yaml must parse to a mapping"


# ── Service metadata ───────────────────────────────────────────────────────────


def test_service_name() -> None:
    """Service name must be 'svc-content-design-intelligence'."""
    data = _load_describe()
    assert data.get("name") == "svc-content-design-intelligence", (
        f"Expected name='svc-content-design-intelligence', got {data.get('name')!r}"
    )


def test_service_version() -> None:
    """Service version must be '0.1.0'."""
    data = _load_describe()
    assert data.get("version") == "0.1.0", (
        f"Expected version='0.1.0', got {data.get('version')!r}"
    )


def test_content_dir() -> None:
    """content_dir must be 'content'."""
    data = _load_describe()
    assert data.get("content_dir") == "content", (
        f"Expected content_dir='content', got {data.get('content_dir')!r}"
    )


# ── Agent definitions ──────────────────────────────────────────────────────────


def test_exactly_7_agents() -> None:
    """describe.yaml must declare exactly 7 agents."""
    data = _load_describe()
    agents = data.get("agents", [])
    assert len(agents) == 7, (
        f"Expected exactly 7 agents, got {len(agents)}: "
        f"{[a.get('name') for a in agents]}"
    )


def test_all_expected_agent_names_present() -> None:
    """All 7 expected agent names must appear in the agents list."""
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
