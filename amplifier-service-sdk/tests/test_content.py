"""Tests for ContentManager — directory scanning and safe file serving."""

from pathlib import Path

import pytest

from amplifier_service_sdk.content import ContentManager


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    """Create a temporary content directory with test files."""
    # context/instructions.md
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "instructions.md").write_text("# Instructions")
    # context/guidelines.md
    (tmp_path / "context" / "guidelines.md").write_text("# Guidelines")
    # agents/default.yaml
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "default.yaml").write_text("name: default")
    # context/sub/deep.md
    (tmp_path / "context" / "sub").mkdir()
    (tmp_path / "context" / "sub" / "deep.md").write_text("# Deep")
    return tmp_path


class TestContentManager:
    def test_scan_finds_all_files(self, content_dir: Path) -> None:
        """Scanning a populated directory finds all 4 files."""
        manager = ContentManager(content_dir)
        paths = manager.list_paths()
        assert len(paths) == 4

    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        """Scanning an empty directory returns an empty list."""
        manager = ContentManager(tmp_path)
        assert manager.list_paths() == []

    def test_read_existing_file(self, content_dir: Path) -> None:
        """Reading an existing file returns its content."""
        manager = ContentManager(content_dir)
        content = manager.read("context/instructions.md")
        assert content == "# Instructions"

    def test_read_nonexistent_file(self, content_dir: Path) -> None:
        """Reading a file that does not exist returns None."""
        manager = ContentManager(content_dir)
        result = manager.read("does/not/exist.md")
        assert result is None

    def test_read_path_traversal_blocked(self, content_dir: Path) -> None:
        """Path traversal attempts (../../etc/passwd) return None."""
        manager = ContentManager(content_dir)
        result = manager.read("../../etc/passwd")
        assert result is None

    def test_read_nested_file(self, content_dir: Path) -> None:
        """Reading a deeply nested file returns its content."""
        manager = ContentManager(content_dir)
        content = manager.read("context/sub/deep.md")
        assert content == "# Deep"
