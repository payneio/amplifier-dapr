"""Conventional paths under ~/.amplifier/ for ampctl artifacts."""

from __future__ import annotations

import os
from pathlib import Path


def amplifier_home() -> Path:
    """Return the Amplifier home directory, defaulting to ~/.amplifier."""
    return Path(os.environ.get("AMPLIFIER_HOME", Path.home() / ".amplifier"))


def agents_dir() -> Path:
    """Return the directory where cached agent definitions live."""
    return amplifier_home() / "agents"


def service_map_path() -> Path:
    """Return the path to the service-map.yaml file."""
    return amplifier_home() / "service-map.yaml"
