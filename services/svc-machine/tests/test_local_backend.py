"""Tests for LocalBackend — async subprocess execution."""

from pathlib import Path

import pytest

from svc_machine.local_backend import (
    ExecResult,
    FileEditResult,
    FileReadResult,
    LocalBackend,
)


class TestExec:
    """Tests for LocalBackend.exec()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    async def test_echo(self, backend: LocalBackend) -> None:
        """exec() captures stdout from a simple echo command."""
        result = await backend.exec("echo hello")
        assert isinstance(result, ExecResult)
        assert result.stdout.strip() == "hello"
        assert result.exit_code == 0

    async def test_exit_code_nonzero(self, backend: LocalBackend) -> None:
        """exec() captures non-zero exit codes."""
        result = await backend.exec("exit 42", timeout=5)
        assert result.exit_code == 42

    async def test_stderr(self, backend: LocalBackend) -> None:
        """exec() captures stderr output separately."""
        result = await backend.exec("echo error_output >&2")
        assert "error_output" in result.stderr
        assert result.exit_code == 0

    async def test_timeout(self, backend: LocalBackend) -> None:
        """exec() kills the process and returns exit_code=124 on timeout."""
        result = await backend.exec("sleep 60", timeout=1)
        assert result.exit_code == 124
        assert result.stdout == "Command timed out"

    async def test_working_dir(self, backend: LocalBackend, tmp_path: Path) -> None:
        """exec() runs command in the specified working directory."""
        # working_dir is a path relative to workspace_dir or an absolute path within it
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        result = await backend.exec("pwd", working_dir=str(subdir))
        assert str(subdir) in result.stdout.strip()
        assert result.exit_code == 0

    async def test_working_dir_outside_workspace_raises(
        self, backend: LocalBackend
    ) -> None:
        """exec() raises ValueError when working_dir is outside workspace_dir."""
        with pytest.raises(ValueError, match="outside workspace"):
            await backend.exec("echo hi", working_dir="/etc")


class TestFileRead:
    """Tests for LocalBackend.file_read()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    def test_read_file(self, backend: LocalBackend, tmp_path: Path) -> None:
        """file_read() returns content and total_lines for a 3-line file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")
        result = backend.file_read("test.txt")
        assert result is not None
        assert isinstance(result, FileReadResult)
        assert result.total_lines == 3
        assert "line1" in result.content
        assert "line2" in result.content
        assert "line3" in result.content

    def test_read_with_offset_and_limit(
        self, backend: LocalBackend, tmp_path: Path
    ) -> None:
        """file_read() respects 1-based offset and line limit."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")
        result = backend.file_read("test.txt", offset=2, limit=2)
        assert result is not None
        assert "line2" in result.content
        assert "line3" in result.content
        assert "line1" not in result.content
        assert "line4" not in result.content

    def test_read_nonexistent(self, backend: LocalBackend) -> None:
        """file_read() returns None for a nonexistent file."""
        result = backend.file_read("nonexistent.txt")
        assert result is None

    def test_read_path_traversal(self, backend: LocalBackend) -> None:
        """file_read() returns None when path escapes the workspace."""
        result = backend.file_read("../../../etc/passwd")
        assert result is None


class TestFileWrite:
    """Tests for LocalBackend.file_write()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    def test_write_new_file(self, backend: LocalBackend, tmp_path: Path) -> None:
        """file_write() creates a new file with given content."""
        result = backend.file_write("newfile.txt", "hello world\n")
        assert result is True
        assert (tmp_path / "newfile.txt").read_text() == "hello world\n"

    def test_write_overwrites(self, backend: LocalBackend, tmp_path: Path) -> None:
        """file_write() overwrites an existing file."""
        test_file = tmp_path / "existing.txt"
        test_file.write_text("old content\n")
        result = backend.file_write("existing.txt", "new content\n")
        assert result is True
        assert test_file.read_text() == "new content\n"

    def test_write_creates_parent_dirs(
        self, backend: LocalBackend, tmp_path: Path
    ) -> None:
        """file_write() creates intermediate parent directories."""
        result = backend.file_write("subdir/nested/file.txt", "data\n")
        assert result is True
        assert (tmp_path / "subdir" / "nested" / "file.txt").read_text() == "data\n"

    def test_write_path_traversal(self, backend: LocalBackend) -> None:
        """file_write() returns False when path escapes workspace."""
        result = backend.file_write("../../../tmp/evil.txt", "bad content")
        assert result is False


class TestFileEdit:
    """Tests for LocalBackend.file_edit()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    def test_edit_replace(self, backend: LocalBackend, tmp_path: Path) -> None:
        """file_edit() replaces first occurrence and returns replacements_made=1."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo bar foo\n")
        result = backend.file_edit("test.txt", "foo", "baz")
        assert result is not None
        assert isinstance(result, FileEditResult)
        assert result.replacements_made == 1
        assert result.success is True
        assert test_file.read_text() == "baz bar foo\n"

    def test_edit_replace_all(self, backend: LocalBackend, tmp_path: Path) -> None:
        """file_edit() with replace_all=True replaces all occurrences."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("foo bar foo\n")
        result = backend.file_edit("test.txt", "foo", "baz", replace_all=True)
        assert result is not None
        assert result.replacements_made == 2
        assert result.success is True
        assert test_file.read_text() == "baz bar baz\n"

    def test_edit_no_match(self, backend: LocalBackend, tmp_path: Path) -> None:
        """file_edit() returns replacements_made=0 when old_string not found."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\n")
        result = backend.file_edit("test.txt", "nonexistent", "replacement")
        assert result is not None
        assert result.replacements_made == 0
        assert result.success is False

    def test_edit_nonexistent_file(self, backend: LocalBackend) -> None:
        """file_edit() returns None when the file does not exist."""
        result = backend.file_edit("ghost.txt", "old", "new")
        assert result is None


class TestFileList:
    """Tests for LocalBackend.file_list()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    @pytest.fixture
    def populated_dir(self, tmp_path: Path) -> Path:
        """Create a directory with known files and subdirectory."""
        (tmp_path / "a.txt").write_text("file a\n")
        (tmp_path / "b.txt").write_text("file b\n")
        (tmp_path / "subdir").mkdir()
        return tmp_path

    def test_list_directory(self, backend: LocalBackend, populated_dir: Path) -> None:
        """file_list() finds a.txt, b.txt, and subdir in the directory."""
        result = backend.file_list(".")
        assert result is not None
        names = {entry["name"] for entry in result}
        assert "a.txt" in names
        assert "b.txt" in names
        assert "subdir" in names

    def test_list_entries_have_type(
        self, backend: LocalBackend, populated_dir: Path
    ) -> None:
        """file_list() entries have type 'file' for files and 'dir' for directories."""
        result = backend.file_list(".")
        assert result is not None
        by_name = {entry["name"]: entry for entry in result}
        assert by_name["a.txt"]["type"] == "file"
        assert by_name["subdir"]["type"] == "dir"

    def test_list_nonexistent(self, backend: LocalBackend) -> None:
        """file_list() returns None for a nonexistent path."""
        result = backend.file_list("nonexistent_dir")
        assert result is None


class TestFileGlob:
    """Tests for LocalBackend.file_glob()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    @pytest.fixture
    def populated_dir(self, tmp_path: Path) -> Path:
        """Create a directory with .py and .txt files including nested."""
        (tmp_path / "main.py").write_text("def main(): pass\n")
        (tmp_path / "readme.txt").write_text("readme\n")
        nested = tmp_path / "pkg"
        nested.mkdir()
        (nested / "utils.py").write_text("def helper(): pass\n")
        return tmp_path

    def test_glob_pattern(self, backend: LocalBackend, populated_dir: Path) -> None:
        """file_glob('*.py') finds .py files but not .txt files."""
        result = backend.file_glob("*.py")
        assert result is not None
        assert any(p.endswith(".py") for p in result)
        assert not any(p.endswith(".txt") for p in result)

    def test_glob_recursive(self, backend: LocalBackend, populated_dir: Path) -> None:
        """file_glob('**/*.py') finds nested .py files."""
        result = backend.file_glob("**/*.py")
        assert result is not None
        # Should find both main.py and pkg/utils.py
        assert len(result) >= 2
        assert any("utils.py" in p for p in result)


class TestFileGrep:
    """Tests for LocalBackend.file_grep()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    @pytest.fixture
    def populated_dir(self, tmp_path: Path) -> Path:
        """Create files with known function definitions."""
        (tmp_path / "funcs.py").write_text(
            "def foo():\n    pass\n\ndef bar():\n    return 1\n"
        )
        (tmp_path / "notes.txt").write_text("no functions here\n")
        return tmp_path

    def test_grep_finds_matches(
        self, backend: LocalBackend, populated_dir: Path
    ) -> None:
        """file_grep('def \\w+') finds 2 function definitions."""
        result = backend.file_grep(r"def \w+")
        assert result is not None
        assert len(result) == 2
        for match in result:
            assert "file" in match
            assert "line" in match
            assert "content" in match

    def test_grep_no_matches(self, backend: LocalBackend, populated_dir: Path) -> None:
        """file_grep() returns empty list when pattern has no matches."""
        result = backend.file_grep("THIS_PATTERN_WILL_NOT_MATCH_ANYTHING_XYZ")
        assert result is not None
        assert result == []
