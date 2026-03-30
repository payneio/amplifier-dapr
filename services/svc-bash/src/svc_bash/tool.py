"""BashTool — executes shell commands by calling svc-machine via httpx."""

from __future__ import annotations

from typing import Any

import httpx

from amplifier_service_sdk.models import ToolResult

_DEFAULT_TIMEOUT_SECONDS = 30


class BashTool:
    """Tool that forwards bash command execution to svc-machine over HTTP."""

    name: str = "bash"
    description: str = "Execute shell commands on the machine service"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "default": _DEFAULT_TIMEOUT_SECONDS,
                "description": "Command timeout in seconds",
            },
            "run_in_background": {
                "type": "boolean",
                "default": False,
                "description": "Run the command in the background",
            },
        },
        "required": ["command"],
    }

    def __init__(self, machine_base_url: str) -> None:
        """Initialise the tool with the machine service base URL.

        Args:
            machine_base_url: Base URL for svc-machine (trailing slash stripped).
        """
        self._base_url = machine_base_url.rstrip("/")

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute a bash command via the machine service.

        Args:
            input: Tool input dict.  Must contain ``command``.

        Returns:
            ToolResult with success=(exit_code==0) and output containing
            stdout, stderr, and returncode.
        """
        command = input.get("command")
        if not command:
            return ToolResult(
                success=False,
                error={"message": "command is required"},
            )

        timeout = int(input.get("timeout", _DEFAULT_TIMEOUT_SECONDS))

        machine_result = await self._call_machine_exec(command, timeout)

        exit_code: int = machine_result.get("exit_code", 1)
        return ToolResult(
            success=(exit_code == 0),
            output={
                "stdout": machine_result.get("stdout", ""),
                "stderr": machine_result.get("stderr", ""),
                "returncode": exit_code,
            },
        )

    async def _call_machine_exec(
        self, command: str, timeout: int = _DEFAULT_TIMEOUT_SECONDS
    ) -> dict[str, Any]:
        """POST to the machine service /exec endpoint.

        Args:
            command: Shell command string.
            timeout: Command-level timeout in seconds.

        Returns:
            Parsed JSON response dict from the machine service.
        """
        # run_in_background is declared in the schema for future use but not yet forwarded
        http_timeout = timeout + 10
        async with httpx.AsyncClient(timeout=http_timeout) as client:
            response = await client.post(
                f"{self._base_url}/exec",
                json={"command": command, "timeout": timeout},
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
