"""Shell hook bridge: finds and executes shell scripts for Amplifier events.

Ported from services/amplifier-foundation/src/amplifier_foundation/hooks/shell/bridge.py.
Simplified to use direct hooks_dir with script-based dispatch instead of
config-file-based matcher groups.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from amplifier_service_sdk.models import HookResult

logger = logging.getLogger(__name__)


def _event_to_script_name(event: str) -> str:
    """Convert an Amplifier event name to a shell script name.

    Converts colon-notation ``noun:verb`` to ``verb-noun``.
    For example: ``tool:pre`` -> ``pre-tool``, ``session:start`` -> ``start-session``.
    """
    if ":" in event:
        parts = event.split(":", 1)
        return f"{parts[1]}-{parts[0]}"
    return event


class ShellHookBridge:
    """Bridge that executes shell hook scripts for Amplifier events."""

    def __init__(self, hooks_dir: Path | None) -> None:
        """Initialise the bridge.

        Args:
            hooks_dir: Directory to search for executable hook scripts.
                       Pass ``None`` (or a non-existent path) to disable
                       all hook execution.
        """
        self.hooks_dir = hooks_dir

    def _find_script(self, script_name: str) -> Path | None:
        """Find a matching script file in hooks_dir.

        Looks for files matching the script name, with or without a ``.sh``
        extension. Returns ``None`` if hooks_dir is not set or no match is found.
        """
        if self.hooks_dir is None or not self.hooks_dir.exists():
            return None

        for candidate in [script_name, f"{script_name}.sh"]:
            path = self.hooks_dir / candidate
            if path.exists() and path.is_file():
                return path

        return None

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:  # noqa: ARG002
        """Handle an Amplifier event by running the matching shell script.

        Maps the event name to a script name (e.g. ``tool:pre`` -> ``pre-tool``),
        locates the script in hooks_dir, and executes it.

        Exit-code semantics:
        - ``0``  → CONTINUE  (script succeeded)
        - ``2``  → DENY      (script explicitly denied; stdout/stderr used as reason)
        - other  → CONTINUE  (best-effort; non-fatal failure)

        If no hooks_dir is configured or no matching script is found, returns
        CONTINUE without executing anything.
        """
        script_name = _event_to_script_name(event)
        script_path = self._find_script(script_name)

        if script_path is None:
            return HookResult(action="CONTINUE")

        try:
            proc = await asyncio.create_subprocess_exec(
                str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            exit_code = proc.returncode

            if exit_code == 0:
                return HookResult(action="CONTINUE")

            if exit_code == 2:
                output = (stdout or stderr).decode(errors="replace").strip()
                reason = output or "Denied by shell hook"
                return HookResult(action="DENY", reason=reason)

            # Non-zero exit code other than 2: best-effort, continue
            logger.warning(
                "Hook script %s exited with code %d (treated as CONTINUE)",
                script_path,
                exit_code,
            )
            return HookResult(action="CONTINUE")

        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to execute hook script %s: %s", script_path, exc)
            return HookResult(action="CONTINUE")
