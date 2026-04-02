"""Tests for ampctl CLI commands (add, list, remove, compose, inspect)."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from ampctl.main import main

# ---------------------------------------------------------------------------
# YAML fixture – mirrors the shape used in test_parser.py
# ---------------------------------------------------------------------------

VALID_YAML = """\
agent:
  ref: "example/my-agent"
  description: "A test agent"
  instruction: "You are helpful."
  orchestrator:
    image: "ghcr.io/example/orchestrator:latest"
  context_manager:
    image: "ghcr.io/example/context-manager:latest"
  providers:
    image: "ghcr.io/example/providers:latest"
  behaviors:
    web-search:
      image: "ghcr.io/example/web-search:latest"
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _put_yaml(path: Path, content: str = VALID_YAML) -> Path:
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# ampctl add
# ---------------------------------------------------------------------------


def test_add_command(tmp_path: Path) -> None:
    """ampctl add copies definition and updates service map."""
    runner = CliRunner()
    src = _put_yaml(tmp_path / "source.yaml")
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    result = runner.invoke(main, ["add", str(src), "my-agent"], env=env)

    assert result.exit_code == 0, result.output
    # YAML copied into agents dir
    assert (tmp_path / "agents" / "my-agent.yaml").exists()
    # Service map written and contains the new entry
    sm_path = tmp_path / "service-map.yaml"
    assert sm_path.exists()
    sm_data = yaml.safe_load(sm_path.read_text())
    assert "my-agent" in sm_data["agents"]


def test_add_duplicate_without_force(tmp_path: Path) -> None:
    """ampctl add errors on duplicate without --force."""
    runner = CliRunner()
    src = _put_yaml(tmp_path / "source.yaml")
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    runner.invoke(main, ["add", str(src), "my-agent"], env=env)
    result = runner.invoke(main, ["add", str(src), "my-agent"], env=env)

    assert result.exit_code != 0


def test_add_duplicate_with_force(tmp_path: Path) -> None:
    """ampctl add --force overwrites existing."""
    runner = CliRunner()
    src = _put_yaml(tmp_path / "source.yaml")
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    runner.invoke(main, ["add", str(src), "my-agent"], env=env)
    result = runner.invoke(main, ["add", "--force", str(src), "my-agent"], env=env)

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# ampctl list
# ---------------------------------------------------------------------------


def test_list_command(tmp_path: Path) -> None:
    """ampctl list shows installed agents."""
    runner = CliRunner()
    src = _put_yaml(tmp_path / "source.yaml")
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    runner.invoke(main, ["add", str(src), "my-agent"], env=env)
    result = runner.invoke(main, ["list"], env=env)

    assert result.exit_code == 0, result.output
    assert "my-agent" in result.output


def test_list_empty(tmp_path: Path) -> None:
    """ampctl list with no agents shows message."""
    runner = CliRunner()
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    result = runner.invoke(main, ["list"], env=env)

    assert result.exit_code == 0, result.output
    assert "No agents installed" in result.output


# ---------------------------------------------------------------------------
# ampctl remove
# ---------------------------------------------------------------------------


def test_remove_command(tmp_path: Path) -> None:
    """ampctl remove deletes agent and updates service map."""
    runner = CliRunner()
    src = _put_yaml(tmp_path / "source.yaml")
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    runner.invoke(main, ["add", str(src), "my-agent"], env=env)
    result = runner.invoke(main, ["remove", "my-agent"], env=env)

    assert result.exit_code == 0, result.output
    assert not (tmp_path / "agents" / "my-agent.yaml").exists()

    sm_data = yaml.safe_load((tmp_path / "service-map.yaml").read_text())
    assert "my-agent" not in sm_data.get("agents", {})


def test_remove_nonexistent(tmp_path: Path) -> None:
    """ampctl remove errors on missing agent."""
    runner = CliRunner()
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    result = runner.invoke(main, ["remove", "nonexistent"], env=env)

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# ampctl compose
# ---------------------------------------------------------------------------


def test_compose_command(tmp_path: Path) -> None:
    """ampctl compose generates docker-compose.yaml."""
    runner = CliRunner()
    src = _put_yaml(tmp_path / "source.yaml")
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    runner.invoke(main, ["add", str(src), "my-agent"], env=env)
    output_file = tmp_path / "docker-compose.yaml"

    result = runner.invoke(main, ["compose", "--output", str(output_file)], env=env)

    assert result.exit_code == 0, result.output
    assert output_file.exists()

    data = yaml.safe_load(output_file.read_text())
    assert "services" in data
    assert "redis" in data["services"]


# ---------------------------------------------------------------------------
# ampctl inspect
# ---------------------------------------------------------------------------


def test_inspect_command(tmp_path: Path) -> None:
    """ampctl inspect shows agent details."""
    runner = CliRunner()
    src = _put_yaml(tmp_path / "source.yaml")
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    runner.invoke(main, ["add", str(src), "my-agent"], env=env)
    result = runner.invoke(main, ["inspect", "my-agent"], env=env)

    assert result.exit_code == 0, result.output
    assert "example/my-agent" in result.output  # ref
    assert "A test agent" in result.output  # description
