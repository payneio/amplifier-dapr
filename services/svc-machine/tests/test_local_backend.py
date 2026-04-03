"""Tests for LocalBackend — async subprocess execution."""

import os
import signal
from pathlib import Path

import pytest

from svc_machine.local_backend import (
    ExecResult,
    FileEditResult,
    FileGlobResult,
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
        assert "size" in by_name["a.txt"]
        assert isinstance(by_name["a.txt"]["size"], int)

    def test_list_nonexistent(self, backend: LocalBackend) -> None:
        """file_list() returns None for a nonexistent path."""
        result = backend.file_list("nonexistent_dir")
        assert result is None


class TestFileGlob:
    """Tests for LocalBackend.file_glob() — enriched with exclude, type_filter, include_ignored."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    @pytest.fixture(autouse=True)
    def populated_dir(self, tmp_path: Path) -> None:
        """Create a known directory structure for glob tests."""
        (tmp_path / "main.py").write_text("def main(): pass\n")
        (tmp_path / "readme.txt").write_text("readme\n")
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "utils.py").write_text("def helper(): pass\n")
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()
        (node_modules / "dep.js").write_text("module.exports = {};\n")
        (tmp_path / "mydir").mkdir()

    def test_glob_pattern(self, backend: LocalBackend) -> None:
        """file_glob('*.py') finds .py files but not .txt files."""
        result = backend.file_glob("*.py")
        assert result is not None
        assert any(p.endswith(".py") for p in result.matches)
        assert not any(p.endswith(".txt") for p in result.matches)

    def test_glob_recursive(self, backend: LocalBackend) -> None:
        """file_glob('**/*.py') finds >=2 files including utils.py."""
        result = backend.file_glob("**/*.py")
        assert result is not None
        assert len(result.matches) >= 2
        assert any("utils.py" in p for p in result.matches)

    def test_glob_excludes_node_modules(self, backend: LocalBackend) -> None:
        """file_glob('**/*.js') returns no matches — node_modules excluded by default."""
        result = backend.file_glob("**/*.js")
        assert result is not None
        assert len(result.matches) == 0

    def test_glob_include_ignored(self, backend: LocalBackend) -> None:
        """file_glob('**/*.js', include_ignored=True) returns matches in node_modules."""
        result = backend.file_glob("**/*.js", include_ignored=True)
        assert result is not None
        assert len(result.matches) >= 1
        assert any("dep.js" in p for p in result.matches)

    def test_glob_exclude_pattern(self, backend: LocalBackend) -> None:
        """file_glob('*', exclude=['*.txt']) returns no .txt files."""
        result = backend.file_glob("*", exclude=["*.txt"])
        assert result is not None
        assert not any(p.endswith(".txt") for p in result.matches)

    def test_glob_type_dir(self, backend: LocalBackend) -> None:
        """file_glob('*', type_filter='dir') returns pkg and mydir but no .py/.txt files."""
        result = backend.file_glob("*", type_filter="dir")
        assert result is not None
        assert any("pkg" in p for p in result.matches)
        assert any("mydir" in p for p in result.matches)
        assert not any(p.endswith(".py") for p in result.matches)
        assert not any(p.endswith(".txt") for p in result.matches)

    def test_glob_type_file(self, backend: LocalBackend) -> None:
        """file_glob('*', type_filter='file') returns only files."""
        result = backend.file_glob("*", type_filter="file")
        assert result is not None
        assert len(result.matches) > 0
        assert not any("mydir" in p for p in result.matches)
        assert not any("pkg" in p for p in result.matches)

    def test_glob_total_files_accurate_when_capped(
        self, backend: LocalBackend, tmp_path: Path
    ) -> None:
        """total_files reflects the real count, not the cap, when results are truncated."""
        # Temporarily lower cap to 3 and create 5 files
        original_max = backend._GLOB_MAX_RESULTS
        backend._GLOB_MAX_RESULTS = 3  # type: ignore[assignment]
        for i in range(5):
            (tmp_path / f"cap{i}.dat").write_text("x")
        result = backend.file_glob("*.dat")
        backend._GLOB_MAX_RESULTS = original_max  # type: ignore[assignment]
        assert isinstance(result, FileGlobResult)
        assert len(result.matches) == 3  # capped at 3
        assert result.total_files == 5  # real count surfaced

    def test_glob_nonexistent_base(self, backend: LocalBackend) -> None:
        """file_glob('*.py', path='nonexistent_dir') returns None."""
        result = backend.file_glob("*.py", path="nonexistent_dir")
        assert result is None


class TestFileGrep:
    """Tests for LocalBackend.file_grep() — ripgrep-based implementation."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    @pytest.fixture(autouse=True)
    def populated_dir(self, tmp_path: Path) -> None:
        """Create files with known function definitions, including node_modules."""
        (tmp_path / "funcs.py").write_text(
            "def foo():\n    pass\n\ndef bar():\n    return 1\n"
        )
        (tmp_path / "notes.txt").write_text("no functions here\n")
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir(parents=True)
        (node_modules / "pkg.js").write_text("def fake() {}\n")

    async def test_grep_files_with_matches_default(self, backend: LocalBackend) -> None:
        """file_grep(pattern) returns dict with 'matches' list containing funcs.py."""
        result = await backend.file_grep(pattern=r"def \w+")
        assert result is not None
        assert "matches" in result
        assert any("funcs.py" in m for m in result["matches"])

    async def test_grep_content_mode(self, backend: LocalBackend) -> None:
        """file_grep with output_mode='content' returns 2 matches for 'def \\w+'."""
        result = await backend.file_grep(pattern=r"def \w+", output_mode="content")
        assert result is not None
        assert len(result["matches"]) == 2

    async def test_grep_count_mode(self, backend: LocalBackend) -> None:
        """file_grep with output_mode='count' returns at least 1 match."""
        result = await backend.file_grep(pattern=r"def \w+", output_mode="count")
        assert result is not None
        assert len(result["matches"]) >= 1

    async def test_grep_excludes_node_modules(self, backend: LocalBackend) -> None:
        """file_grep excludes node_modules by default — 0 matches for 'def fake'."""
        result = await backend.file_grep(pattern="def fake", output_mode="content")
        assert result is not None
        assert len(result["matches"]) == 0

    async def test_grep_include_ignored(self, backend: LocalBackend) -> None:
        """file_grep with include_ignored=True finds matches in node_modules."""
        result = await backend.file_grep(
            pattern="def fake", output_mode="content", include_ignored=True
        )
        assert result is not None
        assert len(result["matches"]) >= 1

    async def test_grep_glob_filter(self, backend: LocalBackend) -> None:
        """file_grep with glob_pattern='*.py' only returns .py file matches."""
        result = await backend.file_grep(
            pattern="def", output_mode="content", glob_pattern="*.py"
        )
        assert result is not None
        for match in result["matches"]:
            assert match["file"].endswith(".py")

    async def test_grep_case_insensitive(self, backend: LocalBackend) -> None:
        """file_grep with case_insensitive=True matches 'DEF' against def lines."""
        result = await backend.file_grep(
            pattern="DEF", output_mode="content", case_insensitive=True
        )
        assert result is not None
        assert len(result["matches"]) >= 2

    async def test_grep_head_limit(self, backend: LocalBackend) -> None:
        """file_grep with head_limit=1 returns at most 1 match."""
        result = await backend.file_grep(
            pattern=r"def \w+", output_mode="content", head_limit=1
        )
        assert result is not None
        assert len(result["matches"]) <= 1

    async def test_grep_no_matches(self, backend: LocalBackend) -> None:
        """file_grep returns {'matches': []} when pattern has no matches."""
        result = await backend.file_grep(pattern="ZZZZZ_NO_MATCH")
        assert result == {"matches": []}

    async def test_grep_invalid_path(self, backend: LocalBackend) -> None:
        """file_grep returns None when path escapes the workspace."""
        result = await backend.file_grep(pattern="test", path="../../../etc")
        assert result is None


class TestExecBackground:
    """Tests for LocalBackend.exec_background()."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalBackend:
        """Create a LocalBackend with a temporary workspace directory."""
        return LocalBackend(workspace_dir=tmp_path)

    async def test_exec_background_returns_pid(self, backend: LocalBackend) -> None:
        """exec_background() returns dict with int pid and status 'running'."""
        result = await backend.exec_background("sleep 60")
        pid = result["pid"]
        try:
            assert isinstance(pid, int)
            assert result["status"] == "running"
        finally:
            # Cleanup: kill process with SIGTERM
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
