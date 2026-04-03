"""Search tools for grep and glob operations via svc-machine."""

from __future__ import annotations

from typing import Any, NamedTuple

import httpx

from amplifier_service_sdk.models import ToolResult

_GREP_TIMEOUT_SECONDS = 60
_GLOB_TIMEOUT_SECONDS = 30


class _MachineCallResult(NamedTuple):
    """Return type for ``_call_machine_safe``.

    Attributes:
        error: A ``ToolResult(success=False, ...)`` on failure, or ``None`` on success.
        data:  Parsed response dict on success, or empty dict on failure.
    """

    error: ToolResult | None
    data: dict[str, Any]


class BaseMachineTool:
    """Shared HTTP machinery for tools that delegate to svc-machine."""

    _timeout_seconds: float = 30
    _endpoint_path: str  # subclasses must set this

    def __init__(self, machine_base_url: str) -> None:
        """Initialise the tool with the machine service base URL.

        Args:
            machine_base_url: Base URL for svc-machine (trailing slash stripped).
        """
        self._base_url = machine_base_url.rstrip("/")

    async def _call_machine(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to the machine service endpoint.

        Args:
            path: Endpoint path (e.g. ``/files/grep``).
            payload: JSON request body.

        Returns:
            Parsed JSON response dict from the machine service.
        """
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}{path}",
                json=payload,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def _call_machine_safe(
        self, path: str, payload: dict[str, Any]
    ) -> _MachineCallResult:
        """Call the machine service, converting HTTP errors to ToolResult failures.

        Args:
            path: Endpoint path (e.g. ``/files/grep``).
            payload: JSON request body.

        Returns:
            A ``_MachineCallResult`` with ``error=None`` and ``data`` populated on
            success, or ``error`` set to a ``ToolResult(success=False, ...)`` and
            ``data`` as an empty dict on failure.
        """
        try:
            result = await self._call_machine(path, payload)
            return _MachineCallResult(error=None, data=result)
        except httpx.HTTPStatusError as exc:
            return _MachineCallResult(
                error=ToolResult(
                    success=False,
                    error={
                        "message": f"machine service error: {exc.response.status_code}"
                    },
                ),
                data={},
            )
        except httpx.RequestError as exc:
            return _MachineCallResult(
                error=ToolResult(
                    success=False,
                    error={"message": f"machine service unreachable: {exc}"},
                ),
                data={},
            )

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Forward a pattern-based request to the machine service endpoint.

        Args:
            params: Tool input dict.  Must contain ``pattern``.
                    Supports optional ``path``.

        Returns:
            ToolResult with success=True and output on success, or
            success=False with an error message on failure.
        """
        pattern = params.get("pattern")
        if not pattern:
            return ToolResult(
                success=False,
                error={"message": "pattern is required"},
            )

        payload: dict[str, Any] = {"pattern": pattern}
        if "path" in params:
            payload["path"] = params["path"]

        call = await self._call_machine_safe(self._endpoint_path, payload)
        if call.error is not None:
            return call.error
        return ToolResult(success=True, output=call.data)


class GrepTool(BaseMachineTool):
    """Tool that searches file contents using grep via svc-machine."""

    _timeout_seconds: float = _GREP_TIMEOUT_SECONDS
    _endpoint_path: str = "/files/grep"

    _FORWARD_KEYS: list[str] = [
        "output_mode",
        "glob",
        "type",
        "after_context",
        "before_context",
        "context",
        "case_insensitive",
        "line_numbers",
        "head_limit",
        "offset",
        "include_ignored",
        "multiline",
    ]

    name: str = "grep"
    description: str = "Search file contents with regex patterns"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The regular expression pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in (defaults to current directory)",
            },
            "output_mode": {
                "type": "string",
                "enum": ["files_with_matches", "content", "count"],
                "description": "Output mode: files_with_matches, content, or count",
            },
            "glob": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. '*.js', '**/*.tsx')",
            },
            "type": {
                "type": "string",
                "description": "File type to search (e.g. py, js, ts)",
            },
            "after_context": {
                "type": "integer",
                "description": "Number of lines to show after each match",
            },
            "before_context": {
                "type": "integer",
                "description": "Number of lines to show before each match",
            },
            "context": {
                "type": "integer",
                "description": "Number of lines to show before and after each match",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case insensitive search",
            },
            "line_numbers": {
                "type": "boolean",
                "description": "Show line numbers in output",
            },
            "head_limit": {
                "type": "integer",
                "description": "Limit output to first N entries",
            },
            "offset": {
                "type": "integer",
                "description": "Skip first N entries before applying head_limit",
            },
            "include_ignored": {
                "type": "boolean",
                "description": "Search in normally-excluded directories",
            },
            "multiline": {
                "type": "boolean",
                "description": "Enable multiline mode where patterns can span lines",
            },
        },
        "required": ["pattern"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Forward a grep request to the machine service endpoint.

        Args:
            params: Tool input dict. Must contain ``pattern``.
                    Supports optional ``path`` and all grep parameters.

        Returns:
            ToolResult with success=True and output on success, or
            success=False with an error message on failure.
        """
        pattern = params.get("pattern")
        if not pattern:
            return ToolResult(
                success=False,
                error={"message": "pattern is required"},
            )

        payload: dict[str, Any] = {"pattern": pattern}
        if "path" in params:
            payload["path"] = params["path"]
        for key in self._FORWARD_KEYS:
            if key in params:
                payload[key] = params[key]

        call = await self._call_machine_safe(self._endpoint_path, payload)
        if call.error is not None:
            return call.error
        return ToolResult(success=True, output=call.data)


class GlobTool(BaseMachineTool):
    """Tool that matches files using glob patterns via svc-machine."""

    _timeout_seconds: float = _GLOB_TIMEOUT_SECONDS
    _endpoint_path: str = "/files/glob"

    _FORWARD_KEYS: list[str] = [
        "exclude",
        "type",
        "include_ignored",
    ]

    name: str = "glob"
    description: str = "Match files using glob patterns"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match files (e.g., '**/*.py')",
            },
            "path": {
                "type": "string",
                "description": "Base path to search from (defaults to current directory)",
            },
            "exclude": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Patterns to exclude from results",
            },
            "type": {
                "type": "string",
                "enum": ["file", "dir", "any"],
                "description": "Filter by type: file, dir, or any",
            },
            "include_ignored": {
                "type": "boolean",
                "description": "Search in normally-excluded directories",
            },
        },
        "required": ["pattern"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Forward a glob request to the machine service endpoint.

        Args:
            params: Tool input dict. Must contain ``pattern``.
                    Supports optional ``path`` and all glob parameters.

        Returns:
            ToolResult with success=True and output on success, or
            success=False with an error message on failure.
        """
        pattern = params.get("pattern")
        if not pattern:
            return ToolResult(
                success=False,
                error={"message": "pattern is required"},
            )

        payload: dict[str, Any] = {"pattern": pattern}
        if "path" in params:
            payload["path"] = params["path"]
        for key in self._FORWARD_KEYS:
            if key in params:
                payload[key] = params[key]

        call = await self._call_machine_safe(self._endpoint_path, payload)
        if call.error is not None:
            return call.error
        return ToolResult(success=True, output=call.data)
