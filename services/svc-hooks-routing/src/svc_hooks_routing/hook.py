"""Routing pre-hook: resolves model_role to provider/model and injects routing context."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from amplifier_service_sdk.models import HookResult

logger = logging.getLogger(__name__)


def load_matrix_from_file(path: Path) -> dict:
    """Load a routing matrix from a YAML file.

    Returns an empty dict if the file is not found or cannot be parsed.
    """
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except (
        FileNotFoundError,
        PermissionError,
        OSError,
        yaml.YAMLError,
        UnicodeDecodeError,
    ):
        logger.warning("Failed to load routing matrix from %s", path)
        return {}


class RoutingHook:
    """Sync pre-hook that resolves model_role to a concrete provider/model.

    If model_role is present in the request data, looks it up in the routing
    matrix and returns a MODIFY action with the resolved provider and model
    merged into the original data.

    If model_role is absent but the matrix has roles defined, returns an
    INJECT_CONTEXT action with a text overview of available roles so the LLM
    can make informed routing decisions.
    """

    name: str = "routing"
    events: list[str] = ["session:start", "provider:request"]
    priority: int = 5
    mode: Literal["sync", "async"] = "sync"

    def __init__(self, matrix: dict[str, Any]) -> None:
        self.matrix = matrix
        self.effective_matrix: dict[str, Any] = matrix.get("roles", {})

    def resolve(self, model_role: str) -> dict[str, str] | None:
        """Resolve a model_role to its first candidate's provider and model.

        Returns a dict with 'provider' and 'model' keys, or None if:
        - The role is not found in the matrix
        - The role has no candidates
        - The first candidate is missing 'provider' or 'model'
        """
        role_info = self.effective_matrix.get(model_role)
        if not isinstance(role_info, dict):
            return None

        candidates = role_info.get("candidates", [])
        if not candidates:
            return None

        first = candidates[0]
        provider = first.get("provider")
        model = first.get("model")
        if not provider or not model:
            return None

        return {"provider": provider, "model": model}

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Evaluate a hook event and return an appropriate HookResult."""
        if event == "session:start":
            return HookResult(action="CONTINUE")
        if event == "provider:request":
            return await self._on_provider_request(data)
        return HookResult(action="CONTINUE")

    async def _on_provider_request(self, data: dict[str, Any]) -> HookResult:
        """Handle provider:request events.

        When model_role is in the request data:
          - Resolve it to a provider/model pair
          - Return MODIFY with the original data merged with the resolved pair
          - Return CONTINUE if the role cannot be resolved

        When model_role is absent and the matrix has roles:
          - Return INJECT_CONTEXT with an overview of available roles
        """
        model_role = data.get("model_role")

        if model_role is not None:
            resolved = self.resolve(model_role)
            if resolved is None:
                return HookResult(action="CONTINUE")
            merged = {**data, **resolved}
            return HookResult(action="MODIFY", data=merged)

        # No model_role in data — inject context if we have a matrix
        if not self.effective_matrix:
            return HookResult(action="CONTINUE")

        matrix_name = self.matrix.get("name", "unknown")
        lines = [f"Routing Matrix: {matrix_name}", "Available roles:"]
        for role_name, role_info in self.effective_matrix.items():
            if isinstance(role_info, dict):
                description = role_info.get("description", "")
                lines.append(f"- {role_name}: {description}")
            else:
                lines.append(f"- {role_name}")

        context_text = "\n".join(lines)
        return HookResult(
            action="INJECT_CONTEXT",
            data={"context_injection": context_text, "ephemeral": True},
        )
