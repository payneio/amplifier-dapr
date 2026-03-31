"""AzureOpenAIProvider — Azure OpenAI provider for svc-providers.

Inherits from OpenAIProvider and overrides client initialization for
Azure-specific configuration (endpoint, api_version, deployment).
"""

from __future__ import annotations

import os
from typing import Any

from svc_providers.openai_provider import OpenAIProvider

__all__ = ["AzureOpenAIProvider"]


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI provider — same as OpenAIProvider but uses AsyncAzureOpenAI client."""

    name = "azure-openai"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the Azure OpenAI provider.

        Args:
            config: Optional configuration dict. Recognised keys:
                ``api_key``, ``azure_endpoint``, ``api_version``,
                ``model``, ``max_tokens``, ``temperature``,
                ``reasoning_effort``. Missing keys fall back to environment
                variables or built-in defaults.
        """
        super().__init__(config)
        config = config or {}
        self._azure_endpoint: str | None = config.get(
            "azure_endpoint"
        ) or os.environ.get("AZURE_OPENAI_ENDPOINT")
        self._api_version: str = config.get("api_version") or os.environ.get(
            "AZURE_OPENAI_API_VERSION", "2024-02-01"
        )

    @property
    def client(self) -> Any:
        """Lazily initialise and return the ``openai.AsyncAzureOpenAI`` client."""
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
                    "An Azure OpenAI API key is required. "
                    "Pass api_key in config or set AZURE_OPENAI_API_KEY."
                )
            if self._azure_endpoint is None:
                raise ValueError(
                    "An Azure OpenAI endpoint is required. "
                    "Pass azure_endpoint in config or set AZURE_OPENAI_ENDPOINT."
                )
            self._client = openai.AsyncAzureOpenAI(
                api_key=self._api_key,
                azure_endpoint=self._azure_endpoint,
                api_version=self._api_version,
                max_retries=0,
            )
        return self._client
