"""VllmProvider — uses OpenAI-compatible API endpoint via the openai SDK.

Ported from amplifier-providers' vllm_provider.py with the following changes:
- amplifier_ipc imports replaced with amplifier_service_sdk models
- @provider decorator removed; inherits from OpenAIProvider instead
- Imports updated to use svc_providers.openai_provider
"""

from __future__ import annotations

import os
from typing import Any

from svc_providers.openai_provider import OpenAIProvider

__all__ = ["VllmProvider"]

DEFAULT_API_BASE = "http://localhost:8000/v1"
DEFAULT_API_KEY = "EMPTY"  # vLLM doesn't require auth by default


class VllmProvider(OpenAIProvider):
    """vLLM provider using the OpenAI-compatible API endpoint.

    Inherits all message, tool, and response conversion methods from OpenAIProvider.
    Overrides client initialisation to point at a vLLM server via ``openai.AsyncOpenAI``.
    """

    name = "vllm"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the vLLM provider.

        Args:
            config: Optional configuration dict.  Recognised keys:
                ``api_base``  — vLLM server base URL (falls back to VLLM_API_BASE,
                                default ``http://localhost:8000/v1``)
                ``api_key``   — API key for auth (falls back to VLLM_API_KEY,
                                default ``"EMPTY"`` — vLLM doesn't require auth)
                ``model``     — Model name to use for completions
        """
        config = config or {}

        # vLLM-specific fields — read before calling super().__init__()
        self._api_base: str = (
            config.get("api_base")
            or os.environ.get("VLLM_API_BASE")
            or DEFAULT_API_BASE
        )

        # Resolve api_key: config → VLLM_API_KEY env var → default "EMPTY"
        resolved_api_key: str = (
            config.get("api_key") or os.environ.get("VLLM_API_KEY") or DEFAULT_API_KEY
        )

        # Build parent config with the resolved key so OpenAIProvider stores it
        parent_config = dict(config)
        parent_config["api_key"] = resolved_api_key

        super().__init__(config=parent_config)

    @property
    def client(self) -> Any:
        """Lazily initialise and return the ``openai.AsyncOpenAI`` client.

        Points the client at the vLLM server endpoint via ``base_url``.
        """
        if self._client is None:
            try:
                import openai  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "The 'openai' package is required.  "
                    "Install it with: pip install openai"
                ) from exc

            self._client = openai.AsyncOpenAI(
                api_key=self._api_key or DEFAULT_API_KEY,
                base_url=self._api_base,
                max_retries=0,
            )
        return self._client
