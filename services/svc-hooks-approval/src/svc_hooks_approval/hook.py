"""Approval pre-hook: allow-list, deny-list, argument inspection, and risk metadata checks."""

from __future__ import annotations

import fnmatch
import re
from typing import Any, Literal

from amplifier_service_sdk.models import HookResult

# ---------------------------------------------------------------------------
# Dangerous bash command patterns — compiled once at import time
# ---------------------------------------------------------------------------

_DANGEROUS_BASH_PATTERNS: list[re.Pattern[str]] = [
    # rm with recursive flag targeting / (e.g. "rm -rf /", "rm -r /")
    re.compile(r"rm\s+-[^\s]*r[^\s]*\s+/"),
    # sudo rm in any form
    re.compile(r"sudo\s+rm\b"),
    # make-filesystem commands (mkfs, mkfs.ext4, mkswap …)
    re.compile(r"\bmkfs\b"),
    # dd writing to a raw device (of=/dev/…)
    re.compile(r"\bdd\b.*\bof=/dev/"),
    # chmod 777 on any absolute path — matches "chmod 777 /", "chmod 777 /etc",
    # "chmod 777 /home/user", etc.  The spec targets "/"; the regex is intentionally
    # broader, flagging world-writable permissions on any system directory.
    re.compile(r"chmod\s+777\s+/"),
    # fork-bomb pattern  :(){:|:&};:
    re.compile(r":\(\)\s*\{.*:\s*\|.*:&"),
    # redirecting to a raw block/char device
    re.compile(r">\s*/dev/[shd]"),
]


class ApprovalHook:
    """Sync pre-hook with allow-list, deny-list, argument inspection, and risk metadata."""

    name: str = "approval"
    events: list[str] = ["tool:pre"]
    priority: int = 5
    # "sync" signals the SDK dispatcher to invoke this hook synchronously
    # (i.e. before the tool executes), not that handle() itself is blocking.
    # The async def is required by the SDK's awaitable hook protocol.
    mode: Literal["sync", "async"] = "sync"

    def __init__(self, config: dict[str, Any]) -> None:
        self.deny_tools: list[str] = config.get("deny_tools", [])
        self.allow_tools: list[str] = config.get("allow_tools", [])

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Evaluate a hook event and return CONTINUE or DENY.

        Check order:
          1. Non-tool:pre events → CONTINUE
          2. Missing tool_name → CONTINUE
          3. Deny-list (takes precedence over allow-list)
          4. Allow-list (if configured, unlisted tools are denied)
          5. Risk metadata (requires_approval flag)
          6. Bash argument inspection
        """
        if event != "tool:pre":
            return HookResult(action="CONTINUE")

        tool_name: str = data.get("tool_name", "")
        if not tool_name:
            return HookResult(action="CONTINUE")

        # ------------------------------------------------------------------
        # 3. Deny-list check (highest priority)
        # ------------------------------------------------------------------
        for pattern in self.deny_tools:
            if fnmatch.fnmatch(tool_name, pattern):
                return HookResult(
                    action="DENY",
                    reason=f"Tool '{tool_name}' is denied by pattern '{pattern}'",
                )

        # ------------------------------------------------------------------
        # 4. Allow-list check (only applied when allow_tools is non-empty)
        # ------------------------------------------------------------------
        if self.allow_tools:
            allowed = any(fnmatch.fnmatch(tool_name, p) for p in self.allow_tools)
            if not allowed:
                return HookResult(
                    action="DENY",
                    reason=f"Tool '{tool_name}' is not in allow-list",
                )

        # ------------------------------------------------------------------
        # 5. Risk metadata check
        # ------------------------------------------------------------------
        metadata: dict[str, Any] = data.get("metadata") or {}
        if metadata.get("requires_approval") is True:
            risk_level = metadata.get("risk_level", "unknown")
            return HookResult(
                action="DENY",
                reason=(
                    f"Tool '{tool_name}' requires approval (risk_level={risk_level})"
                ),
            )

        # ------------------------------------------------------------------
        # 6. Bash argument inspection
        # ------------------------------------------------------------------
        if tool_name == "bash":
            arguments: dict[str, Any] = data.get("arguments") or {}
            command: str = arguments.get("command", "")
            for dangerous in _DANGEROUS_BASH_PATTERNS:
                if dangerous.search(command):
                    return HookResult(
                        action="DENY",
                        reason=(
                            f"Dangerous command pattern detected in bash arguments: "
                            f"{dangerous.pattern!r}"
                        ),
                    )

        return HookResult(action="CONTINUE")
