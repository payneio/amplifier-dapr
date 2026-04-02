"""Tests for ampctl YAML parser and definition fetcher."""

import pytest

from ampctl.models import AgentDefinition
from ampctl.parser import fetch_definition, parse_agent_definition

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

VALID_YAML = """
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
      config:
        max_results: 10
"""

MISSING_AGENT_KEY_YAML = """
ref: "example/my-agent"
orchestrator:
  image: "example/orchestrator:latest"
context_manager:
  image: "example/context-manager:latest"
providers:
  image: "example/providers:latest"
"""

MISSING_REQUIRED_FIELD_YAML = """
agent:
  description: "No ref field"
  orchestrator:
    image: "example/orchestrator:latest"
  context_manager:
    image: "example/context-manager:latest"
  providers:
    image: "example/providers:latest"
"""

# ---------------------------------------------------------------------------
# parse_agent_definition
# ---------------------------------------------------------------------------


def test_parse_valid_definition() -> None:
    result = parse_agent_definition(VALID_YAML)
    assert isinstance(result, AgentDefinition)
    assert result.ref == "example/my-agent"
    assert result.description == "A test agent"
    assert result.instruction == "You are helpful."
    assert result.orchestrator.image == "ghcr.io/example/orchestrator:latest"
    assert "web-search" in result.behaviors
    assert result.behaviors["web-search"].config == {"max_results": 10}


def test_parse_missing_agent_key() -> None:
    with pytest.raises(ValueError, match="agent"):
        parse_agent_definition(MISSING_AGENT_KEY_YAML)


def test_parse_missing_required_field() -> None:
    with pytest.raises(Exception):
        parse_agent_definition(MISSING_REQUIRED_FIELD_YAML)


# ---------------------------------------------------------------------------
# fetch_definition
# ---------------------------------------------------------------------------


def test_fetch_definition_from_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    definition_file = tmp_path / "agent.yaml"
    definition_file.write_text(VALID_YAML)

    result = fetch_definition(str(definition_file))
    assert isinstance(result, AgentDefinition)
    assert result.ref == "example/my-agent"


def test_fetch_definition_missing_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(FileNotFoundError):
        fetch_definition(str(missing))
