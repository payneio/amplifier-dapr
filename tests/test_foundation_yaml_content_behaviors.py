"""
Tests for agents/foundation.yaml content behavior entries.
Task-10: Add content-foundation, remove content-system-design-intelligence.
"""
import yaml
from pathlib import Path


FOUNDATION_YAML = Path(__file__).parent.parent / "agents" / "foundation.yaml"


def load_yaml():
    with FOUNDATION_YAML.open() as f:
        return yaml.safe_load(f)


def test_yaml_is_valid():
    """The foundation.yaml file must be valid YAML."""
    data = load_yaml()
    assert data is not None


def test_content_foundation_present():
    """content-foundation behavior must be present."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    assert "content-foundation" in behaviors, (
        "content-foundation behavior is missing from agents/foundation.yaml"
    )


def test_content_foundation_has_correct_build():
    """content-foundation must point to the correct service."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    assert behaviors["content-foundation"]["build"] == "./services/svc-content-foundation"


def test_content_system_design_intelligence_removed():
    """content-system-design-intelligence behavior must NOT be present."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    assert "content-system-design-intelligence" not in behaviors, (
        "content-system-design-intelligence must be removed from agents/foundation.yaml"
    )


def test_all_eight_content_services_present():
    """All 8 expected content service behaviors must be present."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    expected = [
        "content-core",
        "content-amplifier",
        "content-browser-tester",
        "content-design-intelligence",
        "content-filesystem",
        "content-recipes",
        "content-superpowers",
        "content-foundation",
    ]
    for name in expected:
        assert name in behaviors, f"Missing expected content behavior: {name}"
