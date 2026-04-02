"""
Sync tasks — fetch fresh metrics from every connected platform.

Platform-specific sync functions are registered via `register_platform_sync`.
Steps 6-11 each call register_platform_sync() once, so this task dispatcher
never needs to know about individual platforms.
"""
import logging
import uuid
from collections.abc import Callable

from sqlmodel import Session, select

from app.core.db import engine
from app.models.integration import Integration, IntegrationStatus
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform sync registry
# ---------------------------------------------------------------------------

# Maps Platform → sync function signature: (session, integration) -> None
_platform_sync: dict[str, Callable] = {}


def register_platform_sync(platform_value: str, fn: Callable) -> None:
    """Register a sync function for a platform. Called by Steps 6-11."""
    _platform_sync[platform_value] = fn


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="app.worker.tasks.sync.sync_integration",
)
def sync_integration(self, integration_id: str) -> dict:  # type: ignore[no-untyped-def]
    """
    Sync a single integration.
    Retries up to 3 times on transient errors (network timeouts, rate limits).
    """
    from app import crud

    iid = uuid.UUID(integration_id)

    with Session(engine) as session:
        integration = crud.get_integration(session=session, integration_id=iid)
        if not integration:
            logger.warning("sync_integration: integration %s not found", integration_id)
            return {"status": "not_found", "integration_id": integration_id}

        if integration.status == IntegrationStatus.disconnected:
            return {"status": "skipped", "reason": "disconnected"}

        sync_fn = _platform_sync.get(integration.platform.value)
        if sync_fn is None:
            logger.info(
                "sync_integration: no sync registered for platform %s",
                integration.platform,
            )
            return {"status": "skipped", "reason": f"no sync for {integration.platform}"}

        try:
            sync_fn(session=session, integration=integration)
            crud.mark_integration_synced(session=session, integration=integration)
            logger.info("sync_integration: OK for %s", integration_id)
            return {"status": "ok", "integration_id": integration_id}

        except Exception as exc:
            logger.error(
                "sync_integration: error for %s: %s", integration_id, exc, exc_info=True
            )
            crud.mark_integration_error(
                session=session, integration=integration, error=str(exc)
            )
            raise self.retry(exc=exc)


@celery_app.task(name="app.worker.tasks.sync.sync_all_active_integrations")
def sync_all_active_integrations() -> dict:
    """
    Enqueue a sync_integration task for every active integration.
    Scheduled nightly by Celery Beat.
    """
    with Session(engine) as session:
        integrations = session.exec(
            select(Integration).where(
                Integration.status == IntegrationStatus.active
            )
        ).all()

    count = len(integrations)
    for integ in integrations:
        sync_integration.delay(str(integ.id))

    logger.info("sync_all_active_integrations: enqueued %d tasks", count)
    return {"enqueued": count}


@celery_app.task(name="app.worker.tasks.sync.sync_workspace_integrations")
def sync_workspace_integrations(workspace_id: str) -> dict:
    """Enqueue sync tasks for all active integrations in a specific workspace."""
    from app.models.workspace import Workspace

    wid = uuid.UUID(workspace_id)
    with Session(engine) as session:
        integrations = session.exec(
            select(Integration).where(
                Integration.workspace_id == wid,
                Integration.status == IntegrationStatus.active,
            )
        ).all()

    count = len(integrations)
    for integ in integrations:
        sync_integration.delay(str(integ.id))

    return {"workspace_id": workspace_id, "enqueued": count}
