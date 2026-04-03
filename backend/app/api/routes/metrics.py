"""
Metrics API — dashboard data endpoints.

All endpoints require workspace membership. The caller identifies the workspace
via the `workspace_id` query parameter, and optionally narrows results to a
single platform via `platform`.
"""
import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import crud
from app.api.deps import CurrentUser, SessionDep
from app.models.integration import Platform
from app.models.metrics import (
    MetricsSummary,
    MetricTotals,
    MetricsTimeSeries,
    PostPublic,
    PostsPublic,
    TimeSeriesPoint,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])

_DEFAULT_DAYS = 30


def _default_date_range() -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=_DEFAULT_DAYS - 1)
    return start, end


def _require_member(session: Any, workspace_id: uuid.UUID, current_user: Any) -> None:
    member = crud.get_member(
        session=session, workspace_id=workspace_id, user_id=current_user.id
    )
    if not member:
        raise HTTPException(status_code=404, detail="Workspace not found")


def _account_ids_for_workspace(
    session: Any,
    workspace_id: uuid.UUID,
    platform: Platform | None,
) -> list[uuid.UUID]:
    """Return platform account IDs scoped to a workspace (and optional platform)."""
    accounts = crud.get_accounts_for_workspace(
        session=session, workspace_id=workspace_id, platform=platform
    )
    return [a.id for a in accounts]


def _account_platform_map(
    session: Any,
    workspace_id: uuid.UUID,
    platform: Platform | None,
) -> dict[uuid.UUID, str]:
    """Return {account_id: platform_value} for per-platform breakdown."""
    accounts = crud.get_accounts_for_workspace(
        session=session, workspace_id=workspace_id, platform=platform
    )
    return {a.id: a.platform.value for a in accounts}


# ---------------------------------------------------------------------------
# Summary — KPI cards
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=MetricsSummary)
def get_summary(
    session: SessionDep,
    current_user: CurrentUser,
    workspace_id: uuid.UUID,
    platform: Platform | None = None,
    date_from: date = Query(default_factory=lambda: _default_date_range()[0]),
    date_to: date = Query(default_factory=lambda: _default_date_range()[1]),
) -> Any:
    """
    Aggregate KPI totals for a workspace over a date range.
    Returns overall totals and a per-platform breakdown.
    """
    _require_member(session, workspace_id, current_user)

    account_platform = _account_platform_map(session, workspace_id, platform)
    if not account_platform:
        empty = MetricTotals()
        return MetricsSummary(
            totals=empty, by_platform={}, date_from=date_from, date_to=date_to
        )

    snapshots = crud.get_snapshots_for_accounts(
        session=session,
        platform_account_ids=list(account_platform.keys()),
        start_date=date_from,
        end_date=date_to,
    )

    # Accumulate totals and per-platform sub-totals
    totals: dict[str, int] = defaultdict(int)
    by_platform: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # Track latest followers_count per account (last snapshot in range)
    latest_followers: dict[uuid.UUID, int] = {}

    _SUM_FIELDS = (
        "impressions", "reach", "views", "clicks", "engagements",
        "likes", "comments", "shares", "saves", "followers_gained",
    )

    for snap in snapshots:
        plat = account_platform.get(snap.platform_account_id, "unknown")
        for field in _SUM_FIELDS:
            val = getattr(snap, field) or 0
            totals[field] += val
            by_platform[plat][field] += val
        if snap.followers_count is not None:
            latest_followers[snap.platform_account_id] = snap.followers_count

    total_followers = sum(latest_followers.values()) if latest_followers else None

    def _to_totals(d: dict[str, int], followers: int | None = None) -> MetricTotals:
        return MetricTotals(
            impressions=d.get("impressions", 0),
            reach=d.get("reach", 0),
            views=d.get("views", 0),
            clicks=d.get("clicks", 0),
            engagements=d.get("engagements", 0),
            likes=d.get("likes", 0),
            comments=d.get("comments", 0),
            shares=d.get("shares", 0),
            saves=d.get("saves", 0),
            followers_count=followers,
            followers_gained=d.get("followers_gained", 0),
        )

    # Per-platform followers: sum latest per account in that platform
    plat_followers: dict[str, int] = defaultdict(int)
    for acc_id, followers in latest_followers.items():
        plat = account_platform.get(acc_id, "unknown")
        plat_followers[plat] += followers

    return MetricsSummary(
        totals=_to_totals(totals, total_followers),
        by_platform={
            plat: _to_totals(d, plat_followers.get(plat))
            for plat, d in by_platform.items()
        },
        date_from=date_from,
        date_to=date_to,
    )


# ---------------------------------------------------------------------------
# Timeseries — chart data
# ---------------------------------------------------------------------------


@router.get("/timeseries", response_model=MetricsTimeSeries)
def get_timeseries(
    session: SessionDep,
    current_user: CurrentUser,
    workspace_id: uuid.UUID,
    platform: Platform | None = None,
    date_from: date = Query(default_factory=lambda: _default_date_range()[0]),
    date_to: date = Query(default_factory=lambda: _default_date_range()[1]),
) -> Any:
    """
    Per-day aggregated metrics for line/bar charts.
    Returns one data point per calendar day in the requested range.
    """
    _require_member(session, workspace_id, current_user)

    account_ids = _account_ids_for_workspace(session, workspace_id, platform)
    if not account_ids:
        return MetricsTimeSeries(data=[])

    snapshots = crud.get_snapshots_for_accounts(
        session=session,
        platform_account_ids=account_ids,
        start_date=date_from,
        end_date=date_to,
    )

    # Aggregate by date
    by_date: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    _CHART_FIELDS = ("impressions", "reach", "views", "clicks", "engagements")
    for snap in snapshots:
        for field in _CHART_FIELDS:
            by_date[snap.date][field] += getattr(snap, field) or 0

    # Fill every day in range (even days with no data → zeros)
    data: list[TimeSeriesPoint] = []
    current = date_from
    while current <= date_to:
        d = by_date.get(current, {})
        data.append(
            TimeSeriesPoint(
                date=current,
                impressions=d.get("impressions", 0),
                reach=d.get("reach", 0),
                views=d.get("views", 0),
                clicks=d.get("clicks", 0),
                engagements=d.get("engagements", 0),
            )
        )
        current += timedelta(days=1)

    return MetricsTimeSeries(data=data)


# ---------------------------------------------------------------------------
# Top posts
# ---------------------------------------------------------------------------


@router.get("/posts", response_model=PostsPublic)
def get_top_posts(
    session: SessionDep,
    current_user: CurrentUser,
    workspace_id: uuid.UUID,
    platform: Platform | None = None,
    date_from: date = Query(default_factory=lambda: _default_date_range()[0]),
    date_to: date = Query(default_factory=lambda: _default_date_range()[1]),
    limit: int = Query(default=10, ge=1, le=50),
) -> Any:
    """
    Top-performing posts (by engagements) for a workspace over a date range.
    """
    _require_member(session, workspace_id, current_user)

    account_ids = _account_ids_for_workspace(session, workspace_id, platform)
    if not account_ids:
        return PostsPublic(data=[], count=0)

    posts = crud.get_top_posts(
        session=session,
        platform_account_ids=account_ids,
        start_date=date_from,
        end_date=date_to,
        limit=limit,
    )
    return PostsPublic(data=[PostPublic.model_validate(p) for p in posts], count=len(posts))
