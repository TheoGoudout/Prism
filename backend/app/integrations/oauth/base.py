"""
Abstract OAuth2 base for all platform integrations.

Each platform implements a concrete subclass and overrides:
  - PLATFORM          – the Platform enum value
  - SCOPES            – list of required OAuth scopes
  - AUTH_URL          – the provider's authorization endpoint
  - TOKEN_URL         – the provider's token endpoint
  - get_account_info  – fetch the connected account's name / id / avatar
  - refresh           – exchange refresh_token for a new access_token

The connect / callback HTTP handlers live in api/routes/oauth.py and
delegate to the appropriate provider via the registry below.
"""
import hashlib
import hmac
import json
import secrets
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.models.integration import Platform


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    raw: dict  # full provider response, for debugging


@dataclass
class AccountInfo:
    external_id: str
    name: str
    avatar_url: str | None


class OAuthProvider(ABC):
    """Base class for OAuth2 platform connectors."""

    PLATFORM: Platform
    SCOPES: list[str] = []
    AUTH_URL: str = ""
    TOKEN_URL: str = ""

    # -----------------------------------------------------------------------
    # State parameter — encodes workspace_id + CSRF token
    # -----------------------------------------------------------------------

    @staticmethod
    def encode_state(workspace_id: str) -> str:
        csrf = secrets.token_urlsafe(16)
        payload = json.dumps({"workspace_id": workspace_id, "csrf": csrf})
        return urllib.parse.quote(payload)

    @staticmethod
    def decode_state(state: str) -> dict:
        try:
            return json.loads(urllib.parse.unquote(state))
        except (ValueError, KeyError) as exc:
            raise ValueError(f"Invalid OAuth state parameter: {exc}") from exc

    # -----------------------------------------------------------------------
    # Authorization URL
    # -----------------------------------------------------------------------

    def get_auth_url(
        self,
        redirect_uri: str,
        workspace_id: str,
        extra_params: dict | None = None,
    ) -> str:
        params: dict[str, str] = {
            "client_id": self._client_id(),
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.SCOPES),
            "response_type": "code",
            "state": self.encode_state(workspace_id),
        }
        if extra_params:
            params.update(extra_params)
        return self.AUTH_URL + "?" + urllib.parse.urlencode(params)

    # -----------------------------------------------------------------------
    # Token exchange
    # -----------------------------------------------------------------------

    @abstractmethod
    def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange an authorization code for tokens."""

    @abstractmethod
    def refresh(self, refresh_token: str) -> TokenResponse:
        """Exchange a refresh token for a new access token."""

    # -----------------------------------------------------------------------
    # Account info
    # -----------------------------------------------------------------------

    @abstractmethod
    def get_account_info(self, access_token: str) -> AccountInfo:
        """Return the connected account's id, name, and avatar."""

    # -----------------------------------------------------------------------
    # Subclass helpers
    # -----------------------------------------------------------------------

    @abstractmethod
    def _client_id(self) -> str: ...

    @abstractmethod
    def _client_secret(self) -> str: ...

    def _post_token(self, data: dict) -> dict:
        """POST to TOKEN_URL and return the JSON response."""
        resp = httpx.post(self.TOKEN_URL, data=data, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Registry — maps Platform enum → provider instance
# ---------------------------------------------------------------------------

_registry: dict[Platform, OAuthProvider] = {}


def register(provider: OAuthProvider) -> None:
    _registry[provider.PLATFORM] = provider


def get_provider(platform: Platform) -> OAuthProvider:
    provider = _registry.get(platform)
    if provider is None:
        raise ValueError(f"No OAuth provider registered for platform '{platform}'")
    return provider


def available_platforms() -> list[Platform]:
    return list(_registry.keys())
