"""Filesystem tools for read, write, and edit operations via svc-machine."""

from __future__ import annotations

from typing import Any, NamedTuple

import httpx

from amplifier_service_sdk.models import ToolResult

_DEFAULT_TIMEOUT_SECONDS = 30


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

    def __init__(self, machine_base_url: str) -> None:
        """Initialise the tool with the machine service base URL.

        Args:
            machine_base_url: Base URL for svc-machine (trailing slash stripped).
        """
        self._base_url = machine_base_url.rstrip("/")

    async def _call_machine(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to the machine service endpoint.

        Args:
            path: Endpoint path (e.g. ``/files/read``).
            payload: JSON request body.

        Returns:
            Parsed JSON response dict from the machine service.
        """
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
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
            path: Endpoint path (e.g. ``/files/read``).
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


class ReadFileTool(BaseMachineTool):
    """Tool that reads file contents by calling svc-machine over HTTP."""

    name: str = "read_file"
    description: str = "Read file contents from the filesystem"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to read",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
            },
        },
        "required": ["file_path"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Read file contents via the machine service.

        Args:
            params: Tool input dict.  Must contain ``file_path``.
                    Supports optional ``offset`` and ``limit``.

        Returns:
            ToolResult with success=True and output containing file content.
        """
        file_path = params.get("file_path")
        if not file_path:
            return ToolResult(
                success=False,
                error={"message": "file_path is required"},
            )

        payload: dict[str, Any] = {"path": file_path}
        if "offset" in params:
            payload["offset"] = params["offset"]
        if "limit" in params:
            payload["limit"] = params["limit"]

        call = await self._call_machine_safe("/files/read", payload)
        if call.error is not None:
            return call.error
        return ToolResult(success=True, output=call.data)


class WriteFileTool(BaseMachineTool):
    """Tool that writes file contents by calling svc-machine over HTTP."""

    name: str = "write_file"
    description: str = "Write content to a file on the filesystem"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file",
            },
        },
        "required": ["file_path", "content"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Write file contents via the machine service.

        Args:
            params: Tool input dict.  Must contain ``file_path`` and ``content``.

        Returns:
            ToolResult with success=True on successful write.
        """
        file_path = params.get("file_path")
        if not file_path:
            return ToolResult(
                success=False,
                error={"message": "file_path is required"},
            )

        content = params.get("content")
        if content is None:
            return ToolResult(
                success=False,
                error={"message": "content is required"},
            )

        payload: dict[str, Any] = {"path": file_path, "content": content}

        call = await self._call_machine_safe("/files/write", payload)
        if call.error is not None:
            return call.error
        return ToolResult(success=True, output=call.data)


class EditFileTool(BaseMachineTool):
    """Tool that edits file contents by replacing strings via svc-machine."""

    name: str = "edit_file"
    description: str = "Edit a file by replacing a string with another string"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit",
            },
            "old_string": {
                "type": "string",
                "description": "The string to find and replace",
            },
            "new_string": {
                "type": "string",
                "description": "The replacement string",
            },
            "replace_all": {
                "type": "boolean",
                "default": False,
                "description": "If true, replace all occurrences; otherwise replace only the first",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Edit file contents via the machine service.

        Args:
            params: Tool input dict.  Must contain ``file_path``, ``old_string``,
                    and ``new_string``.  Supports optional ``replace_all``.

        Returns:
            ToolResult with success=True on successful edit.
        """
        file_path = params.get("file_path")
        if not file_path:
            return ToolResult(
                success=False,
                error={"message": "file_path is required"},
            )

        old_string = params.get("old_string")
        if old_string is None:
            return ToolResult(
                success=False,
                error={"message": "old_string is required"},
            )

        new_string = params.get("new_string")
        if new_string is None:
            return ToolResult(
                success=False,
                error={"message": "new_string is required"},
            )

        if old_string == new_string:
            return ToolResult(
                success=False,
                error={"message": "old_string and new_string must differ"},
            )

        payload: dict[str, Any] = {
            "path": file_path,
            "old_string": old_string,
            "new_string": new_string,
        }
        if "replace_all" in params:
            payload["replace_all"] = params["replace_all"]

        call = await self._call_machine_safe("/files/edit", payload)
        if call.error is not None:
            return call.error
        return ToolResult(success=True, output=call.data)
