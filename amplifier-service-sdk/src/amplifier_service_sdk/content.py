"""ContentManager — scans a content root directory and serves files safely."""

from __future__ import annotations

from pathlib import Path


class ContentManager:
    """Manages content files in a directory, providing safe access to their contents."""

    def __init__(self, content_dir: Path) -> None:
        """Resolve the content directory and scan it immediately at construction time."""
        self._content_dir = content_dir.resolve()
        self._paths: list[str] = self._scan()

    def _scan(self) -> list[str]:
        """Recursively glob all files (excluding __init__.py), sorted in posix-style."""
        paths: list[str] = []
        for file in self._content_dir.rglob("*"):
            if file.is_file() and file.name != "__init__.py":
                relative = file.relative_to(self._content_dir)
                paths.append(relative.as_posix())
        return sorted(paths)

    def list_paths(self) -> list[str]:
        """Return a copy of the discovered file paths."""
        return list(self._paths)

    def read(self, relative_path: str) -> str | None:
        """Read file content with path traversal protection.

        Returns None if the path is invalid, does not exist, or attempts to
        escape outside the content directory.
        """
        try:
            target = (self._content_dir / relative_path).resolve()
        except (ValueError, OSError):
            return None

        # Path traversal protection: resolved target must remain within content_dir
        try:
            target.relative_to(self._content_dir)
        except ValueError:
            return None

        if not target.is_file():
            return None

        return target.read_text()
