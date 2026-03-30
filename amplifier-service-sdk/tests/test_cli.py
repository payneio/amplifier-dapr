"""Tests for the CLI entry point (load_config_from_yaml / main)."""

from __future__ import annotations

from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# TestLoadConfigFromYaml
# ---------------------------------------------------------------------------


class TestLoadConfigFromYaml:
    def test_minimal_yaml(self, tmp_path: Path) -> None:
        """load_config_from_yaml works with only name and version fields."""
        from amplifier_service_sdk.cli import load_config_from_yaml

        config_file = tmp_path / "service.yaml"
        config_file.write_text(yaml.dump({"name": "my-service", "version": "1.2.3"}))

        config = load_config_from_yaml(config_file)

        assert config.name == "my-service"
        assert config.version == "1.2.3"
        assert config.content_dir is None
        assert config.tools == []
        assert config.hooks == []
        assert config.providers == []

    def test_yaml_with_tools(self, tmp_path: Path) -> None:
        """load_config_from_yaml parses tools into ToolCapability objects."""
        from amplifier_service_sdk.cli import load_config_from_yaml

        data = {
            "name": "tool-service",
            "version": "0.1.0",
            "tools": [
                {
                    "name": "bash",
                    "description": "Run a bash command",
                    "input_schema": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                    },
                }
            ],
        }
        config_file = tmp_path / "service.yaml"
        config_file.write_text(yaml.dump(data))

        config = load_config_from_yaml(config_file)

        assert len(config.tools) == 1
        tool = config.tools[0]
        assert tool.name == "bash"
        assert tool.description == "Run a bash command"
        assert "command" in tool.input_schema.get("properties", {})

    def test_yaml_with_content_dir(self, tmp_path: Path) -> None:
        """load_config_from_yaml resolves content_dir relative to the YAML file."""
        from amplifier_service_sdk.cli import load_config_from_yaml

        # Create the content directory that will be referenced
        content_subdir = tmp_path / "context"
        content_subdir.mkdir()

        data = {
            "name": "content-service",
            "version": "0.1.0",
            "content_dir": "context",
        }
        config_file = tmp_path / "service.yaml"
        config_file.write_text(yaml.dump(data))

        config = load_config_from_yaml(config_file)

        assert config.content_dir is not None
        assert config.content_dir.exists()
        assert config.content_dir == tmp_path / "context"
