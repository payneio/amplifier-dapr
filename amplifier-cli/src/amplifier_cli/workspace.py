"""Workspace content resolver for reading .amplifier/ directory files."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_EXCLUDED_FILENAMES: set[str] = {"settings.yaml", "settings.local.yaml"}
_MAX_FILE_SIZE = 512 * 1024  # 512KB


def resolve_workspace_content(workspace_root: Path) -> dict[str, str]:
    """Read files from the .amplifier/ directory under workspace_root.

    Walks the .amplifier/ directory recursively and returns a dict mapping
    relative paths (e.g. '.amplifier/AGENTS.md') to file content.

    Excludes:
    - settings.yaml and settings.local.yaml
    - Files larger than 512KB
    - Binary/non-UTF-8 files

    Returns an empty dict when .amplifier/ does not exist.
    """
    amplifier_dir = workspace_root / ".amplifier"

    if not amplifier_dir.exists():
        return {}

    result: dict[str, str] = {}

    for path in sorted(amplifier_dir.rglob("*")):
        if not path.is_file():
            continue

        if path.name in _EXCLUDED_FILENAMES:
            logger.debug("Skipping excluded file: %s", path)
            continue

        file_size = path.stat().st_size
        if file_size > _MAX_FILE_SIZE:
            logger.debug("Skipping large file (%d bytes): %s", file_size, path)
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.debug("Skipping binary/non-UTF-8 file: %s", path)
            continue

        relative_path = str(path.relative_to(workspace_root))
        result[relative_path] = content

    return result
