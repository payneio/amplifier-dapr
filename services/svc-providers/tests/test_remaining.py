"""Tests for GeminiProvider, OllamaProvider, VllmProvider, GitHubCopilotProvider.

Covers basic instantiation and name verification for each provider.
Also verifies GET /describe includes all new providers.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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


class TestOllamaProviderName:
    """OllamaProvider.name == 'ollama' and inherits BaseProvider."""

    def test_provider_name(self) -> None:
        """OllamaProvider.name attribute is 'ollama'."""
        from svc_providers.ollama_provider import OllamaProvider  # noqa: PLC0415

        provider = OllamaProvider()
        assert provider.name == "ollama"

    def test_provider_is_base_provider(self) -> None:
        """OllamaProvider inherits from BaseProvider."""
        from svc_providers.ollama_provider import OllamaProvider  # noqa: PLC0415

        provider = OllamaProvider()
        assert isinstance(provider, BaseProvider)

    def test_provider_no_api_key_required(self) -> None:
        """OllamaProvider instantiates with no config (no api_key needed)."""
        from svc_providers.ollama_provider import OllamaProvider  # noqa: PLC0415

        provider = OllamaProvider(config={})
        assert provider.name == "ollama"


class TestVllmProviderName:
    """VllmProvider.name == 'vllm' and inherits OpenAIProvider."""

    def test_provider_name(self) -> None:
        """VllmProvider.name attribute is 'vllm'."""
        from svc_providers.vllm_provider import VllmProvider  # noqa: PLC0415

        provider = VllmProvider(config={"api_key": "EMPTY"})
        assert provider.name == "vllm"

    def test_provider_is_base_provider(self) -> None:
        """VllmProvider inherits from BaseProvider (via OpenAIProvider)."""
        from svc_providers.vllm_provider import VllmProvider  # noqa: PLC0415

        provider = VllmProvider()
        assert isinstance(provider, BaseProvider)

    def test_provider_inherits_from_openai_provider(self) -> None:
        """VllmProvider inherits from OpenAIProvider."""
        from svc_providers.openai_provider import OpenAIProvider  # noqa: PLC0415
        from svc_providers.vllm_provider import VllmProvider  # noqa: PLC0415

        provider = VllmProvider()
        assert isinstance(provider, OpenAIProvider)

    def test_provider_default_api_key_is_empty(self) -> None:
        """VllmProvider defaults api_key to 'EMPTY' when not provided."""
        from svc_providers.vllm_provider import VllmProvider  # noqa: PLC0415

        provider = VllmProvider()
        assert provider._api_key == "EMPTY"


class TestGitHubCopilotProviderName:
    """GitHubCopilotProvider.name == 'github_copilot' and inherits OpenAIProvider."""

    def test_provider_name(self) -> None:
        """GitHubCopilotProvider.name attribute is 'github_copilot'."""
        from svc_providers.github_copilot_provider import GitHubCopilotProvider  # noqa: PLC0415

        provider = GitHubCopilotProvider(config={"github_token": "test-token"})
        assert provider.name == "github_copilot"

    def test_provider_is_base_provider(self) -> None:
        """GitHubCopilotProvider inherits from BaseProvider (via OpenAIProvider)."""
        from svc_providers.github_copilot_provider import GitHubCopilotProvider  # noqa: PLC0415

        provider = GitHubCopilotProvider(config={"github_token": "test-token"})
        assert isinstance(provider, BaseProvider)

    def test_provider_inherits_from_openai_provider(self) -> None:
        """GitHubCopilotProvider inherits from OpenAIProvider."""
        from svc_providers.github_copilot_provider import GitHubCopilotProvider  # noqa: PLC0415
        from svc_providers.openai_provider import OpenAIProvider  # noqa: PLC0415

        provider = GitHubCopilotProvider(config={"github_token": "test-token"})
        assert isinstance(provider, OpenAIProvider)

    def test_provider_stores_github_token(self) -> None:
        """GitHubCopilotProvider stores the github_token from config."""
        from svc_providers.github_copilot_provider import GitHubCopilotProvider  # noqa: PLC0415

        provider = GitHubCopilotProvider(config={"github_token": "my-gh-token"})
        assert provider._github_token == "my-gh-token"


class TestAppDescribeIncludesAllProviders:
    """GET /describe includes all 7 providers after adding the 4 new ones."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create a TestClient for the providers app."""
        from svc_providers.app import create_providers_app  # noqa: PLC0415

        app = create_providers_app()
        return TestClient(app)

    def test_describe_includes_gemini(self, client: TestClient) -> None:
        """GET /describe lists gemini in providers."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        provider_names = [p["name"] for p in data["providers"]]
        assert "gemini" in provider_names

    def test_describe_includes_ollama(self, client: TestClient) -> None:
        """GET /describe lists ollama in providers."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        provider_names = [p["name"] for p in data["providers"]]
        assert "ollama" in provider_names

    def test_describe_includes_vllm(self, client: TestClient) -> None:
        """GET /describe lists vllm in providers."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        provider_names = [p["name"] for p in data["providers"]]
        assert "vllm" in provider_names

    def test_describe_includes_github_copilot(self, client: TestClient) -> None:
        """GET /describe lists github-copilot in providers."""
        response = client.get("/describe")
        assert response.status_code == 200
        data = response.json()
        provider_names = [p["name"] for p in data["providers"]]
        assert "github-copilot" in provider_names
