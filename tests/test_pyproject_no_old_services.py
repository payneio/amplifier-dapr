"""
Tests that pyproject.toml has no references to removed services (svc-bash, svc-filesystem, svc-search)
and that the file remains valid TOML.
"""

import tomllib
from pathlib import Path

PYPROJECT_PATH = Path(__file__).parent.parent / "pyproject.toml"

REMOVED_SERVICES = [
    "svc-bash",
    "svc-filesystem",
    "svc-search",
]


def test_pyproject_toml_is_valid():
    """pyproject.toml must be parseable as valid TOML."""
    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)
    assert isinstance(data, dict), "Expected TOML to parse to a dict"


def test_pyproject_toml_no_svc_bash():
    """pyproject.toml must not reference svc-bash."""
    content = PYPROJECT_PATH.read_text()
    assert "svc-bash" not in content, (
        "Found 'svc-bash' in pyproject.toml — should have been removed"
    )


def test_pyproject_toml_no_svc_filesystem():
    """pyproject.toml must not reference svc-filesystem."""
    content = PYPROJECT_PATH.read_text()
    assert "svc-filesystem" not in content, (
        "Found 'svc-filesystem' in pyproject.toml — should have been removed"
    )


def test_pyproject_toml_no_svc_search():
    """pyproject.toml must not reference svc-search."""
    content = PYPROJECT_PATH.read_text()
    assert "svc-search" not in content, (
        "Found 'svc-search' in pyproject.toml — should have been removed"
    )


def test_pytest_pythonpath_no_removed_services():
    """tool.pytest.ini_options.pythonpath must not include removed service paths."""
    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    pythonpath = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("pythonpath", [])
    for service in REMOVED_SERVICES:
        matching = [p for p in pythonpath if service in p]
        assert not matching, (
            f"Found '{service}' in tool.pytest.ini_options.pythonpath: {matching}"
        )


def test_pyright_extrapaths_no_removed_services():
    """tool.pyright.extraPaths must not include removed service paths."""
    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    extra_paths = data.get("tool", {}).get("pyright", {}).get("extraPaths", [])
    for service in REMOVED_SERVICES:
        matching = [p for p in extra_paths if service in p]
        assert not matching, (
            f"Found '{service}' in tool.pyright.extraPaths: {matching}"
        )
