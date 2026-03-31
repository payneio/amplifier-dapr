"""GitHubCopilotProvider — Copilot-specific auth with OpenAI-compatible API.

Ported from amplifier-providers' github_copilot_provider.py with the following changes:
- amplifier_ipc imports replaced with amplifier_service_sdk models
- @provider decorator removed; inherits from OpenAIProvider instead
- Imports updated to use svc_providers.openai_provider
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from svc_providers.openai_provider import OpenAIProvider, ProviderError

__all__ = ["GitHubCopilotProvider"]

logger = logging.getLogger(__name__)

COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_API_BASE = "https://api.githubcopilot.com"


class GitHubCopilotProvider(OpenAIProvider):
    """GitHub Copilot provider with Copilot-specific auth and OpenAI-compatible API.

    Inherits all message, tool, and response conversion methods from OpenAIProvider.
    Overrides client initialisation to use a Copilot session token obtained
    from the user's GitHub token.
    """

    name = "github_copilot"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the GitHub Copilot provider.

        Args:
            config: Optional configuration dict.  Recognised keys:
                ``github_token`` — GitHub personal access token or OAuth token
                    (falls back to GITHUB_TOKEN env var)
                ``model``, ``max_tokens``, ``temperature`` — forwarded to OpenAIProvider
        """
        config = config or {}

        # Copilot-specific: read GitHub token before calling super().__init__()
        self._github_token: str | None = config.get("github_token") or os.environ.get(
            "GITHUB_TOKEN"
        )

        # Cached Copilot session token and expiry (epoch seconds)
        self._copilot_token: str | None = None
        self._copilot_token_expires_at: float = 0.0

        # Build a parent config without the Copilot-specific key, and
        # without api_key (Copilot uses its own auth mechanism)
        parent_config = {
            k: v for k, v in config.items() if k not in ("github_token", "api_key")
        }

        super().__init__(config=parent_config)

        # Reset _api_key — Copilot doesn't use the OpenAI API key directly;
        # auth is handled via the Copilot session token in the client property.
        self._api_key = None

    # ------------------------------------------------------------------
    # Copilot-specific authentication
    # ------------------------------------------------------------------

    def _fetch_copilot_token(self) -> str:
        """Exchange the GitHub token for a Copilot session token.

        Calls the GitHub Copilot internal token endpoint and returns
        the bearer token string. Caches expiry for re-use.

        Raises:
            ValueError: When no GitHub token is configured.
            ProviderError: When the token exchange fails (auth error or network error).
        """
        if not self._github_token:
            raise ValueError(
                "A GitHub token is required for Copilot authentication. "
                "Pass github_token in config or set GITHUB_TOKEN."
            )

        headers = {
            "Authorization": f"token {self._github_token}",
            "Accept": "application/json",
            "Editor-Version": "amplifier/1.0",
            "Editor-Plugin-Version": "amplifier-providers/1.0",
            "User-Agent": "amplifier-providers/1.0",
        }

        req = urllib.request.Request(COPILOT_TOKEN_URL, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise ProviderError(
                    "GitHub token authentication failed (401). "
                    "Ensure GITHUB_TOKEN is valid and has Copilot access.",
                    retryable=False,
                    status_code=401,
                ) from exc
            raise ProviderError(
                f"Failed to obtain Copilot token: HTTP {exc.code}",
                retryable=exc.code >= 500,
                status_code=exc.code,
            ) from exc
        except Exception as exc:
            raise ProviderError(
                f"Failed to obtain Copilot token: {exc}",
                retryable=True,
            ) from exc

        token: str = data.get("token", "")
        if not token:
            raise ProviderError(
                "Copilot token exchange returned no token.",
                retryable=False,
            )

        # Cache expiry timestamp if provided (expires_at is an ISO datetime or epoch)
        import time  # noqa: PLC0415

        expires_at = data.get("expires_at")
        if expires_at:
            try:
                from datetime import datetime  # noqa: PLC0415

                if isinstance(expires_at, (int, float)):
                    self._copilot_token_expires_at = float(expires_at)
                else:
                    dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                    self._copilot_token_expires_at = dt.timestamp()
            except Exception:
                # If we can't parse expiry, default to 25 minutes from now
                self._copilot_token_expires_at = time.time() + 1500
        else:
            # Default: 25 minutes from now (Copilot tokens typically expire in 30 min)
            self._copilot_token_expires_at = time.time() + 1500

        self._copilot_token = token
        return token

    def _get_valid_copilot_token(self) -> str:
        """Return a valid (non-expired) Copilot session token.

        Re-fetches if the cached token is absent or within 60 seconds of expiry.
        """
        import time  # noqa: PLC0415

        if self._copilot_token is None or time.time() >= (
            self._copilot_token_expires_at - 60
        ):
            self._copilot_token = self._fetch_copilot_token()
        return self._copilot_token

    # ------------------------------------------------------------------
    # Client property override — Copilot-authenticated AsyncOpenAI client
    # ------------------------------------------------------------------

    @property
    def client(self) -> Any:
        """Lazily initialise and return the Copilot-authenticated ``openai.AsyncOpenAI`` client.

        Unlike OpenAIProvider, the api_key here is the Copilot session token
        obtained by exchanging the GitHub token.
        """
        if self._client is None:
            try:
                import openai  # type: ignore[import-untyped]  # noqa: PLC0415
            except ImportError as exc:
                raise ImportError(
                    "The 'openai' package is required for the Copilot provider. "
                    "Install it with: pip install openai"
                ) from exc

            copilot_token = self._get_valid_copilot_token()
            self._client = openai.AsyncOpenAI(
                api_key=copilot_token,
                base_url=COPILOT_API_BASE,
                max_retries=0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Public interface — complete() with token-expiry handling
    # ------------------------------------------------------------------

    async def complete(self, request: Any, **kwargs: Any) -> Any:
        """Call the Copilot Chat Completions API and return a ChatResponse.

        Delegates to OpenAIProvider.complete() which uses self.client
        (overridden here to return a Copilot-authenticated AsyncOpenAI instance).

        Handles Copilot-specific errors:
        - AuthenticationError (token expiry): resets cached client/token and retries once.
        - Other errors: translated via _translate_openai_error and re-raised.
        """
        try:
            return await super().complete(request, **kwargs)
        except ProviderError as exc:
            # If auth failure — could be expired Copilot token — reset and retry once
            if exc.status_code == 401:
                logger.warning(
                    "Copilot authentication failed (token may have expired); "
                    "refreshing session token and retrying."
                )
                self._client = None
                self._copilot_token = None
                self._copilot_token_expires_at = 0.0
                # Second attempt — if this also fails, propagate
                return await super().complete(request, **kwargs)
            raise
