"""Facebook / Meta OAuth2 provider (also used by Instagram Business)."""
from datetime import timedelta

import httpx

from app.core.config import settings
from app.integrations.oauth.base import AccountInfo, OAuthProvider, TokenResponse, register
from app.models.integration import Platform


class FacebookOAuthProvider(OAuthProvider):
    PLATFORM = Platform.facebook
    SCOPES = ["pages_read_engagement", "read_insights", "pages_show_list"]
    AUTH_URL = "https://www.facebook.com/v19.0/dialog/oauth"
    TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"

    def _client_id(self) -> str:
        return settings.FACEBOOK_APP_ID

    def _client_secret(self) -> str:
        return settings.FACEBOOK_APP_SECRET

    def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        data = self._post_token({
            "client_id": self._client_id(),
            "client_secret": self._client_secret(),
            "redirect_uri": redirect_uri,
            "code": code,
        })
        # Facebook long-lived tokens don't include expires_in by default at
        # the short-lived exchange step; treat as ~1 hour.
        expires_at = self._now_utc() + timedelta(seconds=data.get("expires_in", 3600))
        return TokenResponse(
            access_token=data["access_token"],
            refresh_token=None,
            expires_at=expires_at,
            raw=data,
        )

    def refresh(self, refresh_token: str) -> TokenResponse:
        # Facebook uses long-lived token exchange instead of refresh tokens
        data = self._post_token({
            "grant_type": "fb_exchange_token",
            "client_id": self._client_id(),
            "client_secret": self._client_secret(),
            "fb_exchange_token": refresh_token,
        })
        expires_at = self._now_utc() + timedelta(seconds=data.get("expires_in", 5184000))
        return TokenResponse(
            access_token=data["access_token"],
            refresh_token=None,
            expires_at=expires_at,
            raw=data,
        )

    def get_account_info(self, access_token: str) -> AccountInfo:
        resp = httpx.get(
            "https://graph.facebook.com/v19.0/me",
            params={"fields": "id,name,picture", "access_token": access_token},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return AccountInfo(
            external_id=data["id"],
            name=data["name"],
            avatar_url=(data.get("picture") or {}).get("data", {}).get("url"),
        )


facebook_provider = FacebookOAuthProvider()
register(facebook_provider)
