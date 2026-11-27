"""API-facing helpers that enqueue ARQ jobs (with inline fallback)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.jobs.settings import get_arq_pool
from app.jobs.tasks import (
    task_dispatch_candidate_invite,
    task_finalize_and_score_ai,
    task_finalize_expired_assessment,
    task_refresh_report_synthesis,
    task_send_nudge_email,
    task_send_package_share,
    task_purge_candidate_report_files,
    task_store_cached_report,
)

logger = logging.getLogger(__name__)

# Keep strong refs to fire-and-forget inline tasks so they are not GC'd mid-run.
_inline_tasks: set[asyncio.Task[Any]] = set()


def _spawn_inline(factory: Callable[[], Awaitable[Any]], *, task_name: str) -> asyncio.Task[Any]:
    """Schedule ``factory`` on the running loop without awaiting it.

    Args:
        factory: Zero-arg async callable that performs the work.
        task_name: Label for logs / the Task name.

    Returns:
        The scheduled ``asyncio.Task``.
    """

    async def _runner() -> Any:
        try:
            return await factory()
        except Exception:
            logger.exception("arq_inline_spawn_failed task=%s", task_name)
            return None

    task = asyncio.create_task(_runner(), name=f"arq-inline:{task_name}")
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)
    return task


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


def _job_id_purge(candidate_id: UUID) -> str:
    """Dedup key for one erased candidate's storage purge."""
    return f"purge:{candidate_id}"


def _job_id_expire(
    candidate_id: UUID, assessment_id: UUID, started_at: datetime | None = None
) -> str:
    """Dedup key for one *attempt's* deferred expiry finalize (P2-03).

    The attempt's ``started_at`` epoch is part of the key: after an HR reset
    and a re-start, the old deferred job still holds the plain
    ``expire:{cand}:{assess}`` id until it fires, which silently dropped the
    new attempt's exact-time finalize. The stale job is harmless when it runs
    (the new attempt is not yet expired, so it finalizes nothing).
    """
    base = f"expire:{candidate_id}:{assessment_id}"
    if started_at is None:
        return base
    return f"{base}:{int(started_at.timestamp())}"


def _job_id_refresh_rerun(candidate_id: UUID, token: str) -> str:
    """Dedup key for a follow-up refresh queued from inside a running one.

    The running job still owns ``refresh:{cand}``, so a follow-up under that id
    would be deduped. ``token`` (target input digest or time bucket) keeps one
    pending follow-up per distinct reason.
    """
    return f"refresh:{candidate_id}:rerun:{token}"


# Delay before a follow-up refresh runs, so a burst of score changes settles.
REFRESH_RERUN_DELAY = timedelta(seconds=30)


_BINARY_TYPES = (bytes, bytearray, memoryview)


class BinaryJobPayloadError(TypeError):
    """Raised when raw bytes would be pickled into a Redis job (P2-04)."""


def _reject_binary_payload(task_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    """Refuse to enqueue raw bytes (rendered PDFs, uploads) through Redis.

    Large binaries in job arguments bloat Redis memory and ride the pickle
    serializer. Upload to storage first and pass only the object key.

    Args:
        task_name: Job being enqueued (for the error message).
        args: Positional job arguments.
        kwargs: Keyword job arguments.

    Raises:
        BinaryJobPayloadError: Any argument is ``bytes``-like.
    """
    for value in (*args, *kwargs.values()):
        if isinstance(value, _BINARY_TYPES):
            raise BinaryJobPayloadError(
                f"refusing to enqueue {task_name} with a binary argument; "
                "store it and pass the storage key instead"
            )


async def _enqueue_or_run(
    *,
    task_name: str,
    coroutine_factory,
    job_id: str | None = None,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    await_inline: bool = True,
) -> Any:
    """Enqueue on Redis when a pool exists; otherwise run (or spawn) inline.

    Args:
        task_name: Registered ARQ function name.
        coroutine_factory: Zero-arg async callable that runs the work inline.
        job_id: Optional deterministic ARQ ``_job_id`` for deduplication.
        args: Positional args for ``enqueue_job`` (after the function name).
        kwargs: Keyword args for ``enqueue_job``.
        await_inline: When True (default), missing Redis awaits the work on
            this call. When False, missing Redis / enqueue failures spawn a
            background task so HTTP handlers stay fast.

    Returns:
        The ARQ ``Job`` when enqueued, ``None`` on dedup conflict, the inline
        result when ``await_inline`` is True, or the spawned ``Task`` when
        ``await_inline`` is False.
    """
    kwargs = dict(kwargs or {})
    _reject_binary_payload(task_name, args, kwargs)
    pool = get_arq_pool()
    if pool is None:
        logger.debug(
            "arq_inline_fallback task=%s job_id=%s await_inline=%s",
            task_name,
            job_id,
            await_inline,
        )
        if await_inline:
            return await coroutine_factory()
        return _spawn_inline(coroutine_factory, task_name=task_name)

    enqueue_kwargs: dict[str, Any] = dict(kwargs)
    if job_id:
        enqueue_kwargs["_job_id"] = job_id
    try:
        job = await pool.enqueue_job(task_name, *args, **enqueue_kwargs)
    except Exception:
        logger.exception(
            "arq_enqueue_failed task=%s job_id=%s await_inline=%s",
            task_name,
            job_id,
            await_inline,
        )
        # Prefer durability of side-effects over dropping work when Redis blips.
        if await_inline:
            return await coroutine_factory()
        return _spawn_inline(coroutine_factory, task_name=task_name)

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
    *,
    await_inline: bool = True,
) -> Any:
    """Queue post-submit scoring + AI + PDF prewarm for one assessment.

    Args:
        candidate_id: Candidate who submitted.
        assessment_id: Assessment that was submitted.
        await_inline: When False, never block the caller on Gemini / PDF / HR
            email — spawn a task if Redis is unavailable. Submit HTTP uses
            ``await_inline=False`` so the response stays under ~300ms.

    Returns:
        ARQ job, ``None`` when deduped, inline result, or spawned Task.
    """

    async def _run() -> None:
        await task_finalize_and_score_ai({}, candidate_id, assessment_id)

    return await _enqueue_or_run(
        task_name=task_finalize_and_score_ai.__name__,
        coroutine_factory=_run,
        job_id=_job_id_finalize(candidate_id, assessment_id),
        args=(str(candidate_id), str(assessment_id)),
        await_inline=await_inline,
    )


async def enqueue_refresh_report_synthesis(
    candidate_id: UUID,
    *,
    await_inline: bool = True,
) -> Any:
    """Queue technical backfill + JD synthesis refresh for a candidate.

    Args:
        candidate_id: Candidate whose report needs regeneration.
        await_inline: When False, a missing Redis pool spawns the work
            instead of awaiting Gemini on the caller (candidate submit).

    Returns:
        ARQ job, ``None`` when deduped, inline result, or spawned Task.
    """

    async def _run() -> None:
        await task_refresh_report_synthesis({}, candidate_id)

    return await _enqueue_or_run(
        task_name=task_refresh_report_synthesis.__name__,
        coroutine_factory=_run,
        job_id=_job_id_refresh(candidate_id),
        args=(str(candidate_id),),
        await_inline=await_inline,
    )


async def enqueue_refresh_report_synthesis_rerun(
    candidate_id: UUID,
    *,
    token: str,
    delay: timedelta = REFRESH_RERUN_DELAY,
) -> Any:
    """Queue a deferred follow-up refresh after the current one (P2-03).

    Called by ``refresh_report_synthesis`` when its inputs changed while it
    ran, or when it had to skip because another AI job was in flight. Without
    Redis this is a no-op: inline runs have no job-id dedup to lose requests
    to, and the next report view re-queues as usual.

    Args:
        candidate_id: Candidate whose report needs another pass.
        token: Distinguishes follow-ups (e.g. the new input digest prefix).
        delay: ARQ ``_defer_by``.

    Returns:
        ARQ job, or None when deduped / Redis is unavailable / enqueue failed.
    """
    pool = get_arq_pool()
    job_id = _job_id_refresh_rerun(candidate_id, token)
    if pool is None:
        logger.debug("arq_refresh_rerun_skipped_no_pool job_id=%s", job_id)
        return None
    try:
        job = await pool.enqueue_job(
            task_refresh_report_synthesis.__name__,
            str(candidate_id),
            _job_id=job_id,
            _defer_by=delay,
        )
    except Exception:
        logger.exception("arq_refresh_rerun_enqueue_failed job_id=%s", job_id)
        return None
    logger.info(
        "arq_refresh_rerun_%s job_id=%s",
        "deduped" if job is None else "enqueued",
        job_id,
    )
    return job


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
) -> asyncio.Task[Any]:
    """Upload a rendered PDF to the private reports bucket in the background.

    Used by the on-demand Download miss path (``render_report``) so the HTTP
    handler can return bytes without waiting on object storage. Post-submit
    package completion does **not** call this — ``finalize_and_score_ai`` →
    ``prewarm_report_pdf`` uses ``render_and_store_report`` to sync-store the
    PDF (and upsert ``candidate_reports``) before HR ever clicks Download.

    The upload always runs in-process and never goes through Redis: PDF bytes
    must not be pickled into job arguments. The object is a content-addressed
    cache, so a lost upload (process restart) only costs a re-render on the
    next Download.

    Args:
        corporate_id: Tenant id used as the object prefix.
        candidate_id: Candidate id used as the second path segment.
        cache_key: Content-addressed report cache key.
        content: PDF bytes.

    Returns:
        The spawned background ``asyncio.Task``.
    """

    async def _run() -> None:
        await task_store_cached_report(
            {}, corporate_id, candidate_id, cache_key, content
        )

    return _spawn_inline(
        _run,
        task_name=_job_id_store_report(corporate_id, candidate_id, cache_key),
    )


async def enqueue_purge_candidate_report_files(
    corporate_id: UUID, candidate_id: UUID
) -> Any:
    """Queue the right-to-erasure storage purge with retries (P1-16).

    Without Redis the purge runs as an in-process background task (one
    attempt; a failure is logged at ERROR and sent to Sentry).

    Args:
        corporate_id: Tenant id (object prefix).
        candidate_id: Erased candidate id.

    Returns:
        ARQ job, ``None`` when deduped, or the spawned Task.
    """

    async def _run() -> None:
        await task_purge_candidate_report_files({}, corporate_id, candidate_id)

    return await _enqueue_or_run(
        task_name=task_purge_candidate_report_files.__name__,
        coroutine_factory=_run,
        job_id=_job_id_purge(candidate_id),
        args=(str(corporate_id), str(candidate_id)),
        await_inline=False,
    )


async def enqueue_finalize_expired_assessment(
    candidate_id: UUID,
    assessment_id: UUID,
    *,
    defer_until: datetime,
    started_at: datetime | None = None,
) -> Any:
    """Schedule exact-time auto-finalize when a timed module starts.

    Uses ARQ ``_defer_until=expires_at``. When Redis is unavailable the job is
    skipped (not inlined) — the periodic sweep / dashboard hooks cover the gap.

    Args:
        candidate_id: Candidate who started the module.
        assessment_id: Timed assessment id.
        defer_until: UTC display deadline (``progress.expires_at``).
        started_at: Attempt start; scopes the job id to this attempt so an
            old attempt's deferred job cannot block a post-reset restart.

    Returns:
        ARQ job, ``None`` when deduped or Redis is unavailable.
    """
    pool = get_arq_pool()
    job_id = _job_id_expire(candidate_id, assessment_id, started_at)
    if pool is None:
        logger.debug(
            "arq_expire_skipped_no_pool job_id=%s",
            job_id,
        )
        return None
    try:
        job = await pool.enqueue_job(
            task_finalize_expired_assessment.__name__,
            str(candidate_id),
            str(assessment_id),
            _job_id=job_id,
            _defer_until=defer_until,
        )
    except Exception:
        logger.exception(
            "arq_expire_enqueue_failed job_id=%s",
            job_id,
        )
        return None
    if job is None:
        logger.info("arq_expire_deduped job_id=%s", job_id)
    else:
        logger.info(
            "arq_expire_enqueued job_id=%s defer_until=%s",
            job_id,
            defer_until.isoformat(),
        )
    return job
