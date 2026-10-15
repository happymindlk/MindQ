"""Provision a test HR client for the isolated client portal (/client/login).

Uses the same domain services as the ops "invite HR" flow, so local, staging,
and CI tenants are provisioned exactly like production ones:

1. Upsert a ``corporates`` row by slug.
2. Create/find a *confirmed* Supabase Auth user (no email sent).
3. Link it in ``hr_users`` with role ``hr`` (never demotes ops accounts).
4. Publish a package through ``ClientPackageService`` (real access code).
5. Optionally upsert sample candidates covering Invited / In Progress / Completed.

Every step is idempotent; re-running converges to the same state.

Usage (from backend/ with venv active, local Supabase running):
  python -m scripts.seed_test_client --email hr.test+acme@example.com --candidates 3

Exit codes: 0 success, 1 infrastructure failure, 2 refused (guard / ops email).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_progress import CandidateProgress
from app.models.corporate import Corporate
from app.models.package import Package
from app.schemas.client_package import CustomQuestionIn, DraftPackageRequest
from app.schemas.package_builder import QuestionType
from app.services.client_package import ClientPackageService, slugify_company_name
from app.services.hr_membership import (
    find_ops_role_for_email,
    hr_display_name,
    upsert_hr_membership,
)
from app.services.supabase_admin import SupabaseAdminError, ensure_auth_user

CANDIDATE_STATUSES: tuple[str, ...] = ("invited", "in_progress", "completed")

SAMPLE_QUESTIONS: tuple[CustomQuestionIn, ...] = (
    CustomQuestionIn(
        prompt="Which HTTP status code indicates a resource was created?",
        question_type=QuestionType.mcq,
        options=["200 OK", "201 Created", "204 No Content", "409 Conflict"],
        correct_answer_or_rubric="201 Created",
        evaluated_competency="API Design",
    ),
    CustomQuestionIn(
        prompt="Which index type best serves equality lookups on a UUID column in Postgres?",
        question_type=QuestionType.mcq,
        options=["B-tree", "GIN", "BRIN", "GiST"],
        correct_answer_or_rubric="B-tree",
        evaluated_competency="Databases",
    ),
)


class SeedError(Exception):
    """Seeding was refused (environment guard or protected account)."""


@dataclass(frozen=True)
class SeedOptions:
    """Inputs for one seed run."""

    email: str
    company: str = "Acme Test Co"
    slug: str | None = None
    package_title: str = "Backend Engineer Screen"
    target_role: str | None = "Backend Engineer"
    candidates: int = 3


@dataclass
class SeedResult:
    """Identifiers produced (or reused) by a seed run."""

    corporate_id: UUID
    user_id: UUID
    package_id: UUID
    access_code: str
    package_created: bool
    candidate_ids: list[UUID] = field(default_factory=list)


def check_environment(*, allow_non_debug: bool) -> None:
    """Refuse to seed production-like environments unless explicitly allowed.

    Args:
        allow_non_debug: Operator opt-in for staging (``DEBUG=false``).

    Raises:
        SeedError: ``DEBUG`` is false and no opt-in was given.
    """
    if not settings.DEBUG and not allow_non_debug:
        raise SeedError(
            "DEBUG is false (production-like config). Re-run with --allow-non-debug "
            "only if this is a staging environment."
        )


async def _upsert_corporate(
    db: AsyncSession, *, name: str, slug: str, contact_email: str
) -> Corporate:
    """Find the corporate by slug or create it.

    Args:
        db: Async database session.
        name: Display name used on creation.
        slug: Unique slug (lookup key).
        contact_email: HR contact stamped when the row has none.

    Returns:
        The persisted corporates row (flushed, not committed).
    """
    corporate = (
        await db.execute(select(Corporate).where(Corporate.slug == slug))
    ).scalar_one_or_none()
    if corporate is None:
        corporate = Corporate(name=name, slug=slug, contact_email=contact_email)
        db.add(corporate)
    elif not corporate.contact_email:
        corporate.contact_email = contact_email
    await db.flush()
    return corporate


async def _ensure_published_package(
    db: AsyncSession, *, corporate_id: UUID, title: str, target_role: str | None
) -> tuple[UUID, str, bool]:
    """Reuse a published package with this title, or draft + publish a new one.

    Args:
        db: Async database session.
        corporate_id: Owning tenant.
        title: Package title (idempotency key within the tenant).
        target_role: Role shown on the client dashboard.

    Returns:
        Tuple of (package id, candidate access code, whether it was created).
    """
    existing = (
        await db.execute(
            select(Package)
            .where(
                Package.corporate_id == corporate_id,
                Package.title == title,
                Package.status == "published",
                Package.is_active.is_(True),
            )
            .order_by(Package.published_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id, existing.access_code, False

    draft = await ClientPackageService.save_draft(
        db,
        DraftPackageRequest(
            corporate_id=corporate_id,
            title=title,
            description="Seeded test package for the HR client portal.",
            target_role=target_role,
            custom_questions=list(SAMPLE_QUESTIONS),
        ),
    )
    published = await ClientPackageService.publish(db, draft.id)
    return published.id, published.access_code, True


async def _seed_candidates(
    db: AsyncSession,
    *,
    corporate_id: UUID,
    package_id: UUID,
    access_code: str,
    count: int,
) -> list[UUID]:
    """Upsert ``count`` sample candidates cycling through each dashboard status.

    Args:
        db: Async database session.
        corporate_id: Owning tenant.
        package_id: Published package the candidates belong to.
        access_code: Package access code stored on each candidate.
        count: Number of candidates to upsert.

    Returns:
        Candidate ids in creation order.
    """
    if count <= 0:
        return []
    assessments = (
        await db.execute(
            select(Assessment.id)
            .where(Assessment.package_id == package_id)
            .order_by(Assessment.position)
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    ids: list[UUID] = []
    for index in range(count):
        status = CANDIDATE_STATUSES[index % len(CANDIDATE_STATUSES)]
        logged_in_at = None if status == "invited" else now - timedelta(hours=index + 1)
        candidate_id = (
            await db.execute(
                pg_insert(Candidate)
                .values(
                    corporate_id=corporate_id,
                    package_id=package_id,
                    full_name=f"Test Candidate {index + 1}",
                    email=f"candidate{index + 1}@seed.assesspulse.test",
                    access_code=access_code,
                    logged_in_at=logged_in_at,
                )
                .on_conflict_do_update(
                    constraint="uq_candidate_package_email",
                    set_={"logged_in_at": logged_in_at},
                )
                .returning(Candidate.id)
            )
        ).scalar_one()
        ids.append(candidate_id)

        if status == "invited":
            done = []
        elif status == "in_progress":
            done = list(assessments[:1]) if len(assessments) > 1 else []
        else:
            done = list(assessments)
        for position, assessment_id in enumerate(done):
            score = float(min(95, 68 + 9 * index + 3 * position))
            await db.execute(
                pg_insert(CandidateProgress)
                .values(
                    corporate_id=corporate_id,
                    candidate_id=candidate_id,
                    assessment_id=assessment_id,
                    status="COMPLETED",
                    started_at=now - timedelta(hours=index + 1),
                    completed_at=now - timedelta(minutes=30 * (index + 1)),
                    score=score,
                )
                .on_conflict_do_update(
                    constraint="uq_progress_candidate_assessment",
                    set_={"status": "COMPLETED", "score": score},
                )
            )
    await db.commit()
    return ids


async def seed(
    db: AsyncSession,
    options: SeedOptions,
    *,
    ensure_user: Callable[[str], UUID] = ensure_auth_user,
) -> SeedResult:
    """Provision a corporate, HR login, published package, and sample candidates.

    Args:
        db: Async database session.
        options: Seed inputs.
        ensure_user: Auth Admin user factory (injectable for tests).

    Returns:
        Identifiers for the seeded tenant.

    Raises:
        SeedError: The email already belongs to an internal operator.
        SupabaseAdminError: Auth Admin is misconfigured or failed.
    """
    email = options.email.strip().lower()
    if await find_ops_role_for_email(db, email):
        raise SeedError(
            f"{email} is an ops (admin/owner) account; ops accounts cannot use the client "
            "portal. Use a separate address, e.g. you+hr@example.com."
        )

    slug = options.slug or slugify_company_name(options.company)
    corporate = await _upsert_corporate(
        db, name=options.company, slug=slug, contact_email=email
    )
    # Supabase Auth Admin client is synchronous; keep the event loop free.
    user_id = await asyncio.to_thread(ensure_user, email)
    await upsert_hr_membership(
        db, user_id=user_id, corporate_id=corporate.id, full_name=hr_display_name(email)
    )
    await db.commit()

    package_id, access_code, created = await _ensure_published_package(
        db,
        corporate_id=corporate.id,
        title=options.package_title,
        target_role=options.target_role,
    )
    candidate_ids = await _seed_candidates(
        db,
        corporate_id=corporate.id,
        package_id=package_id,
        access_code=access_code,
        count=options.candidates,
    )
    return SeedResult(
        corporate_id=corporate.id,
        user_id=user_id,
        package_id=package_id,
        access_code=access_code,
        package_created=created,
        candidate_ids=candidate_ids,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--email", required=True, help="HR login email (must not be an ops account)")
    parser.add_argument("--company", default=SeedOptions.company)
    parser.add_argument("--slug", default=None, help="Defaults to a slug of --company")
    parser.add_argument("--package-title", default=SeedOptions.package_title)
    parser.add_argument("--target-role", default=SeedOptions.target_role)
    parser.add_argument("--candidates", type=int, default=SeedOptions.candidates)
    parser.add_argument(
        "--allow-non-debug",
        action="store_true",
        help="Permit running with DEBUG=false (staging only)",
    )
    return parser.parse_args(argv)


def _print_summary(result: SeedResult, email: str) -> None:
    frontend = settings.FRONTEND_URL.rstrip("/")
    local = any(host in settings.SUPABASE_URL for host in ("127.0.0.1", "localhost"))
    print("OK: test HR client provisioned")
    print(f"  corporate_id : {result.corporate_id}")
    print(f"  user_id      : {result.user_id}")
    print(f"  package_id   : {result.package_id} ({'created' if result.package_created else 'reused'})")
    print(f"  candidates   : {len(result.candidate_ids)}")
    print(f"  HR login     : {frontend}/client/login  (email: {email})")
    if local:
        print("  OTP inbox    : http://127.0.0.1:54324  (Mailpit)")
    print(f"  Candidate URL: {frontend}/portal?code={result.access_code}")
    print(f"  PIN          : {result.access_code}")


async def _run(options: SeedOptions) -> SeedResult:
    from app.database import SessionLocal, engine

    engine.echo = False
    try:
        async with SessionLocal() as db:
            return await seed(db, options)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    args = _parse_args(argv)
    options = SeedOptions(
        email=args.email,
        company=args.company,
        slug=args.slug,
        package_title=args.package_title,
        target_role=args.target_role,
        candidates=max(0, args.candidates),
    )
    try:
        check_environment(allow_non_debug=args.allow_non_debug)
        result = asyncio.run(_run(options))
    except SeedError as exc:
        print(f"REFUSED: {exc}")
        return 2
    except SupabaseAdminError as exc:
        print(f"FAIL: Supabase Auth Admin — {exc}")
        return 1
    _print_summary(result, options.email.strip().lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
