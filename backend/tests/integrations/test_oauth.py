"""
OAuth2 provider unit tests and connect/callback route tests.
All external HTTP calls are mocked — no real provider is contacted.
"""
import json
import urllib.parse
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.integrations.oauth.base import OAuthProvider, get_provider
from app.integrations.oauth.facebook import facebook_provider
from app.integrations.oauth.instagram import instagram_provider
from app.integrations.oauth.twitter import twitter_provider
from app.integrations.oauth.google_analytics import google_analytics_provider
from app.models.integration import Platform

PREFIX = f"{settings.API_V1_STR}/oauth"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_user_with_headers(client: TestClient, db: Session) -> tuple:
    from tests.utils.utils import random_lower_string, random_email
    from app.crud.user import create_user
    from app.models.user import UserCreate

    email = random_email()
    password = random_lower_string()
    user = create_user(session=db, user_create=UserCreate(email=email, password=password))
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return user, headers


def _make_state(workspace_id: str) -> str:
    return urllib.parse.quote(json.dumps({"workspace_id": workspace_id, "csrf": "test"}))


# ---------------------------------------------------------------------------
# OAuthProvider base: state encode/decode
# ---------------------------------------------------------------------------


def test_state_encode_decode_roundtrip() -> None:
    state = OAuthProvider.encode_state("ws-abc-123")
    decoded = OAuthProvider.decode_state(state)
    assert decoded["workspace_id"] == "ws-abc-123"
    assert "csrf" in decoded


def test_state_decode_invalid_raises() -> None:
    with pytest.raises(ValueError):
        OAuthProvider.decode_state("not-valid-json!!!")


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------


def test_all_platforms_registered() -> None:
    for platform in Platform:
        provider = get_provider(platform)
        assert provider.PLATFORM == platform


def test_get_provider_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_provider("nonexistent")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Facebook provider — mocked HTTP
# ---------------------------------------------------------------------------


def test_facebook_exchange_code() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "fb-tok", "expires_in": 3600}
    mock_response.raise_for_status = MagicMock()

    with patch("app.integrations.oauth.facebook.httpx.post", return_value=mock_response):
        result = facebook_provider.exchange_code(code="code123", redirect_uri="http://localhost/cb")

    assert result.access_token == "fb-tok"
    assert result.refresh_token is None
    assert result.expires_at is not None


def test_facebook_refresh() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "fb-long", "expires_in": 5184000}
    mock_response.raise_for_status = MagicMock()

    with patch("app.integrations.oauth.facebook.httpx.post", return_value=mock_response):
        result = facebook_provider.refresh("old-token")

    assert result.access_token == "fb-long"


def test_facebook_get_account_info() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": "123456",
        "name": "My Page",
        "picture": {"data": {"url": "https://example.com/pic.jpg"}},
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.integrations.oauth.facebook.httpx.get", return_value=mock_response):
        info = facebook_provider.get_account_info("fb-token")

    assert info.external_id == "123456"
    assert info.name == "My Page"
    assert info.avatar_url == "https://example.com/pic.jpg"


# ---------------------------------------------------------------------------
# Instagram provider — mocked HTTP
# ---------------------------------------------------------------------------


def test_instagram_get_account_info_with_ig_account() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{
            "id": "page-1",
            "instagram_business_account": {
                "id": "ig-789",
                "name": "My IG",
                "profile_picture_url": "https://example.com/ig.jpg",
            }
        }]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.integrations.oauth.instagram.httpx.get", return_value=mock_response):
        info = instagram_provider.get_account_info("ig-token")

    assert info.external_id == "ig-789"
    assert info.name == "My IG"


def test_instagram_get_account_info_fallback() -> None:
    """If no IG business account is found, fall back to Facebook user info."""
    pages_response = MagicMock()
    pages_response.json.return_value = {"data": []}
    pages_response.raise_for_status = MagicMock()

    me_response = MagicMock()
    me_response.json.return_value = {"id": "fb-user-1", "name": "Fallback User"}
    me_response.raise_for_status = MagicMock()

    with patch(
        "app.integrations.oauth.instagram.httpx.get",
        side_effect=[pages_response, me_response],
    ):
        info = instagram_provider.get_account_info("token")

    assert info.external_id == "fb-user-1"
    assert info.name == "Fallback User"


# ---------------------------------------------------------------------------
# Twitter provider — mocked HTTP, PKCE
# ---------------------------------------------------------------------------


def test_twitter_auth_url_contains_pkce() -> None:
    url = twitter_provider.get_auth_url(
        redirect_uri="http://localhost/cb", workspace_id="ws-1"
    )
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url


def test_twitter_exchange_code() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "access_token": "tw-tok",
        "refresh_token": "tw-refresh",
        "expires_in": 7200,
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.integrations.oauth.twitter.httpx.post", return_value=mock_response):
        result = twitter_provider.exchange_code(
            code="tw-code", redirect_uri="http://localhost/cb", code_verifier="verifier"
        )

    assert result.access_token == "tw-tok"
    assert result.refresh_token == "tw-refresh"


def test_twitter_get_account_info() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {"id": "tw-uid", "name": "Twitter User", "profile_image_url": "https://pbs.twimg.com/img.jpg"}
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.integrations.oauth.twitter.httpx.get", return_value=mock_response):
        info = twitter_provider.get_account_info("tw-tok")

    assert info.external_id == "tw-uid"


# ---------------------------------------------------------------------------
# Google Analytics provider — mocked HTTP
# ---------------------------------------------------------------------------


def test_google_analytics_auth_url_has_offline_access() -> None:
    url = google_analytics_provider.get_auth_url(
        redirect_uri="http://localhost/cb", workspace_id="ws-ga"
    )
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_google_analytics_refresh_keeps_same_refresh_token() -> None:
    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "new-ga-tok", "expires_in": 3600}
    mock_response.raise_for_status = MagicMock()

    with patch("app.integrations.oauth.google_analytics.httpx.post", return_value=mock_response):
        result = google_analytics_provider.refresh("original-refresh")

    assert result.refresh_token == "original-refresh"


# ---------------------------------------------------------------------------
# Connect route
# ---------------------------------------------------------------------------


def test_connect_returns_authorization_url(client: TestClient, db: Session) -> None:
    user, headers = _create_user_with_headers(client, db)
    from tests.utils.workspace import create_random_workspace
    ws = create_random_workspace(db, user)

    r = client.get(
        f"{PREFIX}/connect/facebook",
        headers=headers,
        params={"workspace_id": str(ws.id)},
    )
    assert r.status_code == 200
    assert "authorization_url" in r.json()
    assert "facebook.com" in r.json()["authorization_url"]


def test_connect_viewer_forbidden(client: TestClient, db: Session) -> None:
    from tests.utils.workspace import create_random_workspace

    owner, owner_headers = _create_user_with_headers(client, db)
    viewer, viewer_headers = _create_user_with_headers(client, db)
    ws = create_random_workspace(db, owner)
    client.post(
        f"{settings.API_V1_STR}/workspaces/{ws.id}/members",
        headers=owner_headers,
        json={"user_id": str(viewer.id), "role": "viewer"},
    )

    r = client.get(
        f"{PREFIX}/connect/facebook",
        headers=viewer_headers,
        params={"workspace_id": str(ws.id)},
    )
    assert r.status_code == 403


def test_connect_non_member_returns_404(client: TestClient, db: Session) -> None:
    from tests.utils.workspace import create_random_workspace

    owner, _ = _create_user_with_headers(client, db)
    outsider, outsider_headers = _create_user_with_headers(client, db)
    ws = create_random_workspace(db, owner)

    r = client.get(
        f"{PREFIX}/connect/facebook",
        headers=outsider_headers,
        params={"workspace_id": str(ws.id)},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Callback route
# ---------------------------------------------------------------------------


def _mock_token_response():  # type: ignore[no-untyped-def]
    from app.integrations.oauth.base import TokenResponse
    return TokenResponse(
        access_token="cb-access-tok",
        refresh_token="cb-refresh-tok",
        expires_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        raw={},
    )


def _mock_account_info():  # type: ignore[no-untyped-def]
    from app.integrations.oauth.base import AccountInfo
    return AccountInfo(external_id="ext-cb-123", name="Callback Page", avatar_url=None)


def test_callback_creates_integration(client: TestClient, db: Session) -> None:
    from tests.utils.workspace import create_random_workspace

    user, _ = _create_user_with_headers(client, db)
    ws = create_random_workspace(db, user)
    state = _make_state(str(ws.id))

    mock_provider = MagicMock()
    mock_provider.exchange_code.return_value = _mock_token_response()
    mock_provider.get_account_info.return_value = _mock_account_info()

    with patch("app.integrations.oauth.base.get_provider", return_value=mock_provider):
        r = client.get(
            f"{PREFIX}/callback/facebook",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )

    assert r.status_code == 302
    assert "connected=1" in r.headers["location"]

    # Verify integration was persisted
    from app import crud
    integrations = crud.get_integrations_for_workspace(session=db, workspace_id=ws.id)
    assert len(integrations) == 1
    assert integrations[0].external_account_name == "Callback Page"


def test_callback_provider_error_redirects_with_error(client: TestClient, db: Session) -> None:
    from tests.utils.workspace import create_random_workspace

    user, _ = _create_user_with_headers(client, db)
    ws = create_random_workspace(db, user)
    state = _make_state(str(ws.id))

    mock_provider = MagicMock()
    mock_provider.exchange_code.side_effect = Exception("rate limited")

    with patch("app.integrations.oauth.base.get_provider", return_value=mock_provider):
        r = client.get(
            f"{PREFIX}/callback/facebook",
            params={"code": "bad-code", "state": state},
            follow_redirects=False,
        )

    assert r.status_code == 302
    assert "error=" in r.headers["location"]


def test_callback_invalid_state_redirects_to_root(client: TestClient) -> None:
    r = client.get(
        f"{PREFIX}/callback/facebook",
        params={"code": "x", "state": "invalid-state!!!"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "oauth_error=invalid_state" in r.headers["location"]


def test_callback_provider_error_param_redirects(client: TestClient, db: Session) -> None:
    from tests.utils.workspace import create_random_workspace

    user, _ = _create_user_with_headers(client, db)
    ws = create_random_workspace(db, user)
    state = _make_state(str(ws.id))

    r = client.get(
        f"{PREFIX}/callback/facebook",
        params={"code": "", "state": state, "error": "access_denied"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "error=access_denied" in r.headers["location"]
