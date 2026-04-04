"""CLI settings with YAML-based multi-scope loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULT_URL = "http://localhost:8090"
_DEFAULT_PROVIDER = "mock"


@dataclass
class CLISettings:
    """Settings for the Amplifier IPC CLI."""

    url: str = field(default=_DEFAULT_URL)
    provider: str = field(default=_DEFAULT_PROVIDER)

    @classmethod
    def from_yaml(cls, path: Path) -> CLISettings:
        """Read settings from a YAML file.

        Returns defaults on FileNotFoundError, OSError, YAMLError, or
        if the file content is not a dict.
        """
        try:
            data = yaml.safe_load(path.read_text())
        except (FileNotFoundError, OSError, yaml.YAMLError):
            return cls()

        if not isinstance(data, dict):
            return cls()

        return cls(
            url=data.get("url", _DEFAULT_URL),
            provider=data.get("provider", _DEFAULT_PROVIDER),
        )

    @classmethod
    def load_merged(cls) -> CLISettings:
        """Load settings by merging global and project-level YAML files.

        Global settings come from ~/.amplifier/settings.yaml.
        Project settings come from .amplifier/settings.yaml in the cwd.
        Project settings override global for non-default values.
        """
        global_path = Path.home() / ".amplifier" / "settings.yaml"
        project_path = Path(".amplifier") / "settings.yaml"

        global_settings = cls.from_yaml(global_path)
        project_settings = cls.from_yaml(project_path)

        # Project overrides global only when project value differs from default
        url = (
            project_settings.url
            if project_settings.url != _DEFAULT_URL
            else global_settings.url
        )
        provider = (
            project_settings.provider
            if project_settings.provider != _DEFAULT_PROVIDER
            else global_settings.provider
        )

        return cls(url=url, provider=provider)

    def get_history_path(self) -> Path:
        """Return the REPL history file path for the current working directory.

        The path is ~/.amplifier/projects/<slug>/repl_history where slug is:
        - 'global'              if cwd is the home directory
        - '~--<path-parts>'     if cwd is under home (/ replaced with --)
        - cwd.name              otherwise
        """
        home = Path.home()
        cwd = Path.cwd()

        if cwd == home:
            slug = "global"
        else:
            try:
                relative = cwd.relative_to(home)
                slug = "~--" + "--".join(relative.parts)
            except ValueError:
                slug = cwd.name

        return home / ".amplifier" / "projects" / slug / "repl_history"
