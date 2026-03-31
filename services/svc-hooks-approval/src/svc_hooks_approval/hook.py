"""Approval pre-hook: denies tools matching configured glob patterns."""

from __future__ import annotations

import fnmatch
from typing import Any

from amplifier_service_sdk.models import HookResult


class ApprovalHook:
    """Sync pre-hook that blocks tools matching deny-list glob patterns."""

    name: str = "approval"
    events: list[str] = ["tool:pre"]
    priority: int = 5
    mode: str = "sync"

    def __init__(self, config: dict[str, Any]) -> None:
        self.deny_tools: list[str] = config.get("deny_tools", [])

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Evaluate a hook event and return CONTINUE or DENY."""
        if event != "tool:pre":
            return HookResult(action="CONTINUE")

        tool_name: str = data.get("tool_name", "")
        if not tool_name:
            return HookResult(action="CONTINUE")

        for pattern in self.deny_tools:
            if fnmatch.fnmatch(tool_name, pattern):
                return HookResult(
                    action="DENY",
                    reason=f"Tool '{tool_name}' is denied by pattern '{pattern}'",
                )

        return HookResult(action="CONTINUE")
