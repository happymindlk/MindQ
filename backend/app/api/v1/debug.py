"""Debug / verification endpoints (Sentry probe, etc.)."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.auth import get_current_ops_user
from app.config import settings

router = APIRouter()


@router.get("/sentry-trigger", include_in_schema=False)
async def sentry_trigger(
    authorization: str | None = Header(default=None),
) -> None:
    """Intentionally raise so ops can confirm Sentry alerting.

    Open only on DEBUG (local) stacks. Every DEBUG=false server (QA, staging,
    production) requires an ops (admin/owner) JWT, so a deploy with a missing
    or misspelled ENVIRONMENT cannot expose an unauthenticated error-spam
    endpoint.

    Args:
        authorization: Optional ``Bearer`` header; required when DEBUG=false.

    Raises:
        HTTPException: 403 when DEBUG=false and the caller is not ops.
        RuntimeError: Always — the test exception captured by Sentry.
    """
    if not settings.DEBUG or settings.is_production:
        if not authorization:
            raise HTTPException(status_code=403, detail="Operations role required")
        await get_current_ops_user(authorization=authorization)
    raise RuntimeError("Sentry configuration test error")
