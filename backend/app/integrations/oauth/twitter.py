"""Twitter/X OAuth2 (v2 API with PKCE)."""
import base64
import hashlib
import secrets
from datetime import timedelta

import httpx

from app.core.config import settings
from app.integrations.oauth.base import AccountInfo, OAuthProvider, TokenResponse, register
from app.models.integration import Platform


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE."""
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class TwitterOAuthProvider(OAuthProvider):
    PLATFORM = Platform.twitter
    SCOPES = ["tweet.read", "users.read", "offline.access"]
    AUTH_URL = "https://twitter.com/i/oauth2/authorize"
    TOKEN_URL = "https://api.twitter.com/2/oauth2/token"

    def _client_id(self) -> str:
        return settings.TWITTER_CLIENT_ID

    def _client_secret(self) -> str:
        return settings.TWITTER_CLIENT_SECRET

    def get_auth_url(self, redirect_uri: str, workspace_id: str, extra_params: dict | None = None) -> str:
        verifier, challenge = _pkce_pair()
        params = extra_params or {}
        params.update({
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        # NOTE: The verifier must be stored in the session / state for the callback.
        # For now we embed it in the state alongside workspace_id.
        import json, urllib.parse
        state_data = json.dumps({"workspace_id": workspace_id, "pkce_verifier": verifier})
        params["state"] = urllib.parse.quote(state_data)
        params["client_id"] = self._client_id()
        params["redirect_uri"] = redirect_uri
        params["scope"] = " ".join(self.SCOPES)
        params["response_type"] = "code"
        return self.AUTH_URL + "?" + urllib.parse.urlencode(params)

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str = "") -> TokenResponse:  # type: ignore[override]
        resp = httpx.post(
            self.TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            auth=(self._client_id(), self._client_secret()),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        expires_at = self._now_utc() + timedelta(seconds=data.get("expires_in", 7200))
        return TokenResponse(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            raw=data,
        )

    def refresh(self, refresh_token: str) -> TokenResponse:
        resp = httpx.post(
            self.TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(self._client_id(), self._client_secret()),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        expires_at = self._now_utc() + timedelta(seconds=data.get("expires_in", 7200))
        return TokenResponse(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            raw=data,
        )

    def get_account_info(self, access_token: str) -> AccountInfo:
        resp = httpx.get(
            "https://api.twitter.com/2/users/me",
            params={"user.fields": "profile_image_url"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return AccountInfo(
            external_id=data["id"],
            name=data["name"],
            avatar_url=data.get("profile_image_url"),
        )


twitter_provider = TwitterOAuthProvider()
register(twitter_provider)
