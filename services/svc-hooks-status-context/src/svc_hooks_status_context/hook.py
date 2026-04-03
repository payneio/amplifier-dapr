"""Status context pre-hook: injects environmental info before each provider request."""

from __future__ import annotations

import logging
import os
import platform as platform_module
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from amplifier_service_sdk.models import HookResult

logger = logging.getLogger(__name__)

_DAPR_PORT_DEFAULT = "3500"
_MACHINE_APP_ID_DEFAULT = "svc-machine"


class StatusContextHook:
    """Pre-hook on provider:request that injects environmental context.

    Runs synchronously at priority 8, gathering:
    - Working directory (WORKSPACE_DIR env var, defaults to /workspace)
    - Git branch (via svc-machine exec)
    - Git status (modified file count or 'clean')
    - Platform (uname -a via svc-machine exec, falls back to platform module)
    - Current UTC datetime

    Returns INJECT_CONTEXT with ephemeral=True so the context is injected once
    and does not persist. If information gathering fails for any reason, returns
    CONTINUE to avoid blocking the request.
    """

    name: str = "status_context"
    events: list[str] = ["provider:request"]
    priority: int = 8
    mode: Literal["sync", "async"] = "sync"

    async def _exec_on_machine(self, command: str) -> str:
        """Execute a command on svc-machine via Dapr service invocation.

        Returns stdout from the command.
        Raises httpx.HTTPError or RuntimeError on failure.
        """
        port = os.environ.get("DAPR_HTTP_PORT", _DAPR_PORT_DEFAULT)
        app_id = os.environ.get("MACHINE_APP_ID", _MACHINE_APP_ID_DEFAULT)
        url = f"http://localhost:{port}/v1.0/invoke/{app_id}/method/exec"

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={"command": command}, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return str(data.get("stdout", "")).strip()

    async def _gather_info(self) -> dict[str, str]:
        """Gather environmental information.

        Returns a dict with keys: working_dir, git_branch, git_status, platform.
        Raises on any unrecoverable error.
        """
        # Working directory from environment
        working_dir = os.environ.get("WORKSPACE_DIR", "/workspace")

        # Git branch
        git_branch = await self._exec_on_machine("git branch --show-current")

        # Git status — count modified files or report 'clean'
        porcelain = await self._exec_on_machine("git status --porcelain")
        modified_lines = [ln for ln in porcelain.splitlines() if ln.strip()]
        git_status = (
            "clean" if not modified_lines else f"{len(modified_lines)} modified"
        )

        # Platform — try uname -a, fall back to platform module
        try:
            platform_info = await self._exec_on_machine("uname -a")
            if not platform_info:
                raise ValueError("Empty uname output")
        except Exception:
            platform_info = platform_module.platform()

        return {
            "working_dir": working_dir,
            "git_branch": git_branch,
            "git_status": git_status,
            "platform": platform_info,
        }

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Inject status context on provider:request; CONTINUE otherwise."""
        if event != "provider:request":
            return HookResult(action="CONTINUE")

        try:
            info = await self._gather_info()
        except Exception:
            logger.exception("StatusContextHook: failed to gather info, skipping")
            return HookResult(action="CONTINUE")

        now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        content = (
            f'<system-reminder source="hooks-status-context">\n'
            f"Working directory: {info['working_dir']}\n"
            f"Git branch: {info['git_branch']}\n"
            f"Git status: {info['git_status']}\n"
            f"Platform: {info['platform']}\n"
            f"Current time: {now_utc}\n"
            f"</system-reminder>"
        )

        return HookResult(
            action="INJECT_CONTEXT",
            data={"content": content, "ephemeral": True},
        )
