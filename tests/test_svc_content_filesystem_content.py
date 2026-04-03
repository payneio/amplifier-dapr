"""Tests for services/svc-content-filesystem content — validates ported files and describe.yaml.

Acceptance criteria for task-6: Port content to svc-content-filesystem.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# Resolve the repo root relative to this test file (tests/ → project root)
REPO_ROOT = Path(__file__).parent.parent
SVC_DIR = REPO_ROOT / "services" / "svc-content-filesystem"
CONTENT_DIR = SVC_DIR / "content"
DESCRIBE_YAML_PATH = SVC_DIR / "describe.yaml"


def _load_describe() -> dict:
    """Load and return parsed describe.yaml content."""
    assert DESCRIBE_YAML_PATH.exists(), (
        f"describe.yaml not found at {DESCRIBE_YAML_PATH}."
    )
    return yaml.safe_load(DESCRIBE_YAML_PATH.read_text())


# ── Content files ──────────────────────────────────────────────────────────────


def test_editing_guidance_md_exists() -> None:
    """editing-guidance.md must be present in content/."""
    target = CONTENT_DIR / "editing-guidance.md"
    assert target.exists(), f"Expected {target} to exist"


def test_no_gitkeep_remains() -> None:
    """No .gitkeep placeholder should remain in content/."""
    gitkeep = CONTENT_DIR / ".gitkeep"
    assert not gitkeep.exists(), f"Stale placeholder {gitkeep} should have been removed"


# ── describe.yaml ──────────────────────────────────────────────────────────────


def test_describe_yaml_name() -> None:
    """describe.yaml name must be 'svc-content-filesystem'."""
    data = _load_describe()
    assert data.get("name") == "svc-content-filesystem", (
        f"Expected name='svc-content-filesystem', got {data.get('name')!r}"
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


def test_describe_yaml_no_agents_section() -> None:
    """describe.yaml must NOT contain an agents section (content-only service)."""
    data = _load_describe()
    assert "agents" not in data, (
        "describe.yaml must not have an 'agents' section for svc-content-filesystem"
    )


def test_describe_yaml_exactly_3_lines() -> None:
    """describe.yaml must contain exactly 3 lines (name, version, content_dir)."""
    text = DESCRIBE_YAML_PATH.read_text()
    line_count = len(text.splitlines())
    assert line_count == 3, (
        f"Expected exactly 3 lines in describe.yaml, got {line_count}"
    )
