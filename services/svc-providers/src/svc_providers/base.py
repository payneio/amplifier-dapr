"""BaseProvider — abstract base class for all provider implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from amplifier_service_sdk.models import ChatRequest, ChatResponse


class BaseProvider(ABC):
    """Abstract base class for LLM provider implementations.

    All concrete providers must implement:
    - ``name``: a string identifier for the provider
    - ``complete()``: the async method to call the LLM
    """

    name: str

    @abstractmethod
    async def complete(self, request: ChatRequest, **kwargs: Any) -> ChatResponse:
        """Send a chat request to the provider and return a ChatResponse.

        Args:
            request: The chat request containing messages, tools, and config.
            **kwargs: Provider-specific overrides (e.g., model, max_tokens).

        Returns:
            A ChatResponse with content, usage, stop_reason, and optional tool_calls.
        """
        ...
