import logging
from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.candidate import Candidate
from app.models.package import Package
from app.models.assessment import Assessment
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.schemas.candidate import CandidateLogin
from decimal import Decimal

from app.schemas.response import ResponseSave
from app.services.runner_payload import effective_duration_seconds, strict_deadline
from app.services.profiles import ItemResult, ProfileInputs, resolve_profile
from app.services.scoring import ScoreResult, _extract_answer, score_assessment_detailed
from app.exceptions import (
    AssessmentAlreadySubmittedError,
    AssessmentNotFoundError,
    AssessmentTimeExpiredError,
)

logger = logging.getLogger(__name__)

COMPLETED_STATUS = "COMPLETED"


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


def _assessment_duration(assessment: Assessment) -> int | None:
    return effective_duration_seconds(
        getattr(assessment, "duration_seconds", None),
        getattr(assessment, "time_limit_minutes", None),
    )


def is_strict_expired(
    assessment: Assessment, progress: CandidateProgress | None, now: datetime
) -> bool:
    """Whether a strict-timer attempt is past its deadline (including grace).

    Args:
        assessment: Assessment with timer configuration.
        progress: Candidate progress (provides started_at).
        now: Current UTC time.

    Returns:
        True only for strict modules whose deadline has passed.
    """
    if (getattr(assessment, "timer_mode", None) or "flexible") != "strict":
        return False
    deadline = strict_deadline(
        getattr(progress, "started_at", None) if progress else None,
        _assessment_duration(assessment),
    )
    return deadline is not None and now > deadline


def ensure_not_submitted(progress: CandidateProgress | None) -> None:
    """Raise if this assessment is already locked after submit."""
    if progress is not None and progress.status == COMPLETED_STATUS:
        raise AssessmentAlreadySubmittedError()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateService:
    @staticmethod
    async def login(session: AsyncSession, login_data: CandidateLogin) -> tuple[Candidate, bool]:
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
                        func.lower(Candidate.access_code) == raw_code.lower()
                    )
                )
            ).scalars().first()
            if not invited:
                raise ValueError("Invalid access code")
            if invited.email.lower() != email_norm.lower():
                raise ValueError("Email does not match this invitation")
            invited.full_name = display_name
            invited.first_name = first_name
            invited.logged_in_at = _utcnow()
            await session.commit()
            await session.refresh(invited)
            return invited, False

        cand_result = await session.execute(
            select(Candidate).where(
                func.lower(Candidate.email) == email_norm.lower(),
                Candidate.package_id == package.id,
            )
        )
        candidate = cand_result.scalars().first()

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
        await session.commit()
        await session.refresh(candidate)
        return candidate, is_new

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
                )
            )
        ).scalars().first()
        if existing:
            return existing, False

        candidate = Candidate(
            corporate_id=corporate_id,
            package_id=package.id,
            full_name=display,
            email=email_norm,
            access_code=str(uuid4()),
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
        result = await session.execute(select(Candidate).where(Candidate.id == candidate_id))
        return result.scalars().first()

    @staticmethod
    async def get_dashboard(session: AsyncSession, candidate: Candidate) -> dict:
        package = (
            await session.execute(select(Package).where(Package.id == candidate.package_id))
        ).scalars().first()

        assessments = (
            await session.execute(
                select(Assessment)
                .where(Assessment.package_id == candidate.package_id)
                .order_by(Assessment.position)
            )
        ).scalars().all()

        progresses = (
            await session.execute(
                select(CandidateProgress).where(CandidateProgress.candidate_id == candidate.id)
            )
        ).scalars().all()
        status_map = {p.assessment_id: p.status for p in progresses}

        tests = [
            {
                "id": str(a.id),
                "title": a.title,
                "description": a.description,
                "status": status_map.get(a.id, "NOT_STARTED").lower(),
            }
            for a in assessments
        ]

        return {
            "package_title": package.title if package else "",
            "candidate_name": candidate.full_name,
            "tests": tests,
        }

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
        session: AsyncSession, corporate_id: UUID | None = None, package_id: UUID | None = None
    ):
        stmt = select(Candidate)
        if corporate_id:
            stmt = stmt.where(Candidate.corporate_id == corporate_id)
        if package_id:
            stmt = stmt.where(Candidate.package_id == package_id)
        candidates = (await session.execute(stmt)).scalars().all()

        tracker = []
        for cand in candidates:
            pkg = (
                await session.execute(select(Package).where(Package.id == cand.package_id))
            ).scalars().first()
            total = len(
                (
                    await session.execute(
                        select(Assessment.id).where(Assessment.package_id == cand.package_id)
                    )
                ).scalars().all()
            )
            progresses = (
                await session.execute(
                    select(CandidateProgress).where(CandidateProgress.candidate_id == cand.id)
                )
            ).scalars().all()
            completed = sum(1 for p in progresses if p.status == COMPLETED_STATUS)
            in_progress = sum(1 for p in progresses if p.status == "IN_PROGRESS")

            status = "not_started"
            if total > 0 and completed == total:
                status = "completed"
            elif completed > 0 or in_progress > 0 or cand.logged_in_at:
                status = "in_progress"

            scores = [float(p.score) for p in progresses if p.score is not None]
            cand.package_title = pkg.title if pkg else "Unknown Package"
            cand.status = status
            cand.progress = f"{completed}/{total}"
            cand.score = f"{round(sum(scores) / len(scores), 1)}%" if scores else "-"
            tracker.append(cand)
        return tracker

    @staticmethod
    async def _get_progress(
        session: AsyncSession, candidate_id: UUID, assessment_id: UUID
    ) -> CandidateProgress | None:
        return (
            await session.execute(
                select(CandidateProgress).where(
                    CandidateProgress.candidate_id == candidate_id,
                    CandidateProgress.assessment_id == assessment_id,
                )
            )
        ).scalars().first()

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
    async def require_writable_assessment(
        session: AsyncSession, candidate: Candidate, assessment_id: UUID
    ) -> tuple[Assessment, CandidateProgress | None]:
        """Assessment must belong to the candidate's package and not be submitted."""
        assessment = await CandidateService.require_assessment_in_package(
            session, candidate, assessment_id
        )
        progress = await CandidateService._get_progress(session, candidate.id, assessment_id)
        ensure_not_submitted(progress)
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
    ) -> CandidateProgress:
        """Start the attempt clock when the runner first loads the module.

        Strict timers must count from first view, not first answer, otherwise a
        candidate could read every item before the countdown begins.

        Args:
            session: Async database session.
            candidate: Authenticated candidate.
            assessment: Assessment being opened.
            progress: Existing progress row, if any.

        Returns:
            Progress row with ``started_at`` set.
        """
        if progress is not None and progress.started_at is not None:
            return progress
        if progress is None:
            progress = CandidateProgress(
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                assessment_id=assessment.id,
                status="IN_PROGRESS",
                started_at=_utcnow(),
            )
            session.add(progress)
        else:
            progress.status = "IN_PROGRESS"
            progress.started_at = _utcnow()
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
    async def autosave_response(session: AsyncSession, candidate: Candidate, save_data: ResponseSave):
        assessment, progress = await CandidateService.require_writable_assessment(
            session, candidate, save_data.assessment_id
        )
        if is_strict_expired(assessment, progress, _utcnow()):
            raise AssessmentTimeExpiredError()

        if not progress:
            progress = CandidateProgress(
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                assessment_id=assessment.id,
                status="IN_PROGRESS",
                started_at=_utcnow(),
            )
            session.add(progress)
        elif progress.status == "NOT_STARTED":
            progress.status = "IN_PROGRESS"
            progress.started_at = _utcnow()

        response = (
            await session.execute(
                select(CandidateResponse).where(
                    CandidateResponse.candidate_id == candidate.id,
                    CandidateResponse.assessment_id == assessment.id,
                    CandidateResponse.question_id == save_data.question_id,
                )
            )
        ).scalars().first()
        elapsed = _elapsed_decimal(save_data.elapsed_seconds)
        if response:
            response.response = save_data.response
            if elapsed is not None:
                response.elapsed_seconds = elapsed
        else:
            response = CandidateResponse(
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                assessment_id=assessment.id,
                question_id=save_data.question_id,
                response=save_data.response,
                elapsed_seconds=elapsed,
            )
            session.add(response)

        await session.commit()
        return response

    @staticmethod
    async def submit_test(
        session: AsyncSession,
        candidate: Candidate,
        assessment_id: UUID,
        pending_responses: list[ResponseSave] | None = None,
        client_duration_seconds: float | None = None,
    ):
        """Persist optional pending answers, score, and mark COMPLETED atomically.

        Strict modules past their deadline still finalize, but late pending
        answers are discarded so only work saved in time counts.

        Args:
            session: Async database session.
            candidate: Authenticated candidate.
            assessment_id: Assessment being submitted.
            pending_responses: Optional answer payloads upserted before scoring.
            client_duration_seconds: Client-measured total module time (advisory).

        Returns:
            Tuple of (progress row, package_complete flag).
        """
        assessment, progress = await CandidateService.require_writable_assessment(
            session, candidate, assessment_id
        )
        now = _utcnow()
        accept_pending = not is_strict_expired(assessment, progress, now)

        for save_data in (pending_responses or []) if accept_pending else []:
            if save_data.assessment_id != assessment_id:
                continue
            elapsed = _elapsed_decimal(save_data.elapsed_seconds)
            existing = (
                await session.execute(
                    select(CandidateResponse).where(
                        CandidateResponse.candidate_id == candidate.id,
                        CandidateResponse.assessment_id == assessment.id,
                        CandidateResponse.question_id == save_data.question_id,
                    )
                )
            ).scalars().first()
            if existing:
                existing.response = save_data.response
                if elapsed is not None:
                    existing.elapsed_seconds = elapsed
            else:
                session.add(
                    CandidateResponse(
                        corporate_id=candidate.corporate_id,
                        candidate_id=candidate.id,
                        assessment_id=assessment.id,
                        question_id=save_data.question_id,
                        response=save_data.response,
                        elapsed_seconds=elapsed,
                    )
                )

        await session.flush()

        responses = (
            await session.execute(
                select(CandidateResponse).where(
                    CandidateResponse.candidate_id == candidate.id,
                    CandidateResponse.assessment_id == assessment.id,
                )
            )
        ).scalars().all()

        # Score against the stored question bank (includes keys the client never sees).
        result = score_assessment_detailed(assessment.questions, responses)

        if not progress:
            progress = CandidateProgress(
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                assessment_id=assessment.id,
            )
            session.add(progress)

        server_seconds: float | None = None
        if progress.started_at is not None:
            server_seconds = max(0.0, (now - progress.started_at).total_seconds())

        progress.status = COMPLETED_STATUS
        progress.completed_at = now
        progress.score = result.score
        progress.facet_scores = result.facet_scores or None
        progress.derived_profile = derive_profile_payload(
            assessment, result, responses, server_seconds
        )
        progress.client_duration_seconds = _elapsed_decimal(client_duration_seconds)
        if server_seconds is not None:
            progress.server_duration_seconds = _elapsed_decimal(server_seconds)
            duration = _assessment_duration(assessment)
            progress.overtime = bool(duration and server_seconds > duration)

        await session.commit()
        await session.refresh(progress)
        package_complete = await CandidateService.is_package_complete(session, candidate)
        return progress, package_complete

    @staticmethod
    async def is_package_complete(session: AsyncSession, candidate: Candidate) -> bool:
        """True when every assessment in the candidate's package is COMPLETED."""
        assessments = (
            await session.execute(
                select(Assessment.id).where(Assessment.package_id == candidate.package_id)
            )
        ).scalars().all()
        if not assessments:
            return False
        progresses = (
            await session.execute(
                select(CandidateProgress).where(CandidateProgress.candidate_id == candidate.id)
            )
        ).scalars().all()
        completed_ids = {p.assessment_id for p in progresses if p.status == COMPLETED_STATUS}
        return all(aid in completed_ids for aid in assessments)

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
