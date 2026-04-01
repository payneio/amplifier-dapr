"""Tests for workspace content resolver."""

from __future__ import annotations

from pathlib import Path

from amplifier_ipc_cli.workspace import resolve_workspace_content


def test_reads_amplifier_dir_files(tmp_path: Path) -> None:
    """Files in .amplifier/ are returned with their content."""
    amplifier_dir = tmp_path / ".amplifier"
    amplifier_dir.mkdir()
    (amplifier_dir / "AGENTS.md").write_text("# Agents")
    (amplifier_dir / "config.yaml").write_text("key: value")

    result = resolve_workspace_content(tmp_path)

    assert ".amplifier/AGENTS.md" in result
    assert result[".amplifier/AGENTS.md"] == "# Agents"
    assert ".amplifier/config.yaml" in result
    assert result[".amplifier/config.yaml"] == "key: value"


def test_skips_settings_yaml(tmp_path: Path) -> None:
    """settings.yaml and settings.local.yaml are excluded from results."""
    amplifier_dir = tmp_path / ".amplifier"
    amplifier_dir.mkdir()
    (amplifier_dir / "settings.yaml").write_text("secret: value")
    (amplifier_dir / "settings.local.yaml").write_text("local: value")
    (amplifier_dir / "AGENTS.md").write_text("# Agents")

    result = resolve_workspace_content(tmp_path)

    assert ".amplifier/settings.yaml" not in result
    assert ".amplifier/settings.local.yaml" not in result
    assert ".amplifier/AGENTS.md" in result


def test_empty_when_no_amplifier_dir(tmp_path: Path) -> None:
    """Returns empty dict when .amplifier/ directory does not exist."""
    result = resolve_workspace_content(tmp_path)

    assert result == {}


def test_skips_large_files(tmp_path: Path) -> None:
    """Files larger than 512KB are excluded from results."""
    amplifier_dir = tmp_path / ".amplifier"
    amplifier_dir.mkdir()
    # Create a file just over 512KB
    large_content = "x" * (512 * 1024 + 1)
    (amplifier_dir / "large.md").write_text(large_content)
    (amplifier_dir / "small.md").write_text("small content")

    result = resolve_workspace_content(tmp_path)

    assert ".amplifier/large.md" not in result
    assert ".amplifier/small.md" in result


def test_skips_binary_files(tmp_path: Path) -> None:
    """Binary/non-UTF-8 files are excluded from results."""
    amplifier_dir = tmp_path / ".amplifier"
    amplifier_dir.mkdir()
    # Write binary content that is not valid UTF-8
    (amplifier_dir / "binary.bin").write_bytes(b"\xff\xfe\x00\x01\x80\x90")
    (amplifier_dir / "text.md").write_text("valid utf-8 content")

    result = resolve_workspace_content(tmp_path)

    assert ".amplifier/binary.bin" not in result
    assert ".amplifier/text.md" in result


def test_reads_nested_directories(tmp_path: Path) -> None:
    """Files in nested subdirectories of .amplifier/ are included."""
    amplifier_dir = tmp_path / ".amplifier"
    nested_dir = amplifier_dir / "subdir" / "deeper"
    nested_dir.mkdir(parents=True)
    (nested_dir / "nested.md").write_text("nested content")
    (amplifier_dir / "top.md").write_text("top content")

    result = resolve_workspace_content(tmp_path)

    assert ".amplifier/top.md" in result
    assert ".amplifier/subdir/deeper/nested.md" in result
    assert result[".amplifier/subdir/deeper/nested.md"] == "nested content"


def test_output_is_deterministic(tmp_path: Path) -> None:
    """Results are returned in sorted order for deterministic output."""
    amplifier_dir = tmp_path / ".amplifier"
    amplifier_dir.mkdir()
    (amplifier_dir / "z_last.md").write_text("z")
    (amplifier_dir / "a_first.md").write_text("a")
    (amplifier_dir / "m_middle.md").write_text("m")

    result = resolve_workspace_content(tmp_path)

    keys = list(result.keys())
    assert keys == sorted(keys)
