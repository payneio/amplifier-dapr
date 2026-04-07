"""
Tests for agents/foundation.yaml — verifies bash/filesystem/search behaviors are removed.
"""

import yaml
from pathlib import Path

AGENTS_FOUNDATION_YAML = Path(__file__).parent.parent / "agents" / "foundation.yaml"


def load_yaml():
    with open(AGENTS_FOUNDATION_YAML) as f:
        return yaml.safe_load(f)


def test_yaml_is_valid():
    """agents/foundation.yaml must be parseable by PyYAML."""
    data = load_yaml()
    assert data is not None


def test_no_svc_bash_reference():
    """agents/foundation.yaml must have no reference to svc-bash."""
    content = AGENTS_FOUNDATION_YAML.read_text()
    assert "svc-bash" not in content, "Found unexpected reference to svc-bash"


def test_no_svc_filesystem_reference():
    """agents/foundation.yaml must have no reference to svc-filesystem."""
    content = AGENTS_FOUNDATION_YAML.read_text()
    assert "svc-filesystem" not in content, (
        "Found unexpected reference to svc-filesystem"
    )


def test_no_svc_search_reference():
    """agents/foundation.yaml must have no reference to svc-search."""
    content = AGENTS_FOUNDATION_YAML.read_text()
    assert "svc-search" not in content, "Found unexpected reference to svc-search"


def test_machine_behavior_directly_followed_by_web():
    """In behaviors, machine: must be directly followed by web: (no bash/filesystem/search in between)."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    behavior_keys = list(behaviors.keys())
    machine_idx = behavior_keys.index("machine")
    web_idx = behavior_keys.index("web")
    assert web_idx == machine_idx + 1, (
        f"Expected 'web' to immediately follow 'machine' in behaviors, "
        f"but found keys in between: {behavior_keys[machine_idx + 1 : web_idx]}"
    )


def test_bash_behavior_removed():
    """The 'bash' behavior block must not exist in agents/foundation.yaml."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    assert "bash" not in behaviors, "Found unexpected 'bash' behavior block"


def test_filesystem_behavior_removed():
    """The 'filesystem' behavior block must not exist in agents/foundation.yaml."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    assert "filesystem" not in behaviors, "Found unexpected 'filesystem' behavior block"


def test_search_behavior_removed():
    """The 'search' behavior block must not exist in agents/foundation.yaml."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    assert "search" not in behaviors, "Found unexpected 'search' behavior block"


def test_machine_behavior_preserved():
    """The machine behavior with its config must still exist."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    assert "machine" in behaviors
    machine = behaviors["machine"]
    assert machine["build"] == "./services/svc-machine"
    assert machine["environment"]["WORKSPACE_DIR"] == "/workspace"
    assert "${WORKSPACE_PATH:-.}:/workspace" in machine["volumes"]


def test_web_behavior_preserved():
    """The web behavior must still exist."""
    data = load_yaml()
    behaviors = data["agent"]["behaviors"]
    assert "web" in behaviors
    assert behaviors["web"]["build"] == "./services/svc-web"
