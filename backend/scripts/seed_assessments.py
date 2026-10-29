"""Reseed the 7 psychometric catalog modules from assessments.json.

QA/staging only. Clears candidate_responses and resets candidate_progress for
linked assessment snapshots before replacing item banks, so JSONB rewrites
cannot leave orphan answers under old question ids.

Usage (from backend/ with venv active):
  python -m scripts.seed_assessments
  python -m scripts.seed_assessments --allow-non-debug   # staging
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.assessment import Assessment
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.global_module import MODULE_STATUS_DRAFT, MODULE_STATUS_PUBLISHED, GlobalModule
from app.models.package_module import PackageModule
from app.models.template_question import TemplateQuestion
from app.schemas.question_payload import DEFAULT_CONFIDENTIALITY_NOTICE_TEXT, DEFAULT_TOP_DISCLAIMER_TEXT
from app.services.library import LibraryService
from app.services.psychometric_catalog import (
    CATEGORY_BY_SLUG,
    SCORING_PROFILES,
    TARGET_SLUGS,
    TIMER_CONFIG,
    assert_catalog_shape,
    questions_for,
)


class SeedError(Exception):
    """Seeding was refused (environment guard)."""


def check_environment(*, allow_non_debug: bool) -> None:
    """Refuse production-like configs unless explicitly allowed.

    Args:
        allow_non_debug: Operator opt-in for staging.

    Raises:
        SeedError: ``DEBUG`` is false and no opt-in was given.
    """
    if not settings.DEBUG and not allow_non_debug:
        raise SeedError(
            "DEBUG is false (production-like config). Re-run with --allow-non-debug "
            "only if this is a staging environment."
        )


def _minutes(seconds: int) -> int:
    return max(1, math.ceil(seconds / 60))


async def _modules_for_slug(session: AsyncSession, slug: str) -> list[GlobalModule]:
    rows = (
        await session.execute(
            select(GlobalModule).where(
                or_(GlobalModule.slug == slug, GlobalModule.slug.startswith(f"{slug}-v"))
            )
        )
    ).scalars().all()
    return list(rows)


async def _ensure_draft(session: AsyncSession, slug: str, title: str, category: str) -> GlobalModule:
    """Return an editable draft for ``slug``, cloning a published row when needed.

    Args:
        session: Open transaction.
        slug: Catalog module id.
        title: Display title for a newly created module.
        category: ``assessment_category``.

    Returns:
        Draft ``global_modules`` row.
    """
    existing = await _modules_for_slug(session, slug)
    draft = next((row for row in existing if row.status == MODULE_STATUS_DRAFT and row.is_active), None)
    if draft is not None:
        return draft
    published = [row for row in existing if row.status == MODULE_STATUS_PUBLISHED]
    published.sort(key=lambda row: int(row.version or 1), reverse=True)
    if published:
        source = published[0]
        lineage = source.lineage_id or source.id
        max_version = max(int(row.version or 1) for row in existing)
        clone_id = uuid4()
        clone = GlobalModule(
            id=clone_id,
            slug=f"{slug}-v{max_version + 1}"[:128],
            title=source.title,
            description=source.description,
            module_kind="psychometric",
            assessment_category=category,
            time_limit_minutes=source.time_limit_minutes,
            duration_seconds=source.duration_seconds,
            timer_mode=source.timer_mode,
            shuffle_questions=source.shuffle_questions,
            show_top_disclaimer=source.show_top_disclaimer,
            top_disclaimer_text=source.top_disclaimer_text,
            show_confidentiality_notice=source.show_confidentiality_notice,
            confidentiality_notice_text=source.confidentiality_notice_text,
            scoring_profile=source.scoring_profile,
            status=MODULE_STATUS_DRAFT,
            version=max_version + 1,
            lineage_id=lineage,
            parent_module_id=source.id,
            questions=[],
            is_active=True,
            position=source.position,
        )
        session.add(clone)
        await session.flush()
        return clone

    module_id = uuid4()
    max_pos = (
        await session.execute(
            select(GlobalModule.position).where(GlobalModule.module_kind == "psychometric")
        )
    ).scalars().all()
    module = GlobalModule(
        id=module_id,
        slug=slug,
        title=title,
        description=None,
        module_kind="psychometric",
        assessment_category=category,
        time_limit_minutes=None,
        duration_seconds=None,
        timer_mode="flexible",
        shuffle_questions=False,
        show_top_disclaimer=True,
        top_disclaimer_text=DEFAULT_TOP_DISCLAIMER_TEXT,
        show_confidentiality_notice=True,
        confidentiality_notice_text=DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
        scoring_profile=SCORING_PROFILES.get(slug),
        status=MODULE_STATUS_DRAFT,
        version=1,
        lineage_id=module_id,
        questions=[],
        is_active=True,
        position=(max(max_pos) + 1) if max_pos else 1,
    )
    session.add(module)
    await session.flush()
    return module


async def _lineage_ids(session: AsyncSession, module: GlobalModule) -> list[UUID]:
    lineage = module.lineage_id or module.id
    rows = (
        await session.execute(select(GlobalModule.id).where(GlobalModule.lineage_id == lineage))
    ).scalars().all()
    ids = {module.id, lineage, *rows}
    return list(ids)


async def _wipe_child_rows(session: AsyncSession, assessment_ids: list[UUID]) -> tuple[int, int]:
    """Delete responses and reset progress for QA snapshots.

    Args:
        session: Open transaction.
        assessment_ids: Live ``assessments.id`` values.

    Returns:
        ``(deleted_responses, reset_progress)``.
    """
    if not assessment_ids:
        return 0, 0
    deleted = await session.execute(
        delete(CandidateResponse).where(CandidateResponse.assessment_id.in_(assessment_ids))
    )
    progress_rows = (
        await session.execute(
            select(CandidateProgress).where(CandidateProgress.assessment_id.in_(assessment_ids))
        )
    ).scalars().all()
    for row in progress_rows:
        row.status = "NOT_STARTED"
        row.started_at = None
        row.completed_at = None
        row.score = None
        row.client_duration_seconds = None
        row.server_duration_seconds = None
        row.overtime = False
        row.facet_scores = None
        row.derived_profile = None
        row.score_details = None
        row.scoring_version = None
    return int(deleted.rowcount or 0), len(progress_rows)


async def _replace_questions(
    session: AsyncSession, draft: GlobalModule, stored: list[dict]
) -> None:
    await session.execute(delete(TemplateQuestion).where(TemplateQuestion.template_id == draft.id))
    for index, question in enumerate(stored):
        session.add(
            TemplateQuestion(
                id=uuid4(),
                template_id=draft.id,
                question_text=str(question.get("text") or ""),
                evaluation_rubric="",
                question_payload=question,
                is_active=True,
                position=index,
            )
        )
    await session.flush()
    await LibraryService.rebuild_module_questions_json(session, draft.id)


async def _sync_snapshots(
    session: AsyncSession,
    lineage_ids: list[UUID],
    stored: list[dict],
    *,
    duration_seconds: int,
    timer_mode: str,
    shuffle: bool,
    scoring_profile: str | None,
) -> int:
    minutes = _minutes(duration_seconds)
    assessments = (
        await session.execute(select(Assessment).where(Assessment.global_module_id.in_(lineage_ids)))
    ).scalars().all()
    for row in assessments:
        row.questions = stored
        row.duration_seconds = duration_seconds
        row.time_limit_minutes = minutes
        row.timer_mode = timer_mode
        row.shuffle_questions = shuffle
        row.scoring_profile = scoring_profile
        row.module_kind = "psychometric"
    packages = (
        await session.execute(
            select(PackageModule).where(PackageModule.global_module_id.in_(lineage_ids))
        )
    ).scalars().all()
    for row in packages:
        row.questions = stored
    return len(assessments)


async def seed_assessments(session: AsyncSession) -> dict[str, int]:
    """Reseed all seven catalog modules inside the caller's transaction.

    Args:
        session: Database session (caller owns commit).

    Returns:
        Per-slug item counts written.
    """
    by_id = assert_catalog_shape()
    counts: dict[str, int] = {}
    for slug in TARGET_SLUGS:
        module = by_id[slug]
        duration_seconds, timer_mode, shuffle = TIMER_CONFIG[slug]
        scoring_profile = SCORING_PROFILES.get(slug)
        stored = questions_for(module)
        draft = await _ensure_draft(
            session,
            slug,
            str(module.get("displayName") or slug),
            CATEGORY_BY_SLUG[slug],
        )
        lineage_ids = await _lineage_ids(session, draft)
        assessment_ids = list(
            (
                await session.execute(
                    select(Assessment.id).where(Assessment.global_module_id.in_(lineage_ids))
                )
            ).scalars().all()
        )
        await _wipe_child_rows(session, assessment_ids)
        await _replace_questions(session, draft, stored)
        draft.title = str(module.get("displayName") or draft.title)
        draft.module_kind = "psychometric"
        draft.assessment_category = CATEGORY_BY_SLUG[slug]
        draft.duration_seconds = duration_seconds
        draft.time_limit_minutes = _minutes(duration_seconds)
        draft.timer_mode = timer_mode
        draft.shuffle_questions = shuffle
        draft.scoring_profile = scoring_profile
        draft.status = MODULE_STATUS_PUBLISHED
        draft.published_at = datetime.now(timezone.utc)
        await session.flush()
        rebuilt = list(draft.questions or [])
        await _sync_snapshots(
            session,
            lineage_ids,
            rebuilt,
            duration_seconds=duration_seconds,
            timer_mode=timer_mode,
            shuffle=shuffle,
            scoring_profile=scoring_profile,
        )
        counts[slug] = len(rebuilt)
    return counts


async def _run() -> dict[str, int]:
    from app.database import SessionLocal, engine

    engine.echo = False
    try:
        async with SessionLocal() as session:
            async with session.begin():
                return await seed_assessments(session)
    finally:
        await engine.dispose()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reseed psychometric catalog modules.")
    parser.add_argument(
        "--allow-non-debug",
        action="store_true",
        help="Permit running when DEBUG=false (staging only).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list.

    Returns:
        Process exit code.
    """
    args = _parse_args(argv)
    try:
        check_environment(allow_non_debug=args.allow_non_debug)
        counts = asyncio.run(_run())
    except SeedError as exc:
        print(f"REFUSED: {exc}")
        return 2
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    total = sum(counts.values())
    print(f"DEBUG={settings.DEBUG}")
    for slug, count in counts.items():
        duration, mode, shuffle = TIMER_CONFIG[slug]
        print(f"  {slug}: {count} items, {duration}s {mode}" + (" shuffle" if shuffle else ""))
    print(f"  total items: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
