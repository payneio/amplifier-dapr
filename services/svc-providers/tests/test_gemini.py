"""Tests for GeminiProvider.

Covers basic instantiation and name verification.
"""

from __future__ import annotations

from svc_providers.base import BaseProvider


class TestGeminiProviderName:
    """GeminiProvider.name == 'gemini' and inherits BaseProvider."""

    def test_provider_name(self) -> None:
        """GeminiProvider.name attribute is 'gemini'."""
        from svc_providers.gemini_provider import GeminiProvider  # noqa: PLC0415

        provider = GeminiProvider(config={"api_key": "test-key"})
        assert provider.name == "gemini"

    def test_provider_is_base_provider(self) -> None:
        """GeminiProvider inherits from BaseProvider."""
        from svc_providers.gemini_provider import GeminiProvider  # noqa: PLC0415

        provider = GeminiProvider(config={"api_key": "test-key"})
        assert isinstance(provider, BaseProvider)

    def test_provider_instantiates_without_api_key(self) -> None:
        """GeminiProvider can be instantiated without api_key (lazy SDK init)."""
        from svc_providers.gemini_provider import GeminiProvider  # noqa: PLC0415

        provider = GeminiProvider()
        assert provider.name == "gemini"
