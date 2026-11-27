import logging
import time
import uuid as uuid_lib
from collections.abc import Iterable
from typing import Any
from uuid import UUID
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.database import run_db_op_with_retry
from app.exceptions import (
    AssessmentAlreadySubmittedError,
    AssessmentNotFoundError,
    AssessmentNotStartedError,
    AssessmentTimeExpiredError,
    UnknownQuestionError,
    is_progress_unique_violation,
)
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_evaluation import CandidateEvaluation
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_report import CandidateReport
from app.models.candidate_response import CandidateResponse
from app.models.corporate import Corporate
from app.models.package import Package
from app.models.support_ticket import SupportTicket
from app.schemas.candidate import CandidateAuthOtpVerifyRequest
from app.schemas.response import ResponseSave
from app.services.audit_log import log_candidate_erased
from app.services.instrument_results import SCORING_VERSION, build_score_details
from app.services.package_window import (
    ensure_module_launchable,
    ensure_package_open,
    window_state,
)
from app.services.profiles import ItemResult, ProfileInputs, resolve_profile
from app.services.psychometric_catalog import catalog_duration_seconds
from app.services.runner_payload import (
    display_expires_at,
    effective_duration_seconds,
    strict_deadline,
)
from app.services.scoring import ScoreResult, _extract_answer, score_assessment_detailed

logger = logging.getLogger(__name__)

COMPLETED_STATUS = "COMPLETED"
IN_PROGRESS_STATUS = "IN_PROGRESS"
NOT_STARTED_STATUS = "NOT_STARTED"

_DASHBOARD_STATUS = {
    COMPLETED_STATUS: "completed",
    IN_PROGRESS_STATUS: "in_progress",
    NOT_STARTED_STATUS: "not_started",
}


def _dashboard_module_status(raw: str | None) -> str:
    """Map a progress row status to the candidate dashboard lifecycle string.

    Args:
        raw: Stored ``candidate_progress.status`` (or None when no row).

    Returns:
        One of ``not_started``, ``in_progress``, ``completed``.
    """
    key = str(raw or NOT_STARTED_STATUS).strip().upper().replace("-", "_")
    return _DASHBOARD_STATUS.get(key, "not_started")


def _elapsed_decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(round(float(value), 2)))


def derive_profile_payload(
    assessment: Assessment,
    result: ScoreResult,
    responses: Iterable[CandidateResponse],
    elapsed_seconds: float | None,
) -> dict[str, Any] | None:
    """Run the assessment's profile resolver, if any, for persistence.

    Resolver bugs are logged and swallowed: the submission and raw facet
    scores must still be saved, and the profile can be recomputed later.

    Args:
        assessment: Submitted assessment (provides ``scoring_profile``).
        result: Generic scoring output.
        responses: Saved candidate responses for this assessment.
        elapsed_seconds: Server-measured module duration, if known.

    Returns:
        JSON-ready DerivedProfile dict, or None when no resolver applies/fails.
    """
    profile_key = getattr(assessment, "scoring_profile", None)
    if not profile_key:
        return None
    try:
        inputs = ProfileInputs(
            facet_scores=result.facet_scores,
            item_results=[
                ItemResult(
                    question_id=str(r.question_id),
                    response=_extract_answer(r.response),
                    elapsed_seconds=(
                        float(r.elapsed_seconds)
                        if getattr(r, "elapsed_seconds", None) is not None
                        else None
                    ),
                )
                for r in responses
            ],
            elapsed_seconds=elapsed_seconds,
        )
        profile = resolve_profile(profile_key, inputs)
    except Exception:
        logger.exception(
            "profile_resolver_failed assessment_id=%s key=%s", assessment.id, profile_key
        )
        return None
    return profile.model_dump(mode="json") if profile else None


def assessment_duration_seconds(assessment: Assessment) -> int | None:
    """Resolve module duration, falling back to catalog defaults for legacy rows.

    Args:
        assessment: Package assessment (or SimpleNamespace in tests).

    Returns:
        Duration in seconds, or None when untimed / unrecognized.
    """
    resolved = effective_duration_seconds(
        getattr(assessment, "duration_seconds", None),
        getattr(assessment, "time_limit_minutes", None),
    )
    if resolved:
        return resolved
    return catalog_duration_seconds(
        title=getattr(assessment, "title", None),
        scoring_profile=getattr(assessment, "scoring_profile", None),
    )


def is_strict_expired(
    assessment: Assessment, progress: CandidateProgress | None, now: datetime
) -> bool:
    """Whether a timed attempt is past its server write deadline (including grace).

    Every module with a positive duration hard-cuts regardless of
    ``timer_mode`` (``strict`` / ``flexible`` tags are display metadata only).

    Args:
        assessment: Assessment with timer configuration.
        progress: Candidate progress (provides started_at / expires_at).
        now: Current UTC time.

    Returns:
        True when the module is timed and ``now`` is past the grace deadline.
    """
    deadline = strict_deadline(
        getattr(progress, "started_at", None) if progress else None,
        assessment_duration_seconds(assessment),
        expires_at=getattr(progress, "expires_at", None) if progress else None,
    )
    return deadline is not None and now > deadline


def is_display_expired(
    assessment: Assessment, progress: CandidateProgress | None, now: datetime
) -> bool:
    """Whether a timed attempt is past its display deadline (no grace).

    Used by the server-side auto-finalize sweep so abandoned attempts complete
    as soon as the visible clock hits zero.

    Args:
        assessment: Assessment with timer configuration.
        progress: Candidate progress row.
        now: Current UTC time.

    Returns:
        True when timed and ``now`` is at or past the display deadline.
    """
    if progress is None:
        return False
    expires = getattr(progress, "expires_at", None)
    if expires is None:
        expires = display_expires_at(
            getattr(progress, "started_at", None),
            assessment_duration_seconds(assessment),
        )
    if expires is None:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    clock = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return clock >= expires


def ensure_not_submitted(progress: CandidateProgress | None) -> None:
    """Raise if this assessment is already locked after submit."""
    if progress is not None and progress.status == COMPLETED_STATUS:
        raise AssessmentAlreadySubmittedError()


def question_ids(assessment: Assessment) -> set[str]:
    """Ids of every question in the stored bank for ``assessment``.

    Args:
        assessment: Assessment whose ``questions`` JSONB defines valid ids.

    Returns:
        Set of question ids as strings.
    """
    ids: set[str] = set()
    for raw in getattr(assessment, "questions", None) or []:
        if isinstance(raw, dict) and raw.get("id") is not None:
            ids.add(str(raw["id"]))
    return ids


def ensure_known_question(assessment: Assessment, question_id: str) -> None:
    """Reject answers for ids outside the bank (row spam / evidence injection).

    Args:
        assessment: Target assessment (questions already loaded).
        question_id: Candidate-supplied question id.

    Raises:
        UnknownQuestionError: When the id is not in the stored bank.
    """
    if str(question_id) not in question_ids(assessment):
        raise UnknownQuestionError()


async def ensure_question_in_bank(
    session: AsyncSession, assessment_id: UUID, question_id: str
) -> None:
    """Validate ``question_id`` via JSONB containment without shipping the bank.

    Args:
        session: Async database session.
        assessment_id: Assessment whose ``questions`` JSONB is authoritative.
        question_id: Candidate-supplied question id.

    Raises:
        UnknownQuestionError: When the id is not present in the bank.
    """
    found = (
        await session.execute(
            select(Assessment.id).where(
                Assessment.id == assessment_id,
                Assessment.questions.contains([{"id": str(question_id)}]),
            )
        )
    ).scalar_one_or_none()
    if found is None:
        raise UnknownQuestionError()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ``session.info`` key holding the database ``now()`` read by the last gate
# query on this session (P2-05).
DB_NOW_INFO_KEY = "mindq_db_now"


def _remember_db_now(session: AsyncSession, value: Any) -> None:
    """Stash the gate query's database ``now()`` on the session.

    Args:
        session: Session the gate query ran on.
        value: The ``func.now()`` column from that query.
    """
    info = getattr(session, "info", None)
    if isinstance(info, dict) and isinstance(value, datetime):
        info[DB_NOW_INFO_KEY] = (
            value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        )


def request_clock(session: AsyncSession) -> datetime:
    """Database clock read by this session's last gate query (P2-05).

    Expiry, launchability and the sweep compare against Postgres ``now()``
    rather than each app node's clock, so skew between API hosts cannot move
    a candidate's deadline. ``load_runner_context`` / ``_gate_autosave`` /
    ``list_expired_in_progress`` select ``func.now()`` alongside the row they
    already load (no extra round trip) and record it here; follow-on code in
    the same request (``submit_test``, ``ensure_started``, the ``/start``
    response) reuses it. Falls back to the app clock when no gate ran.

    Args:
        session: Request / job session.

    Returns:
        Timezone-aware UTC instant.
    """
    info = getattr(session, "info", None)
    if isinstance(info, dict):
        value = info.get(DB_NOW_INFO_KEY)
        if isinstance(value, datetime):
            return value
    return _utcnow()


class CandidateService:
    @staticmethod
    async def login(
        session: AsyncSession, login_data: CandidateAuthOtpVerifyRequest
    ) -> tuple[Candidate, bool]:
        """Authenticate or register a candidate for a package.

        Returns:
            Tuple of (candidate, is_new_registration).
        """
        raw_code = (login_data.access_code or "").strip()
        if not raw_code:
            raise ValueError("Invalid access code")

        pkg_result = await session.execute(
            select(Package).where(
                Package.access_code.in_((raw_code, raw_code.upper())),
                Package.is_active.is_(True),
            )
        )
        package = pkg_result.scalars().first()

        display_name = login_data.full_name
        first_name = login_data.first_name
        email_norm = str(login_data.email).strip().lower()

        if not package:
            invited = (
                await session.execute(
                    select(Candidate).where(
                        func.lower(Candidate.access_code) == raw_code.lower(),
                        Candidate.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if not invited:
                raise ValueError("Invalid access code")
            if invited.email.lower() != email_norm.lower():
                raise ValueError("Email does not match this invitation")
            invited_package = (
                await session.execute(select(Package).where(Package.id == invited.package_id))
            ).scalars().first()
            await CandidateService._ensure_login_window(session, invited_package, invited)
            invited.full_name = display_name
            invited.first_name = first_name
            invited.logged_in_at = _utcnow()
            invited.terms_accepted_at = _utcnow()
            await session.commit()
            await session.refresh(invited)
            return invited, False

        cand_result = await session.execute(
            select(Candidate).where(
                func.lower(Candidate.email) == email_norm.lower(),
                Candidate.package_id == package.id,
                Candidate.deleted_at.is_(None),
            )
        )
        candidate = cand_result.scalars().first()
        await CandidateService._ensure_login_window(session, package, candidate)

        is_new = False

        if not candidate:
            # Package access codes are invite-only unless open enrollment is enabled.
            if not getattr(package, "allow_open_enrollment", False):
                raise ValueError(
                    "An invitation is required for this package. "
                    "Use the access code from your invite email, or ask your organization to invite you."
                )
            is_new = True
            candidate = Candidate(
                corporate_id=package.corporate_id,
                package_id=package.id,
                first_name=first_name,
                full_name=display_name,
                email=email_norm,
                access_code=package.access_code,
            )
            session.add(candidate)
        else:
            candidate.full_name = display_name
            candidate.first_name = first_name

        candidate.logged_in_at = _utcnow()
        candidate.terms_accepted_at = _utcnow()
        await session.commit()
        await session.refresh(candidate)
        return candidate, is_new

    @staticmethod
    async def _has_unfinished_module(session: AsyncSession, candidate_id: UUID) -> bool:
        """True when the candidate opened a module but has not submitted it."""
        row = (
            await session.execute(
                select(CandidateProgress.id).where(
                    CandidateProgress.candidate_id == candidate_id,
                    CandidateProgress.started_at.is_not(None),
                    CandidateProgress.status != COMPLETED_STATUS,
                )
            )
        ).scalars().first()
        return row is not None

    @staticmethod
    async def _ensure_login_window(
        session: AsyncSession, package: Package | None, candidate: Candidate | None
    ) -> None:
        """Block login outside the package window, except to finish started work.

        Args:
            session: Async database session.
            package: Package being entered (None skips the check).
            candidate: Existing candidate row, if any.

        Raises:
            PackageNotOpenError: Before ``open_time``.
            PackageClosedError: After ``close_time`` with nothing left in progress.
        """
        if package is None:
            return
        open_time = getattr(package, "open_time", None)
        close_time = getattr(package, "close_time", None)
        now = _utcnow()
        state = window_state(open_time, close_time, now)
        if state == "open":
            return
        if (
            state == "closed"
            and candidate is not None
            and await CandidateService._has_unfinished_module(session, candidate.id)
        ):
            return
        ensure_package_open(open_time, close_time, now)

    @staticmethod
    async def invite(
        session: AsyncSession,
        *,
        email: str,
        package_id: UUID,
        corporate_id: UUID,
        full_name: str | None = None,
    ) -> tuple[Candidate, bool]:
        """Insert or reuse a pending candidate row for HR invitation.

        Pending means `logged_in_at` is null — the live table is `candidates`
        (there is no separate `candidate_assessments` table).

        Args:
            session: Async SQLAlchemy session.
            email: Candidate email address.
            package_id: Package to invite into.
            corporate_id: Authenticated HR tenant.
            full_name: Optional display name; defaults to the email local-part.

        Returns:
            Tuple of (candidate, created).
        """
        package = (
            await session.execute(select(Package).where(Package.id == package_id))
        ).scalars().first()
        if not package or package.corporate_id != corporate_id:
            raise LookupError("Package not found")
        if not package.is_active:
            raise ValueError("Package is not active")

        email_norm = email.strip().lower()
        display = (full_name or "").strip() or email_norm.split("@")[0]

        existing = (
            await session.execute(
                select(Candidate).where(
                    Candidate.package_id == package.id,
                    func.lower(Candidate.email) == email_norm,
                    Candidate.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if existing:
            return existing, False

        # Share the package PIN so invite emails, Client Portal "Copy Link",
        # and OTP login all use the same ``package.access_code``.
        candidate = Candidate(
            corporate_id=corporate_id,
            package_id=package.id,
            full_name=display,
            email=email_norm,
            access_code=package.access_code,
        )
        session.add(candidate)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = (
                await session.execute(
                    select(Candidate).where(
                        Candidate.package_id == package.id,
                        func.lower(Candidate.email) == email_norm,
                        Candidate.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if existing:
                return existing, False
            raise
        await session.refresh(candidate)
        return candidate, True

    @staticmethod
    async def get_candidate(session: AsyncSession, candidate_id: UUID) -> Candidate | None:
        async def _load() -> Candidate | None:
            result = await session.execute(
                select(Candidate).where(
                    Candidate.id == candidate_id,
                    Candidate.deleted_at.is_(None),
                )
            )
            return result.scalars().first()

        return await run_db_op_with_retry(_load, session=session)

    @staticmethod
    async def soft_delete_candidate(
        session: AsyncSession,
        candidate: Candidate,
        *,
        admin_user_id: UUID,
    ) -> Candidate:
        """Mark a candidate as soft-deleted so they leave active lists.

        Preserves the row and related progress/responses/evaluations for
        historical audit. Callers must already enforce ops-only access.

        Args:
            session: Open async SQLAlchemy session.
            candidate: Active ``candidates`` row to hide.
            admin_user_id: Authenticated ops actor id for logging.

        Returns:
            The same candidate instance after ``deleted_at`` is set.
        """
        if candidate.deleted_at is not None:
            return candidate
        candidate.deleted_at = _utcnow()
        await session.commit()
        await session.refresh(candidate)
        logger.info(
            "candidate_soft_deleted",
            extra={
                "event": "candidate_soft_deleted",
                "admin_user_id": str(admin_user_id),
                "corporate_id": str(candidate.corporate_id),
                "candidate_id": str(candidate.id),
            },
        )
        return candidate

    @staticmethod
    async def reset_assessment(session: AsyncSession, candidate: Candidate) -> Candidate:
        """Wipe responses, progress, reports, and evaluations so the candidate can retake.

        Clears module answers, attempt timers (including ``expires_at``), scores,
        cached report snapshots / JD narrative, ``logged_in_at`` and
        ``hr_notified_at``. Invite
        identity (email, access_code, package) is kept.

        Args:
            session: Open async SQLAlchemy session.
            candidate: Existing ``candidates`` row already loaded by the caller.

        Returns:
            The same candidate instance after ``logged_in_at`` is cleared and
            the transaction is committed.
        """
        candidate_id = candidate.id
        # Lock progress rows FIRST, in the same order autosave / submit use
        # (progress FOR UPDATE, then responses). Deleting responses first
        # inverted that order and could deadlock (40P01) against a candidate
        # who is answering while HR clicks Reset. ORDER BY id keeps the lock
        # order deterministic across this candidate's modules.
        await session.execute(
            select(CandidateProgress.id)
            .where(CandidateProgress.candidate_id == candidate_id)
            .order_by(CandidateProgress.id)
            .with_for_update()
        )
        await session.execute(
            delete(CandidateResponse).where(CandidateResponse.candidate_id == candidate_id)
        )
        await session.execute(
            update(CandidateProgress)
            .where(CandidateProgress.candidate_id == candidate_id)
            .values(
                status=NOT_STARTED_STATUS,
                started_at=None,
                expires_at=None,
                completed_at=None,
                score=None,
                client_duration_seconds=None,
                server_duration_seconds=None,
                overtime=False,
                facet_scores=None,
                derived_profile=None,
                score_details=None,
                scoring_version=None,
            )
        )
        await session.execute(
            delete(CandidateReport).where(CandidateReport.candidate_id == candidate_id)
        )
        await session.execute(
            delete(CandidateEvaluation).where(CandidateEvaluation.candidate_id == candidate_id)
        )
        candidate.logged_in_at = None
        # A retake must notify HR again when the package re-completes (P2-02).
        candidate.hr_notified_at = None
        await session.commit()
        await session.refresh(candidate)
        return candidate

    @staticmethod
    async def erase_candidate(
        session: AsyncSession,
        candidate: Candidate,
        *,
        admin_user_id: UUID,
    ) -> tuple[UUID, UUID]:
        """Hard-delete a candidate after unlinking support-ticket PII.

        Scrubs ``support_tickets`` (nulls ``candidate_id``, redacts free-text
        fields), then deletes the ``candidates`` row so PostgreSQL
        ``ON DELETE CASCADE`` removes responses, progress, evaluations, and
        report snapshots. Callers must purge object storage using the returned
        ids after this method commits.

        Args:
            session: Open async SQLAlchemy session.
            candidate: Loaded ``candidates`` row to erase.
            admin_user_id: Authenticated actor id for the audit event.

        Returns:
            ``(corporate_id, candidate_id)`` of the erased row for storage purge.
        """
        corporate_id = candidate.corporate_id
        candidate_id = candidate.id
        await session.execute(
            update(SupportTicket)
            .where(SupportTicket.candidate_id == candidate_id)
            .values(
                candidate_id=None,
                details="[Candidate data erased]",
                description="[Candidate data erased]",
                submitter_email=None,
                contact_number=None,
                access_code_entered=None,
                entered_name=None,
                device_id=None,
                browser=None,
                page_url=None,
                path=None,
                user_agent=None,
            )
        )
        await session.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await session.commit()
        log_candidate_erased(
            admin_user_id=admin_user_id,
            corporate_id=corporate_id,
            candidate_id=candidate_id,
        )
        return corporate_id, candidate_id

    @staticmethod
    async def get_company_name(session: AsyncSession, candidate: Candidate) -> str:
        """Resolve the hiring organization display name for completion copy.

        Args:
            session: Async database session.
            candidate: Authenticated candidate (provides ``corporate_id``).

        Returns:
            Corporate name, or an empty string when the tenant row is missing.
        """
        corporate = (
            await session.execute(
                select(Corporate.name).where(Corporate.id == candidate.corporate_id)
            )
        ).scalar_one_or_none()
        return corporate or ""

    @staticmethod
    async def get_dashboard(session: AsyncSession, candidate: Candidate) -> dict:
        """Build the portal summary in a fixed number of queries (no N+1).

        Loads package, corporate name, assessments, and progress rows once each,
        then joins statuses in memory.
        """

        async def _load() -> dict:
            # Finalize abandoned timed attempts before building the roster so
            # In Progress cards flip to Completed without re-entering the runner.
            from app.services.assessment_expiry import finalize_expired_assessment

            await finalize_expired_assessment(session, candidate.id, enqueue=True)

            package = (
                await session.execute(select(Package).where(Package.id == candidate.package_id))
            ).scalars().first()
            company_name = (
                await session.execute(
                    select(Corporate.name).where(Corporate.id == candidate.corporate_id)
                )
            ).scalar_one_or_none() or ""

            # Dashboard only needs roster metadata — defer the questions JSONB
            # bank so every candidate page load does not ship multi-MB blobs.
            assessments = (
                await session.execute(
                    select(Assessment)
                    .where(Assessment.package_id == candidate.package_id)
                    .options(defer(Assessment.questions))
                    .order_by(Assessment.position)
                )
            ).scalars().all()

            progresses = (
                await session.execute(
                    select(CandidateProgress).where(
                        CandidateProgress.candidate_id == candidate.id
                    )
                )
            ).scalars().all()
            progress_map = {p.assessment_id: p for p in progresses}
            open_time = package.open_time if package else None
            close_time = package.close_time if package else None
            clock = _utcnow()
            state = window_state(open_time, close_time, clock)

            tests = []
            for a in assessments:
                progress = progress_map.get(a.id)
                status = _dashboard_module_status(
                    progress.status if progress else NOT_STARTED_STATUS
                )
                started = progress is not None and progress.started_at is not None
                # Mirrors require_writable_assessment so the UI never offers a launch the API rejects.
                launchable = status != "completed" and (
                    state == "open" or (state == "closed" and started)
                )
                duration = assessment_duration_seconds(a)
                expires = getattr(progress, "expires_at", None) if progress else None
                if expires is None and started:
                    expires = display_expires_at(progress.started_at, duration)
                remaining = None
                if status == "in_progress" and (expires is not None or duration):
                    from app.services.runner_payload import (
                        remaining_seconds as remaining_seconds_fn,
                    )

                    remaining = remaining_seconds_fn(
                        progress.started_at if progress else None,
                        duration,
                        clock,
                        expires_at=expires,
                    )
                tests.append(
                    {
                        "id": str(a.id),
                        "title": a.title,
                        "description": a.description,
                        "status": status,
                        "launchable": launchable,
                        "duration_seconds": duration,
                        "time_limit_seconds": duration,
                        "started_at": (
                            progress.started_at.isoformat()
                            if progress and progress.started_at
                            else None
                        ),
                        "expires_at": expires.isoformat() if expires else None,
                        "server_now": clock.isoformat(),
                        "remaining_seconds": remaining,
                    }
                )

            return {
                "package_title": package.title if package else "",
                "company_name": company_name,
                "candidate_name": candidate.full_name,
                "candidate_first_name": candidate.first_name,
                "open_time": open_time.isoformat() if open_time else None,
                "close_time": close_time.isoformat() if close_time else None,
                "window_state": state,
                "server_now": clock.isoformat(),
                "tests": tests,
            }

        return await run_db_op_with_retry(_load, session=session)

    @staticmethod
    async def get_assessment_for_candidate(
        session: AsyncSession, candidate: Candidate, assessment_id: UUID
    ) -> Assessment | None:
        result = await session.execute(
            select(Assessment).where(
                Assessment.id == assessment_id,
                Assessment.package_id == candidate.package_id,
            )
        )
        return result.scalars().first()

    @staticmethod
    async def get_candidates(
        session: AsyncSession,
        corporate_id: UUID | None = None,
        package_id: UUID | None = None,
        *,
        limit: int = 500,
        offset: int = 0,
    ):
        """Candidate tracker rows in a fixed number of queries (no N+1, P1-17).

        Timed-out attempts flip to Completed via the ARQ expiry cron (30s);
        no synchronous sweep on this HR/admin read path.
        """
        from app.services.progress_summary import (
            ProgressSummary,
            assessment_counts,
            progress_summaries,
        )

        stmt = select(Candidate).where(Candidate.deleted_at.is_(None))
        if corporate_id:
            stmt = stmt.where(Candidate.corporate_id == corporate_id)
        if package_id:
            stmt = stmt.where(Candidate.package_id == package_id)
        stmt = stmt.order_by(Candidate.created_at.desc(), Candidate.id).limit(limit).offset(offset)
        candidates = (await session.execute(stmt)).scalars().all()

        package_ids = {c.package_id for c in candidates}
        packages = (
            {
                p.id: p
                for p in (
                    await session.execute(select(Package).where(Package.id.in_(package_ids)))
                ).scalars().all()
            }
            if package_ids
            else {}
        )
        totals = await assessment_counts(session, package_ids)
        summaries = await progress_summaries(session, [c.id for c in candidates])

        tracker = []
        for cand in candidates:
            pkg = packages.get(cand.package_id)
            total = totals.get(cand.package_id, 0)
            summary = summaries.get(cand.id, ProgressSummary())
            completed = summary.completed
            in_progress = summary.in_progress

            status = "not_started"
            if total > 0 and completed == total:
                status = "completed"
            elif completed > 0 or in_progress > 0 or cand.logged_in_at:
                status = "in_progress"

            cand.package_title = pkg.title if pkg else "Unknown Package"
            cand.status = status
            cand.progress = f"{completed}/{total}"
            cand.score = (
                f"{round(summary.avg_score, 1)}%" if summary.avg_score is not None else "-"
            )
            tracker.append(cand)
        return tracker

    @staticmethod
    async def _get_progress(
        session: AsyncSession,
        candidate_id: UUID,
        assessment_id: UUID,
        *,
        for_update: bool = False,
    ) -> CandidateProgress | None:
        stmt = select(CandidateProgress).where(
            CandidateProgress.candidate_id == candidate_id,
            CandidateProgress.assessment_id == assessment_id,
        )
        if for_update:
            # Serialises concurrent submit/autosave for one attempt so the
            # COMPLETED check and the write happen under the same row lock.
            stmt = stmt.with_for_update()
        return (await session.execute(stmt)).scalars().first()

    @staticmethod
    async def require_assessment_in_package(
        session: AsyncSession, candidate: Candidate, assessment_id: UUID
    ) -> Assessment:
        assessment = await CandidateService.get_assessment_for_candidate(
            session, candidate, assessment_id
        )
        if not assessment:
            raise AssessmentNotFoundError()
        return assessment

    @staticmethod
    async def load_runner_context(
        session: AsyncSession,
        candidate: Candidate,
        assessment_id: UUID,
        *,
        for_update: bool = False,
        include_answers: bool = False,
        include_questions: bool = True,
    ) -> tuple[Assessment, CandidateProgress | None, dict[str, Any]]:
        """Load assessment, progress, and package window in one joined query.

        Args:
            session: Async database session.
            candidate: Authenticated candidate.
            assessment_id: Module being opened, started, or hydrated.
            for_update: Lock the progress row until the caller commits.
            include_answers: When True, also load saved answers for hydration.
            include_questions: When False, defer the questions JSONB blob so
                lightweight paths (``POST /start``) avoid shipping the bank.

        Returns:
            ``(assessment, progress, answers)``; progress is None if never opened;
            answers is empty when ``include_answers`` is False.

        Raises:
            AssessmentNotFoundError: Module is not in the candidate's package.
            AssessmentAlreadySubmittedError: Module is already completed.
            PackageNotOpenError: Package has not opened yet.
            PackageClosedError: Deadline passed and the module was never started.
        """
        stmt = (
            select(
                Assessment,
                CandidateProgress,
                Package.open_time,
                Package.close_time,
                func.now().label("db_now"),
            )
            .join(Package, Package.id == Assessment.package_id)
            .outerjoin(
                CandidateProgress,
                (CandidateProgress.candidate_id == candidate.id)
                & (CandidateProgress.assessment_id == Assessment.id),
            )
            .where(
                Assessment.id == assessment_id,
                Assessment.package_id == candidate.package_id,
            )
        )
        # Questions are already a pre-bundled JSONB column — defer them when the
        # caller only needs timer metadata so Supavisor does not ship the bank.
        if not include_questions:
            stmt = stmt.options(defer(Assessment.questions))
        # Never attach FOR UPDATE to this OUTER JOIN. Postgres rejects locking
        # the nullable side (`FOR UPDATE cannot be applied to the nullable side
        # of an outer join`, SQLSTATE 0A000), which surfaced as a generic 503
        # on POST /start for first-time attempts (no progress row yet).
        row = (await session.execute(stmt)).first()
        if row is None:
            raise AssessmentNotFoundError()
        assessment, progress, open_time, close_time, db_now = row
        _remember_db_now(session, db_now)
        if for_update and progress is not None:
            # Lock the progress row in a separate query so concurrent
            # start/autosave/submit still serialize when a row exists.
            # Missing-row races on first start are handled by the unique
            # constraint + IntegrityError path in ensure_started.
            progress = await CandidateService._get_progress(
                session, candidate.id, assessment_id, for_update=True
            )
        ensure_not_submitted(progress)
        ensure_module_launchable(
            open_time,
            close_time,
            progress.started_at if progress is not None else None,
            request_clock(session),
        )
        answers: dict[str, Any] = {}
        if include_answers:
            answers = await CandidateService.get_saved_answers(
                session, candidate.id, assessment_id
            )
        return assessment, progress, answers

    @staticmethod
    async def require_writable_assessment(
        session: AsyncSession,
        candidate: Candidate,
        assessment_id: UUID,
        *,
        for_update: bool = False,
        include_questions: bool = True,
    ) -> tuple[Assessment, CandidateProgress | None]:
        """Assessment must belong to the package, be unsubmitted, and be inside the window.

        Args:
            session: Async database session.
            candidate: Authenticated candidate.
            assessment_id: Module being opened, autosaved, or submitted.
            for_update: Lock the progress row until the caller commits.
            include_questions: When False, skip loading the questions JSONB
                (safe for ``POST /start``, which only arms the timer).

        Returns:
            ``(assessment, progress)``; progress is None if never opened.

        Raises:
            AssessmentNotFoundError: Module is not in the candidate's package.
            AssessmentAlreadySubmittedError: Module is already completed.
            PackageNotOpenError: Package has not opened yet.
            PackageClosedError: Deadline passed and the module was never started.
        """
        assessment, progress, _ = await CandidateService.load_runner_context(
            session,
            candidate,
            assessment_id,
            for_update=for_update,
            include_questions=include_questions,
        )
        return assessment, progress

    @staticmethod
    def answers_from_responses(responses: list[CandidateResponse]) -> dict[str, Any]:
        """Flatten stored JSONB responses into `{question_id: answer}` for hydration.

        Args:
            responses: Rows from `candidate_responses` for one assessment.

        Returns:
            Map of question id to the extracted answer value. Empty or unreadable
            payloads are omitted so the client does not hydrate blanks over a draft.
        """
        answers: dict[str, Any] = {}
        for row in responses:
            extracted = _extract_answer(row.response)
            if extracted is not None and extracted != "":
                answers[str(row.question_id)] = extracted
        return answers

    @staticmethod
    async def get_saved_answers(
        session: AsyncSession, candidate_id: UUID, assessment_id: UUID
    ) -> dict[str, Any]:
        """Load previously autosaved answers for a candidate assessment.

        Args:
            session: Active async SQLAlchemy session.
            candidate_id: Authenticated candidate.
            assessment_id: Assessment whose drafts should be hydrated.

        Returns:
            `{question_id: answer}` map used by the test runner on mount.
        """
        responses = (
            await session.execute(
                select(CandidateResponse).where(
                    CandidateResponse.candidate_id == candidate_id,
                    CandidateResponse.assessment_id == assessment_id,
                )
            )
        ).scalars().all()
        return CandidateService.answers_from_responses(list(responses))

    @staticmethod
    async def ensure_started(
        session: AsyncSession,
        candidate: Candidate,
        assessment: Assessment,
        progress: CandidateProgress | None,
        *,
        commit: bool = True,
    ) -> CandidateProgress:
        """Start the attempt clock after the candidate confirms they are ready.

        Called from ``POST /test/{id}/start`` (instruction screen CTA), not from
        ``GET /test``. Timers therefore begin only on explicit consent, while a
        resume of an already-started attempt is a no-op.

        Args:
            session: Async database session.
            candidate: Authenticated candidate.
            assessment: Assessment being opened.
            progress: Existing progress row, if any.
            commit: When False, leave the txn open so the caller can attach a
                ``MODULE_START`` log row and commit once.

        Returns:
            Progress row with ``started_at`` set.
        """
        if progress is not None and progress.started_at is not None:
            # Never reset / extend an already-running attempt's deadline.
            if progress.expires_at is None:
                duration = assessment_duration_seconds(assessment)
                deadline = display_expires_at(progress.started_at, duration)
                if deadline is not None:
                    progress.expires_at = deadline
                    if commit:
                        await session.commit()
            return progress
        # DB clock from the preceding gate query, so the deadline is on the
        # same clock every later gate compares against (P2-05).
        started = request_clock(session)
        duration = assessment_duration_seconds(assessment)
        deadline = display_expires_at(started, duration)
        if progress is None:
            progress = CandidateProgress(
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                assessment_id=assessment.id,
                status="IN_PROGRESS",
                started_at=started,
                expires_at=deadline,
            )
            session.add(progress)
        else:
            progress.status = "IN_PROGRESS"
            progress.started_at = started
            # Immutable once set — only assign when still null.
            if progress.expires_at is None:
                progress.expires_at = deadline
        if not commit:
            return progress
        try:
            await session.commit()
        except IntegrityError:
            # Two tabs opened the module at once; the other insert won.
            await session.rollback()
            existing = await CandidateService._get_progress(session, candidate.id, assessment.id)
            if existing is None:
                raise
            return existing
        return progress

    @staticmethod
    async def _gate_autosave(
        session: AsyncSession,
        candidate: Candidate,
        assessment_id: UUID,
        question_id: str,
    ) -> tuple[Assessment, CandidateProgress]:
        """Lock progress and validate the question in one query (no questions blob).

        Uses an INNER JOIN on ``candidate_progress`` so ``FOR UPDATE`` is legal,
        defers ``Assessment.questions``, and evaluates JSONB containment as a
        selected boolean so unknown ids fail without a second round-trip on the
        happy path.

        Args:
            session: Async database session.
            candidate: Authenticated candidate.
            assessment_id: Module being autosaved.
            question_id: Candidate-supplied question id.

        Returns:
            ``(assessment, progress)`` with a locked progress row.

        Raises:
            AssessmentNotFoundError: Module is not in the candidate's package.
            AssessmentAlreadySubmittedError: Module is already completed.
            AssessmentNotStartedError: Module was never started via ``POST /start``.
            AssessmentTimeExpiredError: Write deadline has passed.
            PackageNotOpenError: Package has not opened yet.
            PackageClosedError: Deadline passed and the module was never started.
            UnknownQuestionError: ``question_id`` is not in the stored bank.
        """
        qid = str(question_id)
        question_ok = Assessment.questions.contains([{"id": qid}]).label("question_ok")
        stmt = (
            select(
                Assessment,
                CandidateProgress,
                Package.open_time,
                Package.close_time,
                question_ok,
                func.now().label("db_now"),
            )
            .join(Package, Package.id == Assessment.package_id)
            .join(
                CandidateProgress,
                (CandidateProgress.candidate_id == candidate.id)
                & (CandidateProgress.assessment_id == Assessment.id),
            )
            .where(
                Assessment.id == assessment_id,
                Assessment.package_id == candidate.package_id,
            )
            .options(defer(Assessment.questions))
            .with_for_update(of=CandidateProgress)
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            exists = (
                await session.execute(
                    select(Assessment.id).where(
                        Assessment.id == assessment_id,
                        Assessment.package_id == candidate.package_id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                raise AssessmentNotFoundError()
            raise AssessmentNotStartedError()

        assessment, progress, open_time, close_time, in_bank, db_now = row
        _remember_db_now(session, db_now)
        if not in_bank:
            raise UnknownQuestionError()
        ensure_not_submitted(progress)
        clock = request_clock(session)
        ensure_module_launchable(
            open_time,
            close_time,
            progress.started_at,
            clock,
        )
        if progress.started_at is None:
            raise AssessmentNotStartedError()
        if is_strict_expired(assessment, progress, clock):
            raise AssessmentTimeExpiredError()
        return assessment, progress

    @staticmethod
    async def autosave_response(session: AsyncSession, candidate: Candidate, save_data: ResponseSave):
        """Persist one answer with a lean gate + single PostgreSQL upsert.

        Hot path is one locked join (progress + question containment, questions
        JSONB deferred) plus ``INSERT ... ON CONFLICT DO UPDATE`` — no extra
        SELECT round-trips and no full bank load.

        Past the write grace window (``expires_at + 15s``) the late answer is
        rejected, ``overtime`` is set, and the attempt is auto-finalized from
        answers already saved before the deadline.
        """
        started = time.perf_counter()
        try:
            assessment, progress = await CandidateService._gate_autosave(
                session,
                candidate,
                save_data.assessment_id,
                str(save_data.question_id),
            )
        except AssessmentTimeExpiredError as exc:
            # Reject this write; finalize with pre-expiry answers only.
            try:
                _progress, package_complete, _company, _title = (
                    await CandidateService.submit_test(
                        session,
                        candidate,
                        save_data.assessment_id,
                        pending_responses=None,
                    )
                )
            except AssessmentAlreadySubmittedError:
                pass
            else:
                # The caller must queue scoring for this finalize (the
                # expiry sweep only sees IN_PROGRESS rows and will skip it).
                exc.auto_finalized = True
                exc.package_complete = package_complete
            raise

        elapsed = _elapsed_decimal(save_data.elapsed_seconds)
        saved_at = _utcnow()
        qid = str(save_data.question_id)
        values: dict[str, Any] = {
            "id": uuid_lib.uuid4(),
            "corporate_id": candidate.corporate_id,
            "candidate_id": candidate.id,
            "assessment_id": assessment.id,
            "question_id": qid,
            "response": save_data.response,
            "elapsed_seconds": elapsed,
            "saved_at": saved_at,
        }
        update_set: dict[str, Any] = {
            "response": save_data.response,
            "saved_at": saved_at,
        }
        if elapsed is not None:
            update_set["elapsed_seconds"] = elapsed

        stmt = (
            pg_insert(CandidateResponse)
            .values(**values)
            .on_conflict_do_update(
                # Matches UNIQUE (candidate_id, assessment_id, question_id);
                # index_elements avoids depending on the auto-generated constraint name.
                index_elements=["candidate_id", "assessment_id", "question_id"],
                set_=update_set,
            )
            .returning(CandidateResponse)
        )
        response = (await session.scalars(stmt)).one()
        await session.commit()
        duration_ms = (time.perf_counter() - started) * 1000
        logger.debug(
            "autosave_complete candidate_id=%s assessment_id=%s question_id=%s duration_ms=%.1f",
            candidate.id,
            assessment.id,
            qid,
            duration_ms,
        )
        if duration_ms > 150:
            logger.warning(
                "autosave_slow candidate_id=%s assessment_id=%s duration_ms=%.1f",
                candidate.id,
                assessment.id,
                duration_ms,
            )
        return response

    @staticmethod
    def _apply_core_scores(
        progress: CandidateProgress,
        assessment: Assessment,
        responses: list[CandidateResponse],
        server_seconds: float | None,
    ) -> None:
        """Write local facet / profile / score_details onto a progress row in-memory.

        Args:
            progress: Progress row being completed.
            assessment: Assessment with the question bank.
            responses: Persisted (or flushed) answer rows for this attempt.
            server_seconds: Server-measured module duration, if known.
        """
        result = score_assessment_detailed(assessment.questions, responses)
        progress.score = result.score
        progress.facet_scores = result.facet_scores or None
        progress.derived_profile = derive_profile_payload(
            assessment, result, responses, server_seconds
        )
        progress.scoring_version = SCORING_VERSION
        progress.score_details = build_score_details(
            questions=assessment.questions,
            result=result,
            derived_profile=progress.derived_profile,
            category=(
                "cognitive"
                if (getattr(assessment, "module_kind", None) or "").strip().lower()
                == "psychometric"
                else "technical"
            ),
        )

    @staticmethod
    async def submit_test(
        session: AsyncSession,
        candidate: Candidate,
        assessment_id: UUID,
        pending_responses: list[ResponseSave] | None = None,
        client_duration_seconds: float | None = None,
        completed_at: datetime | None = None,
        *,
        record_complete_event: bool = False,
        request: Any | None = None,
    ):
        """Persist answers and mark COMPLETED; core scoring runs in background.

        Timed modules past their deadline still finalize, but late pending
        answers are discarded so only work saved in time counts. Core facet
        scoring, LLM technical eval, JD synthesis, and HR email stay on
        the ARQ queue via ``enqueue_finalize_and_score_ai``.

        Args:
            session: Async database session.
            candidate: Authenticated candidate.
            assessment_id: Assessment being submitted.
            pending_responses: Optional answer payloads upserted before complete.
            client_duration_seconds: Client-measured total module time (advisory).
            completed_at: Optional completion stamp (server auto-finalize may
                pass ``expires_at``); defaults to UTC now.
            record_complete_event: When True, insert ``MODULE_COMPLETE`` in the
                same transaction as the status flip (no extra round-trip).
            request: Optional FastAPI request for session-log device headers.

        Returns:
            Tuple of (progress row, package_complete flag, company_name,
            assessment_title).

        Raises:
            AssessmentNotStartedError: Timed module was never started.
        """
        # Skip the questions JSONB bank unless we may accept pending answers.
        assessment, progress = await CandidateService.require_writable_assessment(
            session,
            candidate,
            assessment_id,
            for_update=True,
            include_questions=bool(pending_responses),
        )
        # A timed module must be armed via POST /start before it can be
        # submitted; otherwise there is no deadline and answers prepared
        # offline from GET /test would be accepted with unlimited time.
        if assessment_duration_seconds(assessment) and (
            progress is None or progress.started_at is None
        ):
            raise AssessmentNotStartedError()

        now = request_clock(session)
        accept_pending = not is_strict_expired(assessment, progress, now)
        if accept_pending and pending_responses:
            await CandidateService._upsert_pending_responses(
                session,
                candidate,
                assessment,
                pending_responses,
            )

        if not progress:
            progress = CandidateProgress(
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                assessment_id=assessment.id,
            )
            session.add(progress)

        finish_at = completed_at or now
        server_seconds: float | None = None
        if progress.started_at is not None:
            server_seconds = max(0.0, (finish_at - progress.started_at).total_seconds())

        progress.status = COMPLETED_STATUS
        progress.completed_at = finish_at
        progress.client_duration_seconds = _elapsed_decimal(client_duration_seconds)
        if server_seconds is not None:
            progress.server_duration_seconds = _elapsed_decimal(server_seconds)
            duration = assessment_duration_seconds(assessment)
            progress.overtime = bool(duration and server_seconds > duration)

        assessment_title = getattr(assessment, "title", None)
        if record_complete_event:
            # Same commit as COMPLETED — avoids a second title SELECT + commit.
            from app.services.session_log import (
                MODULE_COMPLETE,
                duration_from_progress,
                record_session_event,
            )

            await record_session_event(
                session,
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                event_type=MODULE_COMPLETE,
                assessment_id=progress.assessment_id,
                assessment_name=assessment_title,
                duration_seconds=duration_from_progress(progress),
                occurred_at=progress.completed_at,
                request=request,
                commit=False,
            )

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            # Only a duplicate progress row means a concurrent first-time
            # submit won. Any other constraint failure rolled the answers
            # back, so re-raise (503) and let the client keep its draft.
            if is_progress_unique_violation(exc):
                raise AssessmentAlreadySubmittedError() from exc
            raise

        package_complete, company_name = await CandidateService.get_submit_meta(
            session, candidate
        )
        return progress, package_complete, company_name, assessment_title

    @staticmethod
    async def _upsert_pending_responses(
        session: AsyncSession,
        candidate: Candidate,
        assessment: Assessment,
        pending_responses: list[ResponseSave],
    ) -> None:
        """Apply submit-time answers in one SELECT + batched writes.

        Args:
            session: Async database session.
            candidate: Authenticated candidate.
            assessment: Assessment being submitted.
            pending_responses: Answer payloads from the client submit body.
        """
        known_ids = question_ids(assessment)
        by_qid: dict[str, ResponseSave] = {}
        for save_data in pending_responses:
            if save_data.assessment_id != assessment.id:
                continue
            qid = str(save_data.question_id)
            if qid not in known_ids:
                logger.warning(
                    "submit_unknown_question_dropped candidate_id=%s assessment_id=%s",
                    candidate.id,
                    assessment.id,
                )
                continue
            by_qid[qid] = save_data
        if not by_qid:
            return

        existing_rows = (
            await session.execute(
                select(CandidateResponse).where(
                    CandidateResponse.candidate_id == candidate.id,
                    CandidateResponse.assessment_id == assessment.id,
                    CandidateResponse.question_id.in_(tuple(by_qid.keys())),
                )
            )
        ).scalars().all()
        existing_by_qid = {str(row.question_id): row for row in existing_rows}

        new_rows: list[CandidateResponse] = []
        for qid, save_data in by_qid.items():
            elapsed = _elapsed_decimal(save_data.elapsed_seconds)
            row = existing_by_qid.get(qid)
            if row is not None:
                row.response = save_data.response
                if elapsed is not None:
                    row.elapsed_seconds = elapsed
            else:
                new_rows.append(
                    CandidateResponse(
                        corporate_id=candidate.corporate_id,
                        candidate_id=candidate.id,
                        assessment_id=assessment.id,
                        question_id=qid,
                        response=save_data.response,
                        elapsed_seconds=elapsed,
                    )
                )
        if new_rows:
            session.add_all(new_rows)
        await session.flush()

    @staticmethod
    async def finalize_submission_scores(
        session: AsyncSession,
        candidate: Candidate,
        assessment_id: UUID,
    ) -> CandidateProgress | None:
        """Score a completed attempt and persist facets / profile / score_details.

        Safe to retry: skips when the attempt is missing or not COMPLETED.

        Args:
            session: Async database session.
            candidate: Candidate who submitted.
            assessment_id: Assessment that was submitted.

        Returns:
            Updated progress row, or None when nothing to score.
        """
        assessment = await CandidateService.get_assessment_for_candidate(
            session, candidate, assessment_id
        )
        if assessment is None:
            return None
        progress = await CandidateService._get_progress(session, candidate.id, assessment_id)
        if progress is None or progress.status != COMPLETED_STATUS:
            return None

        # Idempotent: skip when a prior finalize already wrote this version.
        if progress.scoring_version == SCORING_VERSION and progress.score_details is not None:
            return progress

        responses = (
            await session.execute(
                select(CandidateResponse).where(
                    CandidateResponse.candidate_id == candidate.id,
                    CandidateResponse.assessment_id == assessment.id,
                )
            )
        ).scalars().all()

        server_seconds: float | None = None
        if progress.server_duration_seconds is not None:
            server_seconds = float(progress.server_duration_seconds)
        elif progress.started_at is not None and progress.completed_at is not None:
            server_seconds = max(
                0.0, (progress.completed_at - progress.started_at).total_seconds()
            )

        CandidateService._apply_core_scores(
            progress, assessment, list(responses), server_seconds
        )
        await session.commit()
        await session.refresh(progress)
        return progress

    @staticmethod
    async def is_package_complete(session: AsyncSession, candidate: Candidate) -> bool:
        """True when every assessment in the candidate's package is COMPLETED."""
        package_complete, _company = await CandidateService.get_submit_meta(
            session, candidate
        )
        return package_complete

    @staticmethod
    async def get_submit_meta(
        session: AsyncSession, candidate: Candidate
    ) -> tuple[bool, str]:
        """Resolve package-complete + company name in one round trip.

        Args:
            session: Async database session.
            candidate: Candidate whose package was just submitted.

        Returns:
            ``(package_complete, company_name)``.
        """
        assessment_count = (
            select(func.count())
            .select_from(Assessment)
            .where(Assessment.package_id == candidate.package_id)
            .scalar_subquery()
        )
        completed_count = (
            select(func.count())
            .select_from(CandidateProgress)
            .where(
                CandidateProgress.candidate_id == candidate.id,
                CandidateProgress.status == COMPLETED_STATUS,
                CandidateProgress.assessment_id.in_(
                    select(Assessment.id).where(
                        Assessment.package_id == candidate.package_id
                    )
                ),
            )
            .scalar_subquery()
        )
        row = (
            await session.execute(
                select(Corporate.name, assessment_count, completed_count).where(
                    Corporate.id == candidate.corporate_id
                )
            )
        ).one_or_none()
        if row is None:
            # Corporate row missing — still compute completion without the name.
            counts = (
                await session.execute(select(assessment_count, completed_count))
            ).one()
            total, done = int(counts[0] or 0), int(counts[1] or 0)
            return (total > 0 and total == done), ""
        company, total, done = row[0] or "", int(row[1] or 0), int(row[2] or 0)
        return (total > 0 and total == done), company

    @staticmethod
    async def evaluate_technical_if_needed(
        session: AsyncSession, candidate: Candidate, assessment_id: UUID
    ) -> None:
        """Gemini-grade custom technical open-ended items after submit (background)."""
        from app.services.technical_eval import TechnicalEvalService

        assessment = await CandidateService.get_assessment_for_candidate(
            session, candidate, assessment_id
        )
        if not assessment:
            return
        await TechnicalEvalService.evaluate_assessment(
            session, candidate=candidate, assessment=assessment
        )

    @staticmethod
    async def evaluate_jd_if_package_complete(session: AsyncSession, candidate: Candidate) -> None:
        """Score JD fit when the package is fully submitted (used by background jobs)."""
        from app.services.jd_scoring import JdScoringService

        if not await CandidateService.is_package_complete(session, candidate):
            return

        assessments = (
            await session.execute(
                select(Assessment)
                .where(Assessment.package_id == candidate.package_id)
                .order_by(Assessment.position)
            )
        ).scalars().all()
        package = (
            await session.execute(select(Package).where(Package.id == candidate.package_id))
        ).scalars().first()
        progresses = (
            await session.execute(
                select(CandidateProgress).where(CandidateProgress.candidate_id == candidate.id)
            )
        ).scalars().all()
        responses = (
            await session.execute(
                select(CandidateResponse).where(CandidateResponse.candidate_id == candidate.id)
            )
        ).scalars().all()
        await JdScoringService.get_or_evaluate(
            session,
            candidate=candidate,
            package=package,
            assessments=list(assessments),
            progresses=list(progresses),
            responses=list(responses),
        )
