"""At-most-once send markers for queued transactional emails (P2-01).

ARQ re-runs a job that was interrupted by a worker restart. Invite, nudge and
package-share emails had no sent-marker, so a restart mid-send delivered them
twice. The worker now claims ``sent_emails`` with the job's idempotency key
*before* calling SES and skips the send when the key is already present.

The key is ``{job_id}@{enqueue_time_ms}``: deterministic job ids
(``nudge:{candidate}``) are reused once the previous job's result expires, so
the enqueue timestamp keeps a later, legitimate re-send (HR nudges again the
next day) distinct from a re-run of the same queued job.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import SessionLocal
from app.models.sent_email import SentEmail

logger = logging.getLogger(__name__)


def email_idempotency_key(ctx: dict[str, Any] | None) -> str | None:
    """Build the send-marker key from an ARQ job context.

    Args:
        ctx: ARQ worker context (``job_id`` / ``enqueue_time`` present when the
            job runs under the worker). Inline runs pass ``{}``.

    Returns:
        ``"{job_id}@{enqueue_ms}"``, or None for inline runs (no Redis, so no
        restart re-run to guard against).
    """
    if not ctx:
        return None
    job_id = ctx.get("job_id")
    if not job_id:
        return None
    enqueued = ctx.get("enqueue_time")
    if isinstance(enqueued, datetime):
        return f"{job_id}@{int(enqueued.timestamp() * 1000)}"
    return str(job_id)


async def claim_email_send(key: str, *, kind: str) -> bool:
    """Insert the send marker; True when this caller owns the send.

    Commits in its own short session so the marker is durable before SES is
    called. A database error fails open (returns True): losing an invite is
    worse than the rare duplicate during a concurrent DB outage.

    Args:
        key: Idempotency key from :func:`email_idempotency_key`.
        kind: Email kind for ops visibility (``invite`` / ``nudge`` / ``share``).

    Returns:
        True when the marker was inserted (send now); False when it already
        existed (an earlier run of this job already sent or is sending).
    """
    stmt = (
        pg_insert(SentEmail)
        .values(idempotency_key=key, kind=kind)
        .on_conflict_do_nothing(index_elements=[SentEmail.idempotency_key])
        .returning(SentEmail.idempotency_key)
    )
    try:
        async with SessionLocal() as session:
            claimed = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
    except Exception:
        logger.exception(
            "email_send_claim_failed key=%s kind=%s", key, kind,
            extra={"event": "email_send_claim_failed"},
        )
        return True
    if claimed is None:
        logger.warning(
            "email_send_duplicate_skipped key=%s kind=%s", key, kind,
            extra={"event": "email_send_duplicate_skipped"},
        )
        return False
    return True


async def release_email_send(key: str) -> None:
    """Drop a send marker after a failed send so a later re-run may retry.

    Args:
        key: Idempotency key previously claimed.
    """
    try:
        async with SessionLocal() as session:
            await session.execute(
                delete(SentEmail).where(SentEmail.idempotency_key == key)
            )
            await session.commit()
    except Exception:
        logger.exception(
            "email_send_release_failed key=%s", key,
            extra={"event": "email_send_release_failed"},
        )
