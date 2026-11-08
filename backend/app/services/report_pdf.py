"""Shared server-side MindQ Report PDF delivery for every portal.

Admin and client downloads both go through ``serve_report_pdf`` so they render
from the same WeasyPrint template and share one content-addressed cache entry
(the report payload is identical across portals, so is the cache key).
Callers MUST authorize access to the candidate before calling.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import BackgroundTasks
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.schemas.mindq_report import MindQReportResponse
from app.services import storage as storage_service
from app.services.report_cache import report_cache_key
from app.services.report_service import ReportService

logger = logging.getLogger(__name__)

REPORT_FILE_PREFIX = "MindQ Report"
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

CacheState = Literal["HIT", "MISS", "BYPASS"]
Portal = Literal["admin", "client"]


@dataclass(frozen=True)
class RenderedReport:
    """Report bytes plus how they were produced.

    Attributes:
        content: PDF bytes, or HTML bytes when WeasyPrint is unavailable.
        is_pdf: Whether ``content`` is a PDF.
        cache_state: ``HIT`` (served from storage), ``MISS`` (rendered, queued
            for caching), or ``BYPASS`` (rendered, deliberately not cached).
    """

    content: bytes
    is_pdf: bool
    cache_state: CacheState


def sanitize_report_name(value: str | None, *, fallback: str = "Candidate") -> str:
    """Strip characters that OS / zip tooling reject from a display name.

    Args:
        value: Untrusted display name (candidate or package title).
        fallback: Used when ``value`` is empty after sanitization.

    Returns:
        A filesystem-safe name, never empty.
    """
    cleaned = " ".join(_ILLEGAL_FILENAME_CHARS.sub(" ", value or "").split())
    cleaned = cleaned.rstrip(". ")[:120].strip()
    return cleaned or fallback


def report_filename(candidate_name: str | None, ext: str) -> str:
    """Return ``MindQ Report - {name}.{ext}`` for a single report download or zip entry.

    Args:
        candidate_name: Candidate full name (untrusted; may be non-Latin).
        ext: File extension without the dot.

    Returns:
        Sanitized filename (UTF-8 safe for zip entries / Content-Disposition).
    """
    return f"{REPORT_FILE_PREFIX} - {sanitize_report_name(candidate_name)}.{ext}"


def report_content_disposition(candidate_name: str | None, ext: str) -> str:
    """Build ``Content-Disposition`` for ``MindQ Report - {name}.{ext}``.

    Args:
        candidate_name: Candidate full name (untrusted; may be non-Latin).
        ext: File extension without the dot.

    Returns:
        Header value with an ASCII fallback and an RFC 5987 UTF-8 filename.
    """
    cleaned = sanitize_report_name(candidate_name)
    ascii_cleaned = " ".join(cleaned.encode("ascii", "ignore").decode("ascii").split()) or "Candidate"
    filename = f"{REPORT_FILE_PREFIX} - {cleaned}.{ext}"
    ascii_filename = f"{REPORT_FILE_PREFIX} - {ascii_cleaned}.{ext}"
    return f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{quote(filename)}'


async def render_report(
    report: MindQReportResponse,
    *,
    corporate_id: UUID,
    candidate_id: UUID,
    background_tasks: BackgroundTasks,
    portal: Portal,
) -> RenderedReport:
    """Return cached PDF bytes, or render once and queue the upload.

    Args:
        report: Fully assembled report for an already-authorized candidate.
        corporate_id: Candidate's tenant (storage prefix).
        candidate_id: Candidate id (storage path segment).
        background_tasks: Request-scoped queue for the cache upload.
        portal: Calling portal, for telemetry only.

    Returns:
        Bytes, format, and cache outcome.
    """
    cache_key = report_cache_key(report)
    # A "generating" PDF is superseded within minutes (its narrative hash will
    # change), so caching it would only churn storage.
    cacheable = report.synthesis_status != "generating"

    cached = (
        await run_in_threadpool(
            storage_service.fetch_cached_report, corporate_id, candidate_id, cache_key.key
        )
        if cacheable
        else None
    )
    if cached is not None:
        rendered = RenderedReport(content=cached, is_pdf=True, cache_state="HIT")
    else:
        content, is_pdf = await run_in_threadpool(
            ReportService.generate_report_bytes,
            report=report.model_dump(mode="json"),
        )
        rendered = RenderedReport(
            content=content, is_pdf=is_pdf, cache_state="MISS" if cacheable else "BYPASS"
        )
        if is_pdf and cacheable:
            background_tasks.add_task(
                storage_service.store_cached_report,
                corporate_id,
                candidate_id,
                cache_key.key,
                content,
            )
    logger.info(
        "report_pdf_served portal=%s candidate_id=%s cache=%s narrative_hash=%s scores_hash=%s",
        portal,
        candidate_id,
        rendered.cache_state,
        cache_key.narrative_hash[:12],
        cache_key.scores_hash[:12],
    )
    return rendered


async def serve_report_pdf(
    report: MindQReportResponse,
    *,
    corporate_id: UUID,
    candidate_id: UUID,
    background_tasks: BackgroundTasks,
    portal: Portal,
) -> StreamingResponse:
    """Render (or fetch) the report and wrap it in the download response.

    Args:
        report: Fully assembled report for an already-authorized candidate.
        corporate_id: Candidate's tenant (storage prefix).
        candidate_id: Candidate id (storage path segment).
        background_tasks: Request-scoped queue for the cache upload.
        portal: Calling portal, for telemetry only.

    Returns:
        Attachment response with ``X-Report-Type``, ``X-Report-Synthesis-Status``,
        and ``X-Report-Cache`` headers exposed to the browser.
    """
    rendered = await render_report(
        report,
        corporate_id=corporate_id,
        candidate_id=candidate_id,
        background_tasks=background_tasks,
        portal=portal,
    )
    ext = "pdf" if rendered.is_pdf else "html"
    return StreamingResponse(
        io.BytesIO(rendered.content),
        media_type="application/pdf" if rendered.is_pdf else "text/html",
        headers={
            "Content-Disposition": report_content_disposition(report.candidate_full_name, ext),
            "Access-Control-Expose-Headers": (
                "Content-Disposition, X-Report-Type, X-Report-Synthesis-Status, X-Report-Cache"
            ),
            "X-Report-Type": "PDF" if rendered.is_pdf else "HTML",
            "X-Report-Synthesis-Status": report.synthesis_status,
            "X-Report-Cache": rendered.cache_state,
            # Reports carry candidate PII; never let a shared proxy or the
            # browser's HTTP cache keep a copy outside our private bucket.
            "Cache-Control": "private, no-store",
        },
    )
