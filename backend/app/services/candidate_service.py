from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.candidate import Candidate
from app.models.package import Package
from app.models.assessment import Assessment
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.schemas.candidate import CandidateLogin
from app.schemas.response import ResponseSave
from app.services.scoring import score_assessment


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateService:
    @staticmethod
    async def login(session: AsyncSession, login_data: CandidateLogin) -> Candidate:
        pkg_result = await session.execute(
            select(Package).where(
                Package.access_code == login_data.access_code,
                Package.is_active.is_(True),
            )
        )
        package = pkg_result.scalars().first()
        if not package:
            raise ValueError("Invalid access code")

        cand_result = await session.execute(
            select(Candidate).where(
                Candidate.email == login_data.email,
                Candidate.package_id == package.id,
            )
        )
        candidate = cand_result.scalars().first()

        display_name = (login_data.full_name or "").strip() or login_data.email.split("@")[0]

        if not candidate:
            candidate = Candidate(
                corporate_id=package.corporate_id,
                package_id=package.id,
                full_name=display_name,
                email=login_data.email,
                access_code=login_data.access_code,
            )
            session.add(candidate)
        elif display_name:
            candidate.full_name = display_name

        candidate.logged_in_at = _utcnow()
        await session.commit()
        await session.refresh(candidate)
        return candidate

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
            completed = sum(1 for p in progresses if p.status == "COMPLETED")
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
    async def autosave_response(session: AsyncSession, candidate: Candidate, save_data: ResponseSave):
        progress = (
            await session.execute(
                select(CandidateProgress).where(
                    CandidateProgress.candidate_id == candidate.id,
                    CandidateProgress.assessment_id == save_data.assessment_id,
                )
            )
        ).scalars().first()
        if not progress:
            progress = CandidateProgress(
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                assessment_id=save_data.assessment_id,
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
                    CandidateResponse.assessment_id == save_data.assessment_id,
                    CandidateResponse.question_id == save_data.question_id,
                )
            )
        ).scalars().first()
        if response:
            response.response = save_data.response
        else:
            response = CandidateResponse(
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                assessment_id=save_data.assessment_id,
                question_id=save_data.question_id,
                response=save_data.response,
            )
            session.add(response)

        await session.commit()
        return response

    @staticmethod
    async def submit_test(session: AsyncSession, candidate: Candidate, assessment_id: UUID):
        assessment = await CandidateService.get_assessment_for_candidate(session, candidate, assessment_id)
        if not assessment:
            raise ValueError("Assessment not found for candidate")

        responses = (
            await session.execute(
                select(CandidateResponse).where(
                    CandidateResponse.candidate_id == candidate.id,
                    CandidateResponse.assessment_id == assessment_id,
                )
            )
        ).scalars().all()

        score = score_assessment(assessment.questions, responses)

        progress = (
            await session.execute(
                select(CandidateProgress).where(
                    CandidateProgress.candidate_id == candidate.id,
                    CandidateProgress.assessment_id == assessment_id,
                )
            )
        ).scalars().first()
        if not progress:
            progress = CandidateProgress(
                corporate_id=candidate.corporate_id,
                candidate_id=candidate.id,
                assessment_id=assessment_id,
            )
            session.add(progress)

        progress.status = "COMPLETED"
        progress.completed_at = _utcnow()
        progress.score = score

        await session.commit()
        await session.refresh(progress)
        return progress
