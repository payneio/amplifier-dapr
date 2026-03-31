"""Routing pre-hook: injects routing matrix context into provider requests."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from amplifier_service_sdk.models import HookResult

logger = logging.getLogger(__name__)


def load_matrix_from_file(path: Path) -> dict:
    """Load a routing matrix from a YAML file.

    Returns an empty dict if the file is not found or cannot be parsed.
    """
    try:
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class RoutingHook:
    """Sync pre-hook that injects routing matrix context into provider requests."""

    name: str = "routing"
    events: list[str] = ["session:start", "provider:request"]
    priority: int = 5
    mode: Literal["sync", "async"] = "sync"

    def __init__(self, matrix: dict[str, Any]) -> None:
        self.matrix = matrix
        self.effective_matrix: dict[str, Any] = matrix.get("roles", {})

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Evaluate a hook event and return an appropriate HookResult."""
        if event == "session:start":
            return HookResult(action="CONTINUE")
        if event == "provider:request":
            return await self._on_provider_request(data)
        return HookResult(action="CONTINUE")

    async def _on_provider_request(self, data: dict[str, Any]) -> HookResult:
        """Handle provider:request events by injecting routing matrix context."""
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
