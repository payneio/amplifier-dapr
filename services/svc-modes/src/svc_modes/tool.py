"""ModeTool — agent-initiated mode management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from amplifier_service_sdk.models import ToolResult

from svc_modes.hook import ModeDefinition, ModeHooks, parse_mode_file

logger = logging.getLogger(__name__)


class ModeTool:
    """Tool for agent-initiated mode management.

    Operations:
        list    - List all available modes (discovers from .amplifier/modes/)
        current - Show the currently active mode
        set     - Activate a mode by name
        clear   - Deactivate the currently active mode
    """

    name = "mode"
    description = (
        "Manage runtime modes. Operations: 'set' (activate a mode), "
        "'clear' (deactivate), 'list' (show available), 'current' (show active). "
        "Mode transitions may require confirmation depending on gate policy."
    )

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["set", "clear", "list", "current"],
                "description": "Operation to perform",
            },
            "name": {
                "type": "string",
                "description": "Mode name (required for 'set' operation)",
            },
        },
        "required": ["operation"],
    }

    _mode_hooks: ModeHooks | None = None

    def _not_ready_result(self) -> ToolResult:
        return ToolResult(
            success=False,
            error={"code": "not_ready", "message": "Mode service not ready"},
        )

    def _discover_modes(self) -> list[ModeDefinition]:
        """Discover mode definitions from .amplifier/modes/ directories."""
        modes_by_name: dict[str, ModeDefinition] = {}
        # User-level first so project-level overwrites on collision
        for base in [Path.home(), Path.cwd()]:
            mode_dir = base / ".amplifier" / "modes"
            if not mode_dir.is_dir():
                continue
            for file_path in sorted(mode_dir.glob("*.md")):
                mode = parse_mode_file(file_path)
                if mode is not None:
                    mode.source = str(file_path)
                    modes_by_name[mode.name] = mode
        return list(modes_by_name.values())

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Dispatch a mode operation."""
        operation = input.get("operation", "")

        if operation == "list":
            return await self._handle_list()
        elif operation == "current":
            return await self._handle_current()
        elif operation == "set":
            return await self._handle_set(input)
        elif operation == "clear":
            return await self._handle_clear()
        else:
            return ToolResult(
                success=False,
                error={
                    "code": "invalid_operation",
                    "message": (
                        f"Unknown operation '{operation}'. "
                        "Use: set, clear, list, current"
                    ),
                },
            )

    async def _handle_list(self) -> ToolResult:
        if self._mode_hooks is None:
            return self._not_ready_result()
        modes = self._discover_modes()
        return ToolResult(
            success=True,
            output={
                "modes": [
                    {
                        "name": m.name,
                        "description": m.description,
                        "shortcut": m.shortcut,
                    }
                    for m in modes
                ]
            },
        )

    async def _handle_current(self) -> ToolResult:
        if self._mode_hooks is None:
            return self._not_ready_result()
        mode = self._mode_hooks.get_active_mode()
        if mode is None:
            return ToolResult(
                success=True,
                output={"active_mode": None, "message": "No mode is currently active."},
            )
        return ToolResult(
            success=True,
            output={"active_mode": mode.name, "description": mode.description},
        )

    async def _handle_set(self, input: dict[str, Any]) -> ToolResult:
        if self._mode_hooks is None:
            return self._not_ready_result()
        name = input.get("name")
        if not name:
            return ToolResult(
                success=False,
                error={
                    "code": "missing_name",
                    "message": "The 'name' parameter is required for set.",
                },
            )
        modes = self._discover_modes()
        mode = next((m for m in modes if m.name == name), None)
        if mode is None:
            available = [m.name for m in modes]
            return ToolResult(
                success=False,
                error={
                    "code": "unknown_mode",
                    "message": f"Mode '{name}' not found.",
                    "available": available,
                },
            )
        self._mode_hooks.set_active_mode(mode)
        return ToolResult(
            success=True,
            output={
                "name": mode.name,
                "description": mode.description,
                "message": f"Mode '{mode.name}' activated.",
            },
        )

    async def _handle_clear(self) -> ToolResult:
        if self._mode_hooks is None:
            return self._not_ready_result()
        self._mode_hooks.clear_active_mode()
        return ToolResult(
            success=True,
            output={"status": "cleared", "message": "Mode deactivated."},
        )
