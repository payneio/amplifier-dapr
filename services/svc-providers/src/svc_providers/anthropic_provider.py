"""AnthropicProvider — Anthropic Claude provider for svc-providers.

Ported from amplifier-providers' anthropic_provider.py with the following changes:
- amplifier_ipc imports replaced with amplifier_service_sdk models
- @provider decorator removed; inherits from BaseProvider instead
- ChatResponse.content set to plain text string
- TokenUsage instead of Usage (no cache/total fields)
- Message conversion adapted for SDK Message model
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from typing import Any

from amplifier_service_sdk.models import (
    ChatRequest,
    ChatResponse,
    TokenUsage,
    ToolCall,
)

from svc_providers.base import BaseProvider

__all__ = ["AnthropicProvider"]

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
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


def _translate_anthropic_error(error: Exception) -> dict[str, Any]:
    """Translate an Anthropic SDK exception into error metadata dict."""
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return {
            "message": str(error),
            "retryable": True,
            "status_code": None,
            "retry_after": None,
        }

    message = str(error)
    retry_after: float | None = None

    if isinstance(error, anthropic.RateLimitError):
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

    if isinstance(error, anthropic.AuthenticationError):
        return {
            "message": message,
            "retryable": False,
            "status_code": 401,
            "retry_after": None,
        }

    if isinstance(error, anthropic.BadRequestError):
        return {
            "message": message,
            "retryable": False,
            "status_code": 400,
            "retry_after": None,
        }

    if isinstance(error, anthropic.APIStatusError):
        sc: int = getattr(error, "status_code", 0)
        retryable = sc >= 500 or sc == 529
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


async def retry_with_backoff(
    fn: Any,
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> Any:
    """Retry an async callable with exponential backoff."""
    attempt = 0
    delay = initial_delay

    while True:
        try:
            return await fn()
        except ProviderError as exc:
            if not exc.retryable:
                raise
            if attempt >= max_retries:
                raise
            wait = exc.retry_after if exc.retry_after is not None else delay
            if jitter:
                wait = wait * (0.5 + random.random())
            wait = min(wait, max_delay)
            if wait > 0:
                await asyncio.sleep(wait)
            delay = min(delay * 2, max_delay)
            attempt += 1
        except Exception:
            if attempt >= max_retries:
                raise
            wait = delay
            if jitter:
                wait = wait * (0.5 + random.random())
            wait = min(wait, max_delay)
            if wait > 0:
                await asyncio.sleep(wait)
            delay = min(delay * 2, max_delay)
            attempt += 1


@dataclass
class _RateLimitState:
    """Tracks rate-limit capacity from Anthropic response headers."""

    requests_limit: int | None = None
    requests_remaining: int | None = None
    requests_reset: str | None = None
    tokens_limit: int | None = None
    tokens_remaining: int | None = None
    tokens_reset: str | None = None
    retry_after: float | None = None

    async def maybe_throttle(self) -> None:
        """Sleep if retry_after > 0, then clear the value."""
        if self.retry_after and self.retry_after > 0:
            await asyncio.sleep(self.retry_after)
            self.retry_after = None

    def update_from_response(self, response: Any) -> None:
        """Extract rate-limit headers from an Anthropic API response."""
        raw_headers: Any = None
        for attr in ("http_response", "_response", "response"):
            candidate = getattr(response, attr, None)
            if candidate is not None:
                raw_headers = getattr(candidate, "headers", None)
                if raw_headers is not None:
                    break
        if raw_headers is None:
            raw_headers = getattr(response, "headers", None)
        if raw_headers is None:
            return

        def _get(key: str) -> str | None:
            try:
                return raw_headers.get(key)
            except Exception:
                return None

        mapping: list[tuple[str, str, type]] = [
            ("anthropic-ratelimit-requests-limit", "requests_limit", int),
            ("anthropic-ratelimit-requests-remaining", "requests_remaining", int),
            ("anthropic-ratelimit-tokens-limit", "tokens_limit", int),
            ("anthropic-ratelimit-tokens-remaining", "tokens_remaining", int),
            ("retry-after", "retry_after", float),
        ]
        for header, attr, cast in mapping:
            val = _get(header)
            if val is not None:
                try:
                    setattr(self, attr, cast(val))
                except (TypeError, ValueError):
                    pass


class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider with message-format conversion."""

    name = "anthropic"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the provider.

        Args:
            config: Optional configuration dict. Recognised keys:
                ``api_key``, ``model``, ``max_tokens``. Missing keys fall back
                to environment variables or built-in defaults.
        """
        config = config or {}
        self._api_key: str | None = config.get("api_key") or os.environ.get(
            "ANTHROPIC_API_KEY"
        )
        self._client: Any = None  # Lazy-initialised on first .client access
        self.model: str = config.get("model", DEFAULT_MODEL)
        self.max_tokens: int = int(config.get("max_tokens", DEFAULT_MAX_TOKENS))
        self._rate_limit_state = _RateLimitState()

    @property
    def client(self) -> Any:
        """Lazily initialise and return the ``anthropic.AsyncAnthropic`` client."""
        if self._client is None:
            try:
                import anthropic  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "The 'anthropic' package is required. "
                    "Install it with: pip install anthropic"
                ) from exc
            if self._api_key is None:
                raise ValueError(
                    "An Anthropic API key is required. "
                    "Pass api_key in config or set ANTHROPIC_API_KEY."
                )
            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
                max_retries=0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Message conversion — SDK Message → Anthropic Messages API
    # ------------------------------------------------------------------

    def _convert_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Convert an SDK Message list to Anthropic Messages API format."""
        result: list[dict[str, Any]] = []
        i = 0

        while i < len(messages):
            msg = messages[i]
            role: str = getattr(msg, "role", "") or (
                msg.get("role", "") if isinstance(msg, dict) else ""
            )

            if role == "system":
                i += 1
                continue

            if role == "tool":
                # Batch all consecutive tool-result messages into ONE user message.
                tool_results: list[dict[str, Any]] = []
                while i < len(messages):
                    cur = messages[i]
                    cur_role = getattr(cur, "role", "") or (
                        cur.get("role", "") if isinstance(cur, dict) else ""
                    )
                    if cur_role != "tool":
                        break
                    tool_call_id: str | None = getattr(cur, "tool_call_id", None) or (
                        cur.get("tool_call_id") if isinstance(cur, dict) else None
                    )
                    tool_content: Any = getattr(cur, "content", "") or (
                        cur.get("content", "") if isinstance(cur, dict) else ""
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id or "",
                            "content": tool_content or "",
                        }
                    )
                    i += 1

                if tool_results:
                    result.append({"role": "user", "content": tool_results})
                continue

            if role == "assistant":
                content_blocks = self._convert_assistant_content(msg)
                result.append({"role": "assistant", "content": content_blocks})
                i += 1
                continue

            if role == "user":
                user_content = getattr(msg, "content", None) or (
                    msg.get("content") if isinstance(msg, dict) else None
                )
                if isinstance(user_content, list):
                    blocks: list[dict[str, Any]] = []
                    for block in user_content:
                        if isinstance(block, dict):
                            btype = block.get("type")
                            if btype == "text":
                                blocks.append(
                                    {"type": "text", "text": block.get("text", "")}
                                )
                    if blocks:
                        result.append({"role": "user", "content": blocks})
                    else:
                        result.append({"role": "user", "content": user_content})
                else:
                    result.append({"role": "user", "content": user_content or ""})
                i += 1
                continue

            logger.warning("Unknown message role %r — skipping", role)
            i += 1

        return result

    def _convert_assistant_content(self, msg: Any) -> list[dict[str, Any]]:
        """Convert an assistant Message to Anthropic content blocks."""
        content: Any = getattr(msg, "content", None) or (
            msg.get("content") if isinstance(msg, dict) else None
        )
        tool_calls_field: Any = getattr(msg, "tool_calls", None) or (
            msg.get("tool_calls") if isinstance(msg, dict) else None
        )

        blocks: list[dict[str, Any]] = []

        if isinstance(content, str) and content:
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    btype = item.get("type")
                    if btype == "text":
                        text = item.get("text", "")
                        if text:
                            blocks.append({"type": "text", "text": text})
                    elif btype in ("tool_use", "tool_call"):
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": item.get("id", ""),
                                "name": item.get("name", ""),
                                "input": item.get("input", {}),
                            }
                        )

        # Convert tool_calls field (SDK ToolCall objects)
        if tool_calls_field:
            for tc in tool_calls_field:
                if isinstance(tc, dict):
                    tc_id = tc.get("id", "")
                    tc_name = tc.get("name", "")
                    tc_input = tc.get("arguments") or tc.get("input", {})
                else:
                    tc_id = getattr(tc, "id", "")
                    tc_name = getattr(tc, "name", "")
                    tc_input = getattr(tc, "arguments", None) or getattr(
                        tc, "input", {}
                    )
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc_id,
                        "name": tc_name,
                        "input": tc_input or {},
                    }
                )

        # Anthropic requires at least one content block
        if not blocks:
            blocks.append({"type": "text", "text": ""})

        return blocks

    def _convert_tools(self, tools: list[Any]) -> list[dict[str, Any]]:
        """Convert SDK ToolCapability list to Anthropic tool format."""
        return [
            {
                "name": tool.name,
                "description": getattr(tool, "description", "") or "",
                "input_schema": getattr(tool, "input_schema", None)
                or {
                    "type": "object",
                    "properties": {},
                },
            }
            for tool in tools
        ]

    def _convert_to_chat_response(self, response: Any) -> ChatResponse:
        """Convert an Anthropic Messages API response to SDK ChatResponse."""
        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []

        for block in response.content or []:
            block_type: str | None = getattr(block, "type", None)

            if block_type == "text":
                text = getattr(block, "text", "")
                if text:
                    text_parts.append(text)

            elif block_type == "tool_use":
                tool_id = getattr(block, "id", "")
                tool_name = getattr(block, "name", "")
                tool_input: dict[str, Any] = getattr(block, "input", {}) or {}
                tool_calls.append(
                    ToolCall(id=tool_id, name=tool_name, arguments=tool_input)
                )

        # Usage extraction
        usage_obj = response.usage
        input_tokens: int = getattr(usage_obj, "input_tokens", 0)
        output_tokens: int = getattr(usage_obj, "output_tokens", 0)

        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        combined_text = "\n\n".join(text_parts) or None

        return ChatResponse(
            content=combined_text,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            stop_reason=getattr(response, "stop_reason", None),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Call the Anthropic Messages API and return a ChatResponse."""
        messages: list[Any] = list(request.messages)

        # Separate system messages from conversation
        def _role(m: Any) -> str:
            return getattr(m, "role", "") or (
                m.get("role", "") if isinstance(m, dict) else ""
            )

        system_msgs = [m for m in messages if _role(m) == "system"]
        conversation = [m for m in messages if _role(m) != "system"]

        # Build system parameter
        system_blocks: list[dict[str, Any]] = []
        if request.system:
            system_blocks.append(
                {
                    "type": "text",
                    "text": request.system,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        elif system_msgs:
            for smsg in system_msgs:
                text: str = (
                    getattr(smsg, "content", "")
                    or (smsg.get("content", "") if isinstance(smsg, dict) else "")
                    or ""
                )
                if text:
                    system_blocks.append(
                        {
                            "type": "text",
                            "text": text,
                            "cache_control": {"type": "ephemeral"},
                        }
                    )

        # Convert messages to Anthropic wire format
        api_messages = self._convert_messages(conversation)

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

        if system_blocks:
            api_params["system"] = system_blocks

        if request.temperature is not None:
            api_params["temperature"] = request.temperature

        if request.tools:
            api_params["tools"] = self._convert_tools(request.tools)

        # Pre-emptive rate-limit throttle
        await self._rate_limit_state.maybe_throttle()

        # API call wrapped in retry_with_backoff
        async def _call() -> Any:
            try:
                return await self.client.messages.create(**api_params)
            except Exception as exc:
                meta = _translate_anthropic_error(exc)
                raise ProviderError(
                    meta["message"],
                    retryable=meta["retryable"],
                    status_code=meta["status_code"],
                    retry_after=meta["retry_after"],
                ) from exc

        response = await retry_with_backoff(_call)

        # Update rate-limit state from response headers
        self._rate_limit_state.update_from_response(response)

        return self._convert_to_chat_response(response)
