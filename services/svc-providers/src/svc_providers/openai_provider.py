"""OpenAIProvider — OpenAI Chat Completions provider for svc-providers.

Ported from amplifier-providers' openai_provider.py with the following changes:
- amplifier_ipc imports replaced with amplifier_service_sdk models
- @provider decorator removed; inherits from BaseProvider instead
- ChatResponse.content set to plain text string
- TokenUsage instead of Usage (no total_tokens field)
- Message conversion adapted for SDK Message model
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

__all__ = ["OpenAIProvider"]

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS = 16384


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Minimal LLM provider error with retry metadata."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after = retry_after


def _translate_openai_error(error: Exception) -> dict[str, Any]:
    """Translate an OpenAI SDK exception into a dict of error metadata.

    Returns a dict with keys: message, retryable, status_code, retry_after.
    """
    try:
        import openai  # noqa: PLC0415
    except ImportError:
        return {
            "message": str(error),
            "retryable": True,
            "status_code": None,
            "retry_after": None,
        }

    message = str(error)
    retry_after: float | None = None

    if isinstance(error, openai.RateLimitError):
        ra = getattr(getattr(error, "response", None), "headers", {}).get("retry-after")
        if ra is not None:
            try:
                retry_after = float(ra)
            except (TypeError, ValueError):
                pass
        return {
            "message": message,
            "retryable": True,
            "status_code": 429,
            "retry_after": retry_after,
        }

    if isinstance(error, openai.AuthenticationError):
        return {
            "message": message,
            "retryable": False,
            "status_code": 401,
            "retry_after": None,
        }

    if isinstance(error, openai.BadRequestError):
        return {
            "message": message,
            "retryable": False,
            "status_code": 400,
            "retry_after": None,
        }

    if isinstance(error, openai.APIStatusError):
        sc: int = getattr(error, "status_code", 0)
        retryable = sc >= 500
        ra = getattr(getattr(error, "response", None), "headers", {}).get("retry-after")
        if ra is not None:
            try:
                retry_after = float(ra)
            except (TypeError, ValueError):
                pass
        return {
            "message": message,
            "retryable": retryable,
            "status_code": sc,
            "retry_after": retry_after,
        }

    # Generic / unknown errors are retryable
    return {
        "message": message,
        "retryable": True,
        "status_code": None,
        "retry_after": None,
    }


class OpenAIProvider(BaseProvider):
    """OpenAI provider with message-format conversion using Chat Completions API."""

    name = "openai"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the provider.

        Args:
            config: Optional configuration dict. Recognised keys:
                ``api_key``, ``model``, ``max_tokens``, ``temperature``,
                ``reasoning_effort``. Missing keys fall back to environment
                variables or built-in defaults.
        """
        config = config or {}
        self._api_key: str | None = config.get("api_key") or os.environ.get(
            "OPENAI_API_KEY"
        )
        self._client: Any = None  # Lazy-initialised on first .client access
        self.model: str = config.get("model", DEFAULT_MODEL)
        self.max_tokens: int = int(config.get("max_tokens", DEFAULT_MAX_TOKENS))
        self.temperature: float = float(config.get("temperature", 1.0))
        self.reasoning_effort: str | None = config.get("reasoning_effort")

    @property
    def client(self) -> Any:
        """Lazily initialise and return the ``openai.AsyncOpenAI`` client."""
        if self._client is None:
            try:
                import openai  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "The 'openai' package is required. "
                    "Install it with: pip install openai"
                ) from exc
            if self._api_key is None:
                raise ValueError(
                    "An OpenAI API key is required. "
                    "Pass api_key in config or set OPENAI_API_KEY."
                )
            self._client = openai.AsyncOpenAI(
                api_key=self._api_key,
                max_retries=0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Message conversion — SDK Message → OpenAI Chat Completions API
    # ------------------------------------------------------------------

    def _convert_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Convert an SDK Message list to OpenAI Chat Completions format.

        Unlike Anthropic, OpenAI supports system messages directly in the
        messages array. Tool results use role='tool' with tool_call_id.
        """
        result: list[dict[str, Any]] = []

        for msg in messages:
            role: str = getattr(msg, "role", "") or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )

            if role == "system":
                content: Any = getattr(msg, "content", None) or (
                    msg.get("content") if isinstance(msg, dict) else None
                )
                result.append({"role": "system", "content": content or ""})
                continue

            if role == "tool":
                tool_call_id: str | None = getattr(msg, "tool_call_id", None) or (
                    msg.get("tool_call_id") if isinstance(msg, dict) else None
                )
                tool_content: Any = getattr(msg, "content", "") or (
                    msg.get("content", "") if isinstance(msg, dict) else ""
                )
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id or "",
                        "content": tool_content or "",
                    }
                )
                continue

            if role == "assistant":
                assistant_msg = self._convert_assistant_message(msg)
                result.append(assistant_msg)
                continue

            if role in ("user", "developer"):
                user_content = getattr(msg, "content", None) or (
                    msg.get("content") if isinstance(msg, dict) else None
                )
                result.append({"role": "user", "content": user_content or ""})
                continue

            # Unknown role — log and skip
            logger.warning("Unknown message role %r — skipping", role)

        return result

    def _convert_assistant_message(self, msg: Any) -> dict[str, Any]:
        """Convert an assistant Message to OpenAI format."""
        content: Any = getattr(msg, "content", None) or (
            msg.get("content") if isinstance(msg, dict) else None
        )
        tool_calls_field: Any = getattr(msg, "tool_calls", None) or (
            msg.get("tool_calls") if isinstance(msg, dict) else None
        )

        text_content: str | None = None
        tool_calls: list[dict[str, Any]] = []

        if isinstance(content, str):
            text_content = content
        elif isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    btype = item.get("type")
                    if btype in ("tool_use", "tool_call"):
                        tool_calls.append(
                            {
                                "type": "function",
                                "id": item.get("id", ""),
                                "function": {
                                    "name": item.get("name", ""),
                                    "arguments": json.dumps(
                                        item.get("input", {}) or {}
                                    ),
                                },
                            }
                        )
                    elif btype == "text":
                        text = item.get("text", "")
                        if text:
                            text_parts.append(text)
                else:
                    btype = getattr(item, "type", None)
                    if btype in ("tool_use", "tool_call"):
                        tool_calls.append(
                            {
                                "type": "function",
                                "id": getattr(item, "id", ""),
                                "function": {
                                    "name": getattr(item, "name", ""),
                                    "arguments": json.dumps(
                                        getattr(item, "input", {}) or {}
                                    ),
                                },
                            }
                        )
                    elif btype == "text":
                        text = getattr(item, "text", "")
                        if text:
                            text_parts.append(text)
            if text_parts:
                text_content = "\n\n".join(text_parts)

        # Also handle tool_calls field (SDK ToolCall objects)
        if tool_calls_field:
            for tc in tool_calls_field:
                if isinstance(tc, dict):
                    tc_id = tc.get("id", "")
                    tc_name = tc.get("name") or tc.get("tool", "")
                    tc_input = tc.get("arguments") or tc.get("input", {})
                else:
                    tc_id = getattr(tc, "id", "")
                    tc_name = getattr(tc, "name", "") or getattr(tc, "tool", "")
                    tc_input = getattr(tc, "arguments", None) or getattr(
                        tc, "input", {}
                    )
                tool_calls.append(
                    {
                        "type": "function",
                        "id": tc_id,
                        "function": {
                            "name": tc_name,
                            "arguments": json.dumps(tc_input or {}),
                        },
                    }
                )

        out: dict[str, Any] = {"role": "assistant"}
        out["content"] = text_content
        if tool_calls:
            out["tool_calls"] = tool_calls

        return out

    def _convert_tools(self, tools: list[Any]) -> list[dict[str, Any]]:
        """Convert SDK ToolCapability list to OpenAI function tool format."""
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

    def _convert_to_chat_response(self, response: Any) -> ChatResponse:
        """Convert an OpenAI Chat Completions response to SDK ChatResponse.

        Usage extraction
        ----------------
        Maps ``prompt_tokens`` → ``input_tokens``,
        ``completion_tokens`` → ``output_tokens``.
        """
        tool_calls: list[ToolCall] = []

        choice = response.choices[0] if response.choices else None
        message = getattr(choice, "message", None) if choice else None
        finish_reason = getattr(choice, "finish_reason", None) if choice else None

        text_content: str | None = None

        if message is not None:
            # Text content; `or None` coerces empty string "" → None intentionally
            text_content = getattr(message, "content", None) or None

            # Tool calls
            raw_tool_calls = getattr(message, "tool_calls", None)
            if raw_tool_calls:
                for tc in raw_tool_calls:
                    tool_id: str = getattr(tc, "id", "")
                    fn = getattr(tc, "function", None)
                    tool_name: str = getattr(fn, "name", "") if fn else ""
                    raw_arguments: str = getattr(fn, "arguments", "{}") if fn else "{}"

                    # Parse JSON arguments string
                    try:
                        tool_input: dict[str, Any] = json.loads(raw_arguments)
                    except (json.JSONDecodeError, TypeError):
                        tool_input = {}

                    tool_calls.append(
                        ToolCall(id=tool_id, name=tool_name, arguments=tool_input)
                    )

        # --- Usage extraction ---
        usage_obj = response.usage
        input_tokens: int = getattr(usage_obj, "prompt_tokens", 0) or 0
        output_tokens: int = getattr(usage_obj, "completion_tokens", 0) or 0

        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        return ChatResponse(
            content=text_content,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            stop_reason=finish_reason,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Call the OpenAI Chat Completions API and return a ChatResponse."""
        messages_list: list[Any] = list(request.messages)

        # Extract system message content from ChatRequest.system field
        system_content: str | None = request.system

        # Convert messages to OpenAI format
        api_messages = self._convert_messages(messages_list)

        # Prepend system message from request.system if provided and not already in messages
        if system_content:
            has_system = any(m.get("role") == "system" for m in api_messages)
            if not has_system:
                api_messages = [
                    {"role": "system", "content": system_content}
                ] + api_messages

        # Build core API parameters
        model: str = kwargs.get("model", self.model)
        max_tokens_val: int = int(
            request.max_output_tokens or kwargs.get("max_tokens") or self.max_tokens
        )
        api_params: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens_val,
        }

        # Temperature
        api_params["temperature"] = (
            request.temperature if request.temperature is not None else self.temperature
        )

        # Tools
        if request.tools:
            api_params["tools"] = self._convert_tools(request.tools)

        # Reasoning effort (o1/o3 models)
        reasoning_effort: str | None = (
            getattr(request, "reasoning_effort", None)
            or kwargs.get("reasoning_effort")
            or self.reasoning_effort
        )
        if reasoning_effort:
            api_params["reasoning_effort"] = reasoning_effort

        # API call with error translation
        try:
            response = await self.client.chat.completions.create(**api_params)
        except Exception as exc:
            meta = _translate_openai_error(exc)
            raise ProviderError(
                meta["message"],
                retryable=meta["retryable"],
                status_code=meta["status_code"],
                retry_after=meta["retry_after"],
            ) from exc

        return self._convert_to_chat_response(response)
