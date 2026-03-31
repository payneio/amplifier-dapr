"""OllamaProvider — local model support via the ollama Python SDK for svc-providers.

Ported from amplifier-providers' ollama_provider.py with the following changes:
- amplifier_ipc imports replaced with amplifier_service_sdk models
- @provider decorator removed; inherits from BaseProvider instead
- ChatResponse.content set to plain text string
- TokenUsage instead of Usage (no total_tokens field)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from amplifier_service_sdk.models import (
    ChatRequest,
    ChatResponse,
    TokenUsage,
    ToolCall,
)

from svc_providers.base import BaseProvider

__all__ = ["OllamaProvider"]

logger = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"


class OllamaProvider(BaseProvider):
    """Ollama provider for local model support via the ollama Python SDK."""

    name = "ollama"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the provider.

        Args:
            config: Optional configuration dict. Recognised keys:
                ``host``, ``model``. Missing keys fall back to environment
                variables or built-in defaults.

                - ``host``: Ollama server URL. Falls back to ``OLLAMA_HOST``
                  env var, then ``http://localhost:11434``.
                - ``model``: Model name. Defaults to ``llama3.1``.
        """
        config = config or {}
        self.host: str = (
            config.get("host") or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
        )
        self.model: str = config.get("model", DEFAULT_MODEL)
        self._client: Any = None  # Lazy-initialised on first .client access

    @property
    def client(self) -> Any:
        """Lazily initialise and return the ``ollama.AsyncClient``."""
        if self._client is None:
            try:
                import ollama  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "The 'ollama' package is required.  "
                    "Install it with: pip install ollama"
                ) from exc
            self._client = ollama.AsyncClient(host=self.host)
        return self._client

    # ------------------------------------------------------------------
    # Message conversion — SDK Message → Ollama format
    # ------------------------------------------------------------------

    def _convert_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Convert an SDK Message list to Ollama chat format.

        Ollama uses the same role/content format as OpenAI:
        ``{"role": "user" | "assistant" | "system" | "tool", "content": "..."}``.
        """
        result: list[dict[str, Any]] = []

        for msg in messages:
            role: str = getattr(msg, "role", "") or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )
            content: Any = getattr(msg, "content", None) or (
                msg.get("content") if isinstance(msg, dict) else None
            )

            if role in ("system", "user", "assistant"):
                # Simple string content — pass through directly
                if isinstance(content, str):
                    result.append({"role": role, "content": content})
                elif isinstance(content, list):
                    # Flatten list content to text
                    parts: list[str] = []
                    for item in content:
                        text = (
                            item.get("text")
                            if isinstance(item, dict)
                            else getattr(item, "text", None)
                        )
                        if text:
                            parts.append(text)
                        elif isinstance(item, str):
                            parts.append(item)
                    result.append({"role": role, "content": "\n\n".join(parts)})
                else:
                    result.append({"role": role, "content": content or ""})
                continue

            if role == "tool":
                tool_call_id: str | None = getattr(msg, "tool_call_id", None) or (
                    msg.get("tool_call_id") if isinstance(msg, dict) else None
                )
                tool_content: str = (
                    content if isinstance(content, str) else str(content or "")
                )
                result.append(
                    {
                        "role": "tool",
                        "content": tool_content,
                        "tool_call_id": tool_call_id or "",
                    }
                )
                continue

            # Unknown role — log and skip
            logger.warning("Unknown message role %r — skipping", role)

        return result

    def _convert_tools_from_request(self, tools: list[Any]) -> list[dict[str, Any]]:
        """Convert SDK ToolCapability objects to Ollama tool format.

        Ollama uses the same OpenAI-compatible function format::

            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            }
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": getattr(tool, "description", "") or "",
                    "parameters": getattr(tool, "input_schema", None) or {},
                },
            }
            for tool in tools
        ]

    def _convert_to_chat_response(self, response: dict[str, Any]) -> ChatResponse:
        """Convert an Ollama dict response to ChatResponse.

        Token counts:
        - ``eval_count``        → ``output_tokens``
        - ``prompt_eval_count`` → ``input_tokens``
        """
        tool_calls: list[ToolCall] = []

        message = response.get("message", {})
        text_content: str | None = message.get("content") if message else None
        raw_tool_calls: list[Any] | None = (
            message.get("tool_calls") if message else None
        )

        if raw_tool_calls:
            for tc in raw_tool_calls:
                # Ollama tool call format (OpenAI-compatible):
                # {"function": {"name": "...", "arguments": {...}}}
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                tool_name: str = fn.get("name", "") if fn else ""
                raw_args: Any = fn.get("arguments", {}) if fn else {}

                # Arguments may be a dict already or a JSON string
                if isinstance(raw_args, str):
                    try:
                        tool_input: dict[str, Any] = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {}
                elif isinstance(raw_args, dict):
                    tool_input = raw_args
                else:
                    tool_input = {}

                # Ollama doesn't always provide a tool call ID
                tool_id: str = tc.get("id", "") if isinstance(tc, dict) else ""

                tool_calls.append(
                    ToolCall(id=tool_id, name=tool_name, arguments=tool_input)
                )

        # --- Usage extraction ---
        # Some models don't report tokens — default to 0
        output_tokens: int = response.get("eval_count") or 0
        input_tokens: int = response.get("prompt_eval_count") or 0

        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        return ChatResponse(
            content=text_content or None,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            stop_reason="stop" if response.get("done") else None,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Call the Ollama chat API and return a ChatResponse."""
        messages_list: list[Any] = list(request.messages)
        api_messages = self._convert_messages(messages_list)

        model: str = kwargs.get("model", self.model)
        api_params: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
        }

        # Tools (only if request has tools)
        if request.tools:
            api_params["tools"] = self._convert_tools_from_request(request.tools)

        # API call
        try:
            response = await self.client.chat(**api_params)
        except Exception as exc:
            exc_str = str(exc)
            raise RuntimeError(f"Ollama API call failed: {exc_str}") from exc

        return self._convert_to_chat_response(response)
