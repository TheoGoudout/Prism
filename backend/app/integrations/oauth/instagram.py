"""Instagram Business OAuth2 provider (shares the Facebook/Meta Graph API app)."""
from datetime import timedelta

import httpx

from app.core.config import settings
from app.integrations.oauth.base import AccountInfo, OAuthProvider, TokenResponse, register
from app.models.integration import Platform


class InstagramOAuthProvider(OAuthProvider):
    """
    Instagram Business accounts are accessed through the Facebook Graph API.
    The OAuth app is the same; we just request different scopes.
    """

    PLATFORM = Platform.instagram
    SCOPES = [
        "instagram_basic",
        "instagram_manage_insights",
        "pages_show_list",
        "pages_read_engagement",
    ]
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
        expires_at = self._now_utc() + timedelta(seconds=data.get("expires_in", 3600))
        return TokenResponse(
            access_token=data["access_token"],
            refresh_token=None,
            expires_at=expires_at,
            raw=data,
        )

    def refresh(self, refresh_token: str) -> TokenResponse:
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
        # Get the Facebook user to find connected Instagram Business accounts
        resp = httpx.get(
            "https://graph.facebook.com/v19.0/me/accounts",
            params={"fields": "instagram_business_account{id,name,profile_picture_url}", "access_token": access_token},
            timeout=10,
        )
        resp.raise_for_status()
        pages = resp.json().get("data", [])
        for page in pages:
            ig = page.get("instagram_business_account")
            if ig:
                return AccountInfo(
                    external_id=ig["id"],
                    name=ig.get("name", "Instagram Account"),
                    avatar_url=ig.get("profile_picture_url"),
                )
        # Fallback to the Facebook user name
        me = httpx.get(
            "https://graph.facebook.com/v19.0/me",
            params={"fields": "id,name", "access_token": access_token},
            timeout=10,
        ).json()
        return AccountInfo(external_id=me["id"], name=me["name"], avatar_url=None)


instagram_provider = InstagramOAuthProvider()
register(instagram_provider)
