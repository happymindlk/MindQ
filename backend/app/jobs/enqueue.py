"""API-facing helpers that enqueue ARQ jobs (with inline fallback)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from app.jobs.settings import get_arq_pool
from app.jobs.tasks import (
    task_dispatch_candidate_invite,
    task_finalize_and_score_ai,
    task_refresh_report_synthesis,
    task_send_nudge_email,
    task_send_package_share,
    task_store_cached_report,
)

logger = logging.getLogger(__name__)


def _job_id_finalize(candidate_id: UUID, assessment_id: UUID) -> str:
    """Dedup key for one module's post-submit scoring pipeline."""
    return f"finalize:{candidate_id}:{assessment_id}"


def _job_id_refresh(candidate_id: UUID) -> str:
    """Dedup key for one candidate's report synthesis refresh."""
    return f"refresh:{candidate_id}"


def _job_id_invite(candidate_email: str, access_code: str) -> str:
    """Dedup key for one invite dispatch (email + PIN)."""
    return f"invite:{candidate_email.strip().lower()}:{access_code}"


def _job_id_package_share(package_id: UUID | str, recipient: str) -> str:
    """Dedup key for one package-share email."""
    return f"package_share:{package_id}:{recipient.strip().lower()}"


def _job_id_nudge(candidate_id: UUID) -> str:
    """Dedup key for one candidate nudge email."""
    return f"nudge:{candidate_id}"


def _job_id_store_report(corporate_id: UUID, candidate_id: UUID, cache_key: str) -> str:
    """Dedup key for one content-addressed PDF cache upload."""
    return f"store_report:{corporate_id}:{candidate_id}:{cache_key[:24]}"


async def _enqueue_or_run(
    *,
    task_name: str,
    coroutine_factory,
    job_id: str | None = None,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Enqueue on Redis when a pool exists; otherwise await the work inline.

    Args:
        task_name: Registered ARQ function name.
        coroutine_factory: Zero-arg async callable that runs the work inline.
        job_id: Optional deterministic ARQ ``_job_id`` for deduplication.
        args: Positional args for ``enqueue_job`` (after the function name).
        kwargs: Keyword args for ``enqueue_job``.

    Returns:
        The ARQ ``Job`` when enqueued, ``None`` on dedup conflict, or the inline
        result when Redis is unavailable.
    """
    kwargs = dict(kwargs or {})
    pool = get_arq_pool()
    if pool is None:
        logger.debug(
            "arq_inline_fallback task=%s job_id=%s",
            task_name,
            job_id,
        )
        return await coroutine_factory()

    enqueue_kwargs: dict[str, Any] = dict(kwargs)
    if job_id:
        enqueue_kwargs["_job_id"] = job_id
    try:
        job = await pool.enqueue_job(task_name, *args, **enqueue_kwargs)
    except Exception:
        logger.exception(
            "arq_enqueue_failed task=%s job_id=%s",
            task_name,
            job_id,
        )
        # Prefer durability of side-effects over dropping work when Redis blips.
        return await coroutine_factory()

    if job is None:
        logger.info(
            "arq_enqueue_deduped task=%s job_id=%s",
            task_name,
            job_id,
        )
    else:
        logger.info(
            "arq_enqueued task=%s job_id=%s",
            task_name,
            job_id or getattr(job, "job_id", None),
        )
    return job


async def enqueue_finalize_and_score_ai(
    candidate_id: UUID,
    assessment_id: UUID,
) -> Any:
    """Queue post-submit scoring + AI + PDF prewarm for one assessment.

    Args:
        candidate_id: Candidate who submitted.
        assessment_id: Assessment that was submitted.

    Returns:
        ARQ job, ``None`` when deduped, or inline result.
    """

    async def _run() -> None:
        await task_finalize_and_score_ai({}, candidate_id, assessment_id)

    return await _enqueue_or_run(
        task_name=task_finalize_and_score_ai.__name__,
        coroutine_factory=_run,
        job_id=_job_id_finalize(candidate_id, assessment_id),
        args=(str(candidate_id), str(assessment_id)),
    )


async def enqueue_refresh_report_synthesis(candidate_id: UUID) -> Any:
    """Queue technical backfill + JD synthesis refresh for a candidate.

    Args:
        candidate_id: Candidate whose report needs regeneration.

    Returns:
        ARQ job, ``None`` when deduped, or inline result.
    """

    async def _run() -> None:
        await task_refresh_report_synthesis({}, candidate_id)

    return await _enqueue_or_run(
        task_name=task_refresh_report_synthesis.__name__,
        coroutine_factory=_run,
        job_id=_job_id_refresh(candidate_id),
        args=(str(candidate_id),),
    )


async def enqueue_candidate_invite(
    *,
    candidate_email: str,
    candidate_name: str,
    access_code: str,
    package_title: str,
    corporate_name: str | None,
    origin: str,
    close_time: datetime | None = None,
    candidate_first_name: str | None = None,
) -> Any:
    """Queue SES delivery for one candidate invite.

    Args:
        candidate_email: Recipient address.
        candidate_name: Display name.
        access_code: Candidate PIN.
        package_title: Assessment package title.
        corporate_name: Hiring company name, if known.
        origin: Absolute frontend origin.
        close_time: Package window end (UTC), if enforced.
        candidate_first_name: Greeting name override.

    Returns:
        ARQ job, ``None`` when deduped, or inline result.
    """
    payload = dict(
        candidate_email=candidate_email,
        candidate_name=candidate_name,
        access_code=access_code,
        package_title=package_title,
        corporate_name=corporate_name,
        origin=origin,
        close_time=close_time.isoformat() if close_time is not None else None,
        candidate_first_name=candidate_first_name,
    )

    async def _run() -> None:
        await task_dispatch_candidate_invite({}, **{
            **payload,
            "close_time": close_time,
        })

    return await _enqueue_or_run(
        task_name=task_dispatch_candidate_invite.__name__,
        coroutine_factory=_run,
        job_id=_job_id_invite(candidate_email, access_code),
        kwargs=payload,
    )


async def enqueue_package_share(
    *,
    package_id: UUID | str,
    recipient: str,
    subject: str,
    html_content: str,
) -> Any:
    """Queue SES delivery for a package-share email.

    Args:
        package_id: Package UUID (dedup key only).
        recipient: Recipient address.
        subject: Email subject.
        html_content: Rendered HTML body.

    Returns:
        ARQ job, ``None`` when deduped, or inline result.
    """

    async def _run() -> None:
        await task_send_package_share({}, recipient, subject, html_content)

    return await _enqueue_or_run(
        task_name=task_send_package_share.__name__,
        coroutine_factory=_run,
        job_id=_job_id_package_share(package_id, recipient),
        args=(recipient, subject, html_content),
    )


async def enqueue_nudge_email(
    email: str,
    name: str,
    access_code: str,
    package_title: str,
    *,
    candidate_id: UUID,
) -> Any:
    """Queue a candidate reminder email.

    Args:
        email: Candidate email.
        name: Candidate display name.
        access_code: Access code shown in the email.
        package_title: Assessment package title.
        candidate_id: Candidate id used for deduplication.

    Returns:
        ARQ job, ``None`` when deduped, or inline result.
    """

    async def _run() -> None:
        await task_send_nudge_email({}, email, name, access_code, package_title)

    return await _enqueue_or_run(
        task_name=task_send_nudge_email.__name__,
        coroutine_factory=_run,
        job_id=_job_id_nudge(candidate_id),
        args=(email, name, access_code, package_title),
    )


async def enqueue_store_cached_report(
    corporate_id: UUID,
    candidate_id: UUID,
    cache_key: str,
    content: bytes,
) -> Any:
    """Queue a rendered PDF upload to the private reports bucket.

    Args:
        corporate_id: Tenant id used as the object prefix.
        candidate_id: Candidate id used as the second path segment.
        cache_key: Content-addressed report cache key.
        content: PDF bytes.

    Returns:
        ARQ job, ``None`` when deduped, or inline result.
    """

    async def _run() -> None:
        await task_store_cached_report(
            {}, corporate_id, candidate_id, cache_key, content
        )

    return await _enqueue_or_run(
        task_name=task_store_cached_report.__name__,
        coroutine_factory=_run,
        job_id=_job_id_store_report(corporate_id, candidate_id, cache_key),
        args=(str(corporate_id), str(candidate_id), cache_key, content),
    )
