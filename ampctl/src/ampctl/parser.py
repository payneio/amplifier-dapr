"""YAML parser and definition fetcher for ampctl agent definitions."""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml

from ampctl.models import AgentDefinition, AgentDefinitionFile


def parse_agent_definition(yaml_content: str) -> AgentDefinition:
    """Parse a YAML string into an AgentDefinition.

    Args:
        yaml_content: Raw YAML text.

    Returns:
        Validated AgentDefinition instance.

    Raises:
        ValueError: If the top-level 'agent' key is missing.
        pydantic.ValidationError: If the definition is structurally invalid.
    """
    data = yaml.safe_load(yaml_content)
    if not isinstance(data, dict) or "agent" not in data:
        raise ValueError("YAML must have a top-level 'agent' key")
    wrapper = AgentDefinitionFile.model_validate(data)
    return wrapper.agent


def fetch_definition(uri: str) -> AgentDefinition:
    """Load an AgentDefinition from a local file path or HTTPS URL.

    Args:
        uri: A file system path (absolute or with ~) or an https:// URL.

    Returns:
        Validated AgentDefinition instance.

    Raises:
        FileNotFoundError: If the file path does not exist.
        httpx.HTTPStatusError: If the HTTPS request fails.
    """
    if uri.startswith("https://"):
        response = httpx.get(uri)
        response.raise_for_status()
        return parse_agent_definition(response.text)

    path = Path(uri).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Agent definition file not found: {path}")
    return parse_agent_definition(path.read_text())
