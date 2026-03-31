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


class GrepTool(BaseMachineTool):
    """Tool that searches file contents using grep via svc-machine."""

    _timeout_seconds: float = _GREP_TIMEOUT_SECONDS

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
        },
        "required": ["pattern"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Search file contents via the machine service.

        Args:
            params: Tool input dict.  Must contain ``pattern``.
                    Supports optional ``path``.

        Returns:
            ToolResult with success=True and output containing matches.
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

        call = await self._call_machine_safe("/files/grep", payload)
        if call.error is not None:
            return call.error
        return ToolResult(success=True, output=call.data)


class GlobTool(BaseMachineTool):
    """Tool that matches files using glob patterns via svc-machine."""

    _timeout_seconds: float = _GLOB_TIMEOUT_SECONDS

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
        },
        "required": ["pattern"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Match files via the machine service.

        Args:
            params: Tool input dict.  Must contain ``pattern``.
                    Supports optional ``path``.

        Returns:
            ToolResult with success=True and output containing matches.
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

        call = await self._call_machine_safe("/files/glob", payload)
        if call.error is not None:
            return call.error
        return ToolResult(success=True, output=call.data)
