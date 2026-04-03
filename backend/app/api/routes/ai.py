"""
AI endpoints — on-demand content insights and performance reports.

Both endpoints:
- Require workspace membership
- Fetch the same metrics data as /metrics/summary + /metrics/posts
- Pass the data through a LangChain chain and return the result

LangSmith tracing is automatically enabled when LANGCHAIN_TRACING_V2=true
and LANGCHAIN_API_KEY are set in the environment.
"""
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from app import crud
from app.ai.chains.insights import build_insights_chain, build_insights_input
from app.ai.chains.report import build_report_chain, build_report_input
from app.api.deps import CurrentUser, SessionDep
from app.models.ai import AIRequest, Insight, InsightsResponse, ReportResponse
from app.models.integration import Platform
from app.models.metrics import PostPublic

router = APIRouter(prefix="/ai", tags=["ai"])

_DEFAULT_DAYS = 30


def _default_range() -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=_DEFAULT_DAYS - 1), end


def _require_member(session: Any, workspace_id: uuid.UUID, current_user: Any) -> Any:
    member = crud.get_member(
        session=session, workspace_id=workspace_id, user_id=current_user.id
    )
    if not member:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return member


def _get_workspace(session: Any, workspace_id: uuid.UUID) -> Any:
    ws = crud.get_workspace(session=session, workspace_id=workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _collect_metrics(
    session: Any,
    workspace_id: uuid.UUID,
    platform: Platform | None,
    date_from: date,
    date_to: date,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return (totals, by_platform, top_posts) as plain dicts."""
    from collections import defaultdict

    accounts = crud.get_accounts_for_workspace(
        session=session, workspace_id=workspace_id, platform=platform
    )
    account_platform = {a.id: a.platform.value for a in accounts}

    if not account_platform:
        return {}, {}, []

    snapshots = crud.get_snapshots_for_accounts(
        session=session,
        platform_account_ids=list(account_platform.keys()),
        start_date=date_from,
        end_date=date_to,
    )

    _SUM_FIELDS = (
        "impressions", "reach", "views", "clicks", "engagements",
        "likes", "comments", "shares", "saves", "followers_gained",
    )
    totals: dict[str, int] = defaultdict(int)
    by_platform: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    latest_followers: dict[uuid.UUID, int] = {}

    for snap in snapshots:
        plat = account_platform.get(snap.platform_account_id, "unknown")
        for field in _SUM_FIELDS:
            val = getattr(snap, field) or 0
            totals[field] += val
            by_platform[plat][field] += val
        if snap.followers_count is not None:
            latest_followers[snap.platform_account_id] = snap.followers_count

    totals_dict: dict[str, Any] = dict(totals)
    totals_dict["followers_count"] = (
        sum(latest_followers.values()) if latest_followers else None
    )

    posts = crud.get_top_posts(
        session=session,
        platform_account_ids=list(account_platform.keys()),
        start_date=date_from,
        end_date=date_to,
        limit=10,
    )
    posts_list = [PostPublic.model_validate(p).model_dump() for p in posts]

    return totals_dict, {k: dict(v) for k, v in by_platform.items()}, posts_list


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/insights", response_model=InsightsResponse)
def generate_insights(
    body: AIRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    Generate AI-powered insights from workspace metrics.

    Calls the configured LLM (AI_PROVIDER / AI_MODEL) with the aggregated
    metrics data and returns 4–6 structured, actionable insights.
    """
    ws_id = uuid.UUID(body.workspace_id)
    _require_member(session, ws_id, current_user)
    ws = _get_workspace(session, ws_id)

    date_from, date_to = _default_range()
    if body.date_from:
        date_from = body.date_from
    if body.date_to:
        date_to = body.date_to

    totals, by_platform, _ = _collect_metrics(
        session, ws_id, body.platform, date_from, date_to
    )

    chain_input = build_insights_input(
        workspace_name=ws.name,
        date_from=str(date_from),
        date_to=str(date_to),
        platform=body.platform.value if body.platform else None,
        totals=totals,
        by_platform=by_platform,
    )

    try:
        raw: list[dict[str, Any]] = build_insights_chain().invoke(chain_input)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"AI generation failed: {exc}"
        ) from exc

    insights = [
        Insight(
            title=item.get("title", ""),
            body=item.get("body", ""),
            type=item.get("type", "neutral"),
            metric=item.get("metric"),
        )
        for item in raw
        if isinstance(item, dict)
    ]
    return InsightsResponse(insights=insights)


@router.post("/report", response_model=ReportResponse)
def generate_report(
    body: AIRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    Generate a full markdown performance report for a workspace.

    Includes executive summary, per-platform analysis, top content, and
    recommendations based on the requested date range.
    """
    ws_id = uuid.UUID(body.workspace_id)
    _require_member(session, ws_id, current_user)
    ws = _get_workspace(session, ws_id)

    date_from, date_to = _default_range()
    if body.date_from:
        date_from = body.date_from
    if body.date_to:
        date_to = body.date_to

    totals, by_platform, posts = _collect_metrics(
        session, ws_id, body.platform, date_from, date_to
    )

    chain_input = build_report_input(
        workspace_name=ws.name,
        date_from=str(date_from),
        date_to=str(date_to),
        platform=body.platform.value if body.platform else None,
        totals=totals,
        by_platform=by_platform,
        posts=posts,
    )

    try:
        report: str = build_report_chain().invoke(chain_input)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"AI generation failed: {exc}"
        ) from exc

    return ReportResponse(report=report)
