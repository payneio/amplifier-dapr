"""Tests for CLISettings."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from amplifier_ipc_cli.settings import (
    _DEFAULT_PROVIDER,
    _DEFAULT_URL,
    CLISettings,
)


class TestDefaults:
    def test_default_url(self) -> None:
        """CLISettings defaults url to http://localhost:8090."""
        settings = CLISettings()
        assert settings.url == "http://localhost:8090"
        assert _DEFAULT_URL == "http://localhost:8090"

    def test_default_provider(self) -> None:
        """CLISettings defaults provider to 'mock'."""
        settings = CLISettings()
        assert settings.provider == "mock"
        assert _DEFAULT_PROVIDER == "mock"


class TestFromYaml:
    def test_from_yaml(self, tmp_path: Path) -> None:
        """from_yaml reads url and provider from a YAML file."""
        config = tmp_path / "settings.yaml"
        config.write_text(
            yaml.dump({"url": "http://myserver:9090", "provider": "openai"})
        )

        settings = CLISettings.from_yaml(config)

        assert settings.url == "http://myserver:9090"
        assert settings.provider == "openai"

    def test_from_yaml_missing_file(self, tmp_path: Path) -> None:
        """from_yaml returns defaults when the file does not exist."""
        missing = tmp_path / "nonexistent.yaml"

        settings = CLISettings.from_yaml(missing)

        assert settings.url == _DEFAULT_URL
        assert settings.provider == _DEFAULT_PROVIDER

    def test_from_yaml_empty_file(self, tmp_path: Path) -> None:
        """from_yaml returns defaults when the YAML file is empty (non-dict data)."""
        config = tmp_path / "settings.yaml"
        config.write_text("")  # empty YAML parses to None

        settings = CLISettings.from_yaml(config)

        assert settings.url == _DEFAULT_URL
        assert settings.provider == _DEFAULT_PROVIDER

    def test_from_yaml_partial_override(self, tmp_path: Path) -> None:
        """from_yaml only overrides fields present in the YAML."""
        config = tmp_path / "settings.yaml"
        config.write_text(yaml.dump({"url": "http://custom:1234"}))

        settings = CLISettings.from_yaml(config)

        assert settings.url == "http://custom:1234"
        assert settings.provider == _DEFAULT_PROVIDER

    def test_from_yaml_non_dict_data(self, tmp_path: Path) -> None:
        """from_yaml returns defaults when YAML contains non-dict data."""
        config = tmp_path / "settings.yaml"
        config.write_text("- item1\n- item2\n")  # list, not dict

        settings = CLISettings.from_yaml(config)

        assert settings.url == _DEFAULT_URL
        assert settings.provider == _DEFAULT_PROVIDER

    def test_from_yaml_invalid_yaml(self, tmp_path: Path) -> None:
        """from_yaml returns defaults on YAML parse errors."""
        config = tmp_path / "settings.yaml"
        config.write_text("{invalid: yaml: content: [}")

        settings = CLISettings.from_yaml(config)

        assert settings.url == _DEFAULT_URL
        assert settings.provider == _DEFAULT_PROVIDER


class TestGetHistoryPath:
    def test_get_history_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """get_history_path returns a path inside ~/.amplifier/projects/<slug>/repl_history."""
        fake_home = tmp_path / "home" / "testuser"
        fake_home.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        # Test with cwd = home (slug = 'global')
        monkeypatch.chdir(fake_home)
        settings = CLISettings()
        path = settings.get_history_path()
        assert path == fake_home / ".amplifier" / "projects" / "global" / "repl_history"

    def test_get_history_path_under_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """get_history_path uses ~--<path> slug for directories under home."""
        # Use tmp_path as the fake home, with a subdir as cwd
        fake_home = tmp_path / "home" / "user"
        fake_home.mkdir(parents=True)
        subdir = fake_home / "projects" / "myapp"
        subdir.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.chdir(subdir)

        settings = CLISettings()
        path = settings.get_history_path()

        # Relative path from home: projects/myapp → ~--projects--myapp
        expected_slug = "~--projects--myapp"
        expected = (
            fake_home / ".amplifier" / "projects" / expected_slug / "repl_history"
        )
        assert path == expected

    def test_get_history_path_outside_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """get_history_path uses cwd.name for directories outside home."""
        fake_home = tmp_path / "home" / "user"
        fake_home.mkdir(parents=True)
        outside_dir = tmp_path / "var" / "myproject"
        outside_dir.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
        monkeypatch.chdir(outside_dir)

        settings = CLISettings()
        path = settings.get_history_path()

        expected = fake_home / ".amplifier" / "projects" / "myproject" / "repl_history"
        assert path == expected
