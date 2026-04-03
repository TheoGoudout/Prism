"""
OAuth2 connect / callback routes.

Flow:
  1. Frontend calls GET /oauth/connect/{platform}?workspace_id=<id>
     → receives a redirect URL for the provider.
  2. User authorises the app on the provider's site.
  3. Provider redirects to GET /oauth/callback/{platform}?code=...&state=...
     → server exchanges code for tokens, creates Integration row,
        redirects user back to the frontend.
"""
import uuid
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import crud
from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.integrations.oauth import base as oauth_registry
from app.models.integration import IntegrationCreate, Platform

# All providers must be imported so they register themselves
import app.integrations.oauth.facebook  # noqa: F401
import app.integrations.oauth.instagram  # noqa: F401
import app.integrations.oauth.twitter  # noqa: F401
import app.integrations.oauth.linkedin  # noqa: F401
import app.integrations.oauth.tiktok  # noqa: F401
import app.integrations.oauth.google_analytics  # noqa: F401

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _redirect_uri(platform: Platform) -> str:
    return f"{settings.API_BASE_URL}{settings.API_V1_STR}/oauth/callback/{platform.value}"


def _frontend_success_url(workspace_id: str) -> str:
    return f"{settings.FRONTEND_HOST}/integrations?connected=1"


def _frontend_error_url(workspace_id: str, error: str) -> str:
    params = urlencode({"error": error})
    return f"{settings.FRONTEND_HOST}/integrations?{params}"


# ---------------------------------------------------------------------------
# Connect — return the provider's authorization URL
# ---------------------------------------------------------------------------


@router.get("/connect/{platform}")
def connect(
    platform: Platform,
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    session: SessionDep,
) -> Any:
    """Return the OAuth authorization URL for the given platform."""
    member = crud.get_member(
        session=session, workspace_id=workspace_id, user_id=current_user.id
    )
    if not member:
        raise HTTPException(status_code=404, detail="Workspace not found")

    from app.models.workspace import WorkspaceRole
    if member.role not in (WorkspaceRole.owner, WorkspaceRole.admin):
        raise HTTPException(status_code=403, detail="Only owners and admins can connect integrations")

    try:
        provider = oauth_registry.get_provider(platform)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    auth_url = provider.get_auth_url(
        redirect_uri=_redirect_uri(platform),
        workspace_id=str(workspace_id),
    )
    return {"authorization_url": auth_url}


# ---------------------------------------------------------------------------
# Callback — exchange code, create Integration, redirect to frontend
# ---------------------------------------------------------------------------


@router.get("/callback/{platform}")
def callback(
    platform: Platform,
    code: str,
    state: str,
    session: SessionDep,
    request: Request,
    error: str | None = None,
) -> RedirectResponse:
    """
    OAuth2 callback — called by the provider after user authorises.
    This endpoint is not authenticated (the user arrives via redirect).
    Workspace identity is recovered from the `state` parameter.
    """
    try:
        state_data = oauth_registry.OAuthProvider.decode_state(state)
        workspace_id = uuid.UUID(state_data["workspace_id"])
    except (ValueError, KeyError):
        # Can't recover workspace — redirect to root with error
        return RedirectResponse(
            url=f"{settings.FRONTEND_HOST}?oauth_error=invalid_state", status_code=302
        )

    if error:
        return RedirectResponse(
            url=_frontend_error_url(str(workspace_id), error), status_code=302
        )

    try:
        provider = oauth_registry.get_provider(platform)
        # Twitter embeds the PKCE verifier in the state
        code_verifier = state_data.get("pkce_verifier", "")

        if platform == Platform.twitter:
            token_resp = provider.exchange_code(  # type: ignore[call-arg]
                code=code,
                redirect_uri=_redirect_uri(platform),
                code_verifier=code_verifier,
            )
        else:
            token_resp = provider.exchange_code(
                code=code, redirect_uri=_redirect_uri(platform)
            )

        account_info = provider.get_account_info(token_resp.access_token)

        integration_in = IntegrationCreate(
            platform=platform,
            workspace_id=workspace_id,
            access_token=token_resp.access_token,
            refresh_token=token_resp.refresh_token,
            token_expires_at=token_resp.expires_at,
            external_account_id=account_info.external_id,
            external_account_name=account_info.name,
            external_account_avatar=account_info.avatar_url,
        )
        crud.create_integration(session=session, integration_in=integration_in)

    except Exception as exc:
        return RedirectResponse(
            url=_frontend_error_url(str(workspace_id), str(exc)[:200]),
            status_code=302,
        )

    return RedirectResponse(
        url=_frontend_success_url(str(workspace_id)), status_code=302
    )
