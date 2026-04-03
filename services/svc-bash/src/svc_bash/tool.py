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

    def get_metadata(self) -> dict[str, Any]:
        return {"requires_approval": True, "risk_level": "high"}

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
        run_in_background = input.get("run_in_background", False)

        try:
            machine_result = await self._call_machine_exec(
                command, timeout, run_in_background=run_in_background
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                try:
                    detail = exc.response.json().get("detail", {})
                    reason = detail.get("reason", "safety policy")
                except Exception:
                    reason = "safety policy"
                return ToolResult(
                    success=False,
                    error={"message": f"Command denied: {reason}"},
                )
            return ToolResult(
                success=False,
                error={"message": f"machine service error: {exc.response.status_code}"},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                error={"message": f"machine service unreachable: {exc}"},
            )

        if run_in_background:
            return ToolResult(
                success=True,
                output={
                    "pid": machine_result.get("pid"),
                    "status": machine_result.get("status"),
                },
            )

        exit_code: int = machine_result.get("exit_code", 1)
        output: dict[str, Any] = {
            "stdout": machine_result.get("stdout", ""),
            "stderr": machine_result.get("stderr", ""),
            "returncode": exit_code,
        }
        if "truncated" in machine_result:
            output["truncated"] = machine_result["truncated"]
        return ToolResult(
            success=(exit_code == 0),
            output=output,
        )

    async def _call_machine_exec(
        self,
        command: str,
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
        run_in_background: bool = False,
    ) -> dict[str, Any]:
        """POST to the machine service /exec endpoint.

        Args:
            command: Shell command string.
            timeout: Command-level timeout in seconds.
            run_in_background: Whether to run the command in the background.

        Returns:
            Parsed JSON response dict from the machine service.
        """
        http_timeout = timeout + 10
        payload: dict[str, Any] = {"command": command, "timeout": timeout}
        if run_in_background:
            payload["run_in_background"] = True
        async with httpx.AsyncClient(timeout=http_timeout) as client:
            response = await client.post(
                f"{self._base_url}/exec",
                json=payload,
            )
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
