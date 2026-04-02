"""CLI entry point for amplifier-serve."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from amplifier_service_sdk.models import (
    AgentCapability,
    HookRegistration,
    ModeCapability,
    ToolCapability,
)
from amplifier_service_sdk.service import ServiceConfig, create_app


def load_config_from_yaml(config_path: Path) -> ServiceConfig:
    """Load a ServiceConfig from a YAML file.

    - Reads YAML with yaml.safe_load
    - Resolves content_dir relative to the YAML file's parent directory
    - Converts the tools list to ToolCapability objects via model_validate
    - Converts the modes list to ModeCapability objects via model_validate
    - Converts the agents list to AgentCapability objects via model_validate
    - Returns a fully populated ServiceConfig
    """
    raw: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}

    name: str = raw["name"]
    version: str = raw.get("version", "0.1.0")

    content_dir: str | None = None
    if "content_dir" in raw and raw["content_dir"] is not None:
        content_dir = str((config_path.parent / raw["content_dir"]).resolve())

    tools: list[ToolCapability] = [
        ToolCapability.model_validate(t) for t in raw.get("tools") or []
    ]
    hooks: list[HookRegistration] = [
        HookRegistration.model_validate(h) for h in raw.get("hooks") or []
    ]
    providers: list[dict[str, Any]] = raw.get("providers") or []
    modes: list[ModeCapability] = [
        ModeCapability.model_validate(m) for m in raw.get("modes") or []
    ]
    agents: list[AgentCapability] = [
        AgentCapability.model_validate(a) for a in raw.get("agents") or []
    ]

    return ServiceConfig(
        name=name,
        version=version,
        content_dir=content_dir,
        tools=tools,
        hooks=hooks,
        providers=providers,
        modes=modes,
        agents=agents,
    )


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for amplifier-serve."""
    parser = argparse.ArgumentParser(
        prog="amplifier-serve",
        description="Run an Amplifier-compatible microservice",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to service YAML configuration file",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind the server to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the server to (default: 8000)",
    )

    args = parser.parse_args(argv)

    config = load_config_from_yaml(args.config)
    app = create_app(config)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
