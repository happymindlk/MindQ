"""Client-package cart: draft persistence, publish snapshots, HR masking."""
from __future__ import annotations

import copy
import re
import secrets
import unicodedata
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_evaluation import CandidateEvaluation
from app.models.candidate_progress import CandidateProgress
from app.models.corporate import Corporate
from app.models.custom_technical_question import CustomTechnicalQuestion
from app.models.global_module import GlobalModule
from app.models.package import Package
from app.models.package_module import PackageModule
from app.schemas.client_package import (
    AdminPackageDetail,
    AdminPackageModule,
    AdminPackageUpdateRequest,
    BlindReviewResponse,
    ClientCandidateStatus,
    ClientCorporate,
    ClientDashboardCandidate,
    ClientDashboardPackage,
    ClientDashboardResponse,
    ClientScorecardAssessment,
    ClientScorecardResponse,
    ClientPipelineRow,
    CompanyCreateRequest,
    CompanyCreateResponse,
    CompanyUpdateRequest,
    CustomQuestionIn,
    CustomQuestionOut,
    DraftPackageRequest,
    DraftPackageResponse,
    GlobalModuleResponse,
    PackagePreviewRequest,
    PackageScheduleResponse,
    PackageScheduleUpdate,
    PublishPackageResponse,
    ReviewQuestion,
)
from app.schemas.candidate import CandidateTestResponse
from app.schemas.package_builder import QuestionItem, QuestionType
from app.services.jd_scoring import evaluation_is_ok
from app.services.runner_payload import build_runner_payload
from app.services.package_generator import (
    _mint_access_code,
    blueprint_question_to_storage,
)

PSYCHOMETRIC = "psychometric"
TECHNICAL = "technical"
ANSWER_KEYS = (
    "correct_answer",
    "correct_answer_or_rubric",
    "benchmark_rubric",
    "answer",
    "scoring_key",
    "correct_keys",
    "option_weights",
    "accepted_answers",
    "reverse_scored",
    "sme_rationale",
)


class ClientPackageError(Exception):
    """Domain error for draft/publish operations."""


class PackageLockedError(ClientPackageError):
    """Raised when a published package is mutated."""

    def __init__(self, message: str = "Published packages are locked and cannot be modified."):
        super().__init__(message)


def slugify_company_name(name: str) -> str:
    """Build a URL-safe slug from a company name.

    Args:
        name: Display name entered by ops.

    Returns:
        Lowercase hyphenated slug with non-alphanumerics stripped.
    """
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "company"


def _company_response(corporate: Corporate) -> CompanyCreateResponse:
    """Serialize a corporates row for ops company endpoints.

    Args:
        corporate: Loaded ORM row.

    Returns:
        API response model.
    """
    return CompanyCreateResponse(
        id=corporate.id,
        name=corporate.name,
        slug=corporate.slug,
        contact_email=corporate.contact_email,
        logo_url=corporate.logo_url,
        created_at=corporate.created_at,
    )


async def _get_corporate_or_raise(session: AsyncSession, company_id: UUID) -> Corporate:
    """Load a corporate by id.

    Args:
        session: Async database session.
        company_id: Target corporate UUID.

    Returns:
        The corporates row.

    Raises:
        LookupError: No corporate exists with ``company_id``.
    """
    corporate = (
        await session.execute(select(Corporate).where(Corporate.id == company_id))
    ).scalar_one_or_none()
    if corporate is None:
        raise LookupError("Company not found")
    return corporate


def _review_token() -> str:
    return secrets.token_urlsafe(24)


def _strip_answer_keys(question: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a stored question without scoring keys.

    Args:
        question: Portal-shaped question dict from JSONB.

    Returns:
        Sanitized dict safe to send to HR review/scorecard clients.
    """
    cleaned = copy.deepcopy(question) if isinstance(question, dict) else {}
    for key in ANSWER_KEYS:
        cleaned.pop(key, None)
    return cleaned


def public_review_questions(
    custom_questions: list[CustomTechnicalQuestion],
    assessments: list[Assessment],
) -> list[ReviewQuestion]:
    """Build the blind-review item list: technical only, keys stripped.

    Psychometric assessments are dropped entirely. Custom technical questions
    are preferred (source of truth on drafts); published snapshots in
    ``module_kind=technical`` assessments are included when custom rows are
    empty so already-published packs still render.

    Args:
        custom_questions: Ops-authored items for the package.
        assessments: Snapshot rows created at publish time.

    Returns:
        Ordered review questions with scoring keys removed.
    """
    items: list[ReviewQuestion] = []

    for row in sorted(custom_questions, key=lambda q: q.position):
        options = row.options if isinstance(row.options, list) else []
        items.append(
            ReviewQuestion(
                id=str(row.id),
                prompt=row.prompt,
                question_type=row.question_type,
                options=[str(o) for o in options],
                evaluated_competency=row.evaluated_competency,
                likert_label_1=row.likert_label_1,
                likert_label_5=row.likert_label_5,
            )
        )

    if items:
        return items

    for assessment in sorted(assessments, key=lambda a: a.position):
        if (assessment.module_kind or TECHNICAL) == PSYCHOMETRIC:
            continue
        for raw in assessment.questions or []:
            if not isinstance(raw, dict):
                continue
            cleaned = _strip_answer_keys(raw)
            qtype = str(cleaned.get("builder_type") or cleaned.get("type") or "mcq")
            items.append(
                ReviewQuestion(
                    id=str(cleaned.get("id") or ""),
                    prompt=str(cleaned.get("text") or cleaned.get("prompt") or ""),
                    question_type=qtype,
                    options=[str(o) for o in (cleaned.get("options") or [])],
                    evaluated_competency=cleaned.get("evaluated_competency"),
                    likert_label_1=cleaned.get("likert_label_1"),
                    likert_label_5=cleaned.get("likert_label_5"),
                )
            )
    return items


def _custom_to_storage(item: CustomTechnicalQuestion | CustomQuestionIn, index: int) -> dict:
    """Map a custom technical row into assessments.questions JSONB.

    Args:
        item: Persisted or inbound custom question.
        index: Zero-based position for stable ids.

    Returns:
        Portal-compatible question dict.
    """
    qtype = item.question_type
    if not isinstance(qtype, QuestionType):
        qtype = QuestionType(str(qtype))
    mapped = QuestionItem(
        prompt=item.prompt,
        question_type=qtype,
        options=list(item.options or []),
        correct_answer_or_rubric=item.correct_answer_or_rubric or "",
        evaluated_competency=item.evaluated_competency or "Technical",
        weight=int(item.weight or 3),
        likert_label_1=item.likert_label_1 or "Strongly Disagree",
        likert_label_5=item.likert_label_5 or "Strongly Agree",
    )
    return blueprint_question_to_storage(mapped, index)


def _to_custom_out(row: CustomTechnicalQuestion) -> CustomQuestionOut:
    return CustomQuestionOut(
        id=row.id,
        prompt=row.prompt,
        question_type=QuestionType(row.question_type),
        options=list(row.options or []),
        correct_answer_or_rubric=row.correct_answer_or_rubric or "",
        evaluated_competency=row.evaluated_competency,
        weight=row.weight,
        likert_label_1=row.likert_label_1,
        likert_label_5=row.likert_label_5,
        position=row.position,
    )


def _draft_response(
    package: Package,
    module_ids: list[UUID],
    custom_rows: list[CustomTechnicalQuestion],
    *,
    published: bool = False,
) -> DraftPackageResponse:
    review_token = package.review_token
    access = package.access_code if published else None
    return DraftPackageResponse(
        id=package.id,
        corporate_id=package.corporate_id,
        title=package.title,
        description=package.description,
        target_role=package.target_role,
        passing_threshold=float(package.passing_threshold)
        if package.passing_threshold is not None
        else None,
        status=package.status if package.status in ("draft", "published") else "draft",
        is_active=bool(package.is_active),
        access_code=access,
        review_token=review_token if published else None,
        review_path=f"/client/review/{review_token}" if published and review_token else None,
        track_secret=package.track_secret if published else None,
        published_at=package.published_at,
        open_time=package.open_time,
        close_time=package.close_time,
        module_ids=module_ids,
        custom_questions=[_to_custom_out(r) for r in custom_rows],
        module_count=len(module_ids),
        custom_question_count=len(custom_rows),
    )


def _lineage_key(module: GlobalModule) -> UUID:
    return module.lineage_id or module.id


def newest_by_lineage(candidates: list[GlobalModule]) -> dict[UUID, GlobalModule]:
    """Pick the highest-version row per lineage.

    Args:
        candidates: Published, active module rows (any lineage mix).

    Returns:
        Lineage id -> newest module row.
    """
    newest: dict[UUID, GlobalModule] = {}
    for row in candidates:
        key = _lineage_key(row)
        current = newest.get(key)
        if current is None or (row.version or 1) > (current.version or 1):
            newest[key] = row
    return newest


def resolve_cart_row(
    pinned: GlobalModule,
    latest: GlobalModule,
    link_questions: list[dict[str, Any]] | None,
) -> tuple[GlobalModule, list[dict[str, Any]]]:
    """Choose the module version and question snapshot a draft cart row should use.

    "Clone as New Version" creates a new lineage row instead of mutating the
    published one, so a draft suite pinned to v1 would otherwise keep v1's
    duration forever. Drafts follow the newest published version; the eager
    question snapshot follows too unless ops customised it for this suite.

    Args:
        pinned: Module row the cart currently references.
        latest: Newest published row on the same lineage (may be ``pinned``).
        link_questions: Stored per-package snapshot, or None if never snapshotted.

    Returns:
        ``(module_to_use, questions)`` where questions is a deep copy.
    """
    pinned_qs = pinned.questions if isinstance(pinned.questions, list) else []
    if latest.id == pinned.id:
        source = link_questions if link_questions is not None else pinned_qs
        return pinned, copy.deepcopy(source)
    if link_questions is None or link_questions == pinned_qs:
        latest_qs = latest.questions if isinstance(latest.questions, list) else []
        return latest, copy.deepcopy(latest_qs)
    return latest, copy.deepcopy(link_questions)


async def _latest_published_for(
    session: AsyncSession, modules: list[GlobalModule]
) -> dict[UUID, GlobalModule]:
    """Map each pinned module id to the newest published version of its lineage.

    Args:
        session: Async database session.
        modules: Module rows referenced by a package cart.

    Returns:
        Pinned module id -> module to use (itself when already newest).
    """
    if not modules:
        return {}
    lineages = {_lineage_key(m) for m in modules}
    rows = (
        await session.execute(
            select(GlobalModule).where(
                func.coalesce(GlobalModule.lineage_id, GlobalModule.id).in_(lineages),
                GlobalModule.status == "published",
                GlobalModule.is_active.is_(True),
            )
        )
    ).scalars().all()
    newest = newest_by_lineage(list(rows))
    resolved: dict[UUID, GlobalModule] = {}
    for module in modules:
        candidate = newest.get(_lineage_key(module))
        if candidate is not None and (candidate.version or 1) > (module.version or 1):
            resolved[module.id] = candidate
        else:
            resolved[module.id] = module
    return resolved


def pipeline_status(
    *,
    completed: int,
    total: int,
    logged_in: bool,
    jd_fit: float | None,
) -> str:
    """Map progress counts to Pending / Scoring / Completed.

    Args:
        completed: Completed assessment count.
        total: Assessments in the package.
        logged_in: Whether the candidate has entered the portal.
        jd_fit: Cached Gemini overall fit, if any.

    Returns:
        One of ``pending``, ``scoring``, ``completed``.
    """
    if total > 0 and completed >= total:
        return "completed" if jd_fit is not None else "scoring"
    if completed > 0 or logged_in:
        return "scoring"
    return "pending"


def client_status(*, completed: int, total: int, logged_in: bool) -> ClientCandidateStatus:
    """Map progress counts to the HR-facing Invited / In Progress / Completed.

    Unlike ``pipeline_status`` this does not wait for the Gemini JD-fit score:
    HR sees Completed as soon as every assessment is submitted.

    Args:
        completed: Completed assessment count.
        total: Assessments in the package (0 for an empty package).
        logged_in: Whether the candidate has entered the portal.

    Returns:
        One of ``invited``, ``in_progress``, ``completed``.
    """
    if total > 0 and completed >= total:
        return "completed"
    if completed > 0 or logged_in:
        return "in_progress"
    return "invited"


@dataclass(frozen=True)
class CandidateAggregates:
    """Batched per-candidate progress metrics (one query per metric, no N+1)."""

    assessment_counts: dict[UUID, int] = dc_field(default_factory=dict)
    completed: dict[UUID, int] = dc_field(default_factory=dict)
    avg_score: dict[UUID, float | None] = dc_field(default_factory=dict)
    completed_at: dict[UUID, datetime | None] = dc_field(default_factory=dict)
    fit: dict[UUID, float | None] = dc_field(default_factory=dict)

    def total_for(self, candidate: Candidate) -> int:
        """Assessment count of the candidate's package.

        Args:
            candidate: Candidate row.

        Returns:
            Number of assessments in ``candidate.package_id``.
        """
        return int(self.assessment_counts.get(candidate.package_id, 0) or 0)


async def _candidate_aggregates(
    session: AsyncSession,
    candidates: list[Candidate],
    package_ids: list[UUID] | None = None,
) -> CandidateAggregates:
    """Load progress counts, technical average, completion time, and JD fit.

    Args:
        session: Async database session.
        candidates: Already tenant-filtered candidate rows.
        package_ids: Packages to count assessments for; defaults to the
            candidates' packages.

    Returns:
        Aggregates keyed by candidate id (or package id for assessment counts).
    """
    pkg_ids = set(package_ids or []) | {c.package_id for c in candidates}
    assessment_counts: dict[UUID, int] = {}
    if pkg_ids:
        assessment_counts = {
            pid: int(n)
            for pid, n in (
                await session.execute(
                    select(Assessment.package_id, func.count(Assessment.id))
                    .where(Assessment.package_id.in_(pkg_ids))
                    .group_by(Assessment.package_id)
                )
            ).all()
        }
    if not candidates:
        return CandidateAggregates(assessment_counts=assessment_counts)

    candidate_ids = [c.id for c in candidates]
    completed = {
        cid: int(n)
        for cid, n in (
            await session.execute(
                select(CandidateProgress.candidate_id, func.count(CandidateProgress.id))
                .where(
                    CandidateProgress.candidate_id.in_(candidate_ids),
                    CandidateProgress.status == "COMPLETED",
                )
                .group_by(CandidateProgress.candidate_id)
            )
        ).all()
    }

    avg_score = {
        cid: float(avg) if avg is not None else None
        for cid, avg in (
            await session.execute(
                select(
                    CandidateProgress.candidate_id,
                    func.round(func.avg(CandidateProgress.score), 1),
                )
                .join(Assessment, Assessment.id == CandidateProgress.assessment_id)
                .where(
                    CandidateProgress.candidate_id.in_(candidate_ids),
                    CandidateProgress.score.is_not(None),
                    func.coalesce(Assessment.module_kind, TECHNICAL) == TECHNICAL,
                )
                .group_by(CandidateProgress.candidate_id)
            )
        ).all()
    }

    completed_at = {
        cid: ts
        for cid, ts in (
            await session.execute(
                select(
                    CandidateProgress.candidate_id,
                    func.max(CandidateProgress.completed_at),
                )
                .where(
                    CandidateProgress.candidate_id.in_(candidate_ids),
                    CandidateProgress.status == "COMPLETED",
                )
                .group_by(CandidateProgress.candidate_id)
            )
        ).all()
    }

    evals = (
        await session.execute(
            select(CandidateEvaluation).where(
                CandidateEvaluation.candidate_id.in_(candidate_ids)
            )
        )
    ).scalars().all()
    fit = {
        e.candidate_id: float(e.overall_fit) if e.overall_fit is not None else None
        for e in evals
    }

    return CandidateAggregates(
        assessment_counts=assessment_counts,
        completed=completed,
        avg_score=avg_score,
        completed_at=completed_at,
        fit=fit,
    )


class ClientPackageService:
    """Draft/publish lifecycle for managed-service client packages."""

    @staticmethod
    async def list_modules(session: AsyncSession) -> list[GlobalModuleResponse]:
        """Return the latest published version of each active module lineage.

        Drafts and archived modules never reach the composer, so a package can
        only snapshot immutable, published question banks.

        Args:
            session: Async database session.

        Returns:
            Catalog rows sorted by kind then position.
        """
        result = await session.execute(
            select(GlobalModule)
            .where(
                GlobalModule.is_active.is_(True),
                GlobalModule.status == "published",
            )
            .order_by(GlobalModule.module_kind, GlobalModule.position, GlobalModule.title)
        )
        rows = result.scalars().all()
        latest: dict[UUID, GlobalModule] = {}
        for row in rows:
            lineage = getattr(row, "lineage_id", None) or row.id
            current = latest.get(lineage)
            if current is None or int(getattr(row, "version", 1) or 1) > int(
                getattr(current, "version", 1) or 1
            ):
                latest[lineage] = row
        keep = {id(r) for r in latest.values()}

        out: list[GlobalModuleResponse] = []
        for row in rows:
            if id(row) not in keep:
                continue
            questions = row.questions if isinstance(row.questions, list) else []
            facets = {
                str(q.get("facet") or q.get("evaluated_competency") or "").strip()
                for q in questions
                if isinstance(q, dict)
            }
            facets.discard("")
            # Ops builder needs full payloads for temporary psychometric edits.
            out.append(
                GlobalModuleResponse(
                    id=row.id,
                    slug=row.slug,
                    title=row.title,
                    description=row.description,
                    module_kind=row.module_kind,  # type: ignore[arg-type]
                    assessment_category=getattr(row, "assessment_category", None),
                    time_limit_minutes=row.time_limit_minutes,
                    duration_seconds=getattr(row, "duration_seconds", None),
                    timer_mode=getattr(row, "timer_mode", None) or "flexible",
                    shuffle_questions=bool(getattr(row, "shuffle_questions", False)),
                    status=getattr(row, "status", None) or "published",
                    version=int(getattr(row, "version", 1) or 1),
                    lineage_id=getattr(row, "lineage_id", None),
                    question_count=len(questions),
                    facet_count=len(facets),
                    position=row.position,
                    is_active=row.is_active,
                    questions=copy.deepcopy(questions),
                )
            )
        return out

    @staticmethod
    async def preview(
        session: AsyncSession, body: PackagePreviewRequest
    ) -> list[CandidateTestResponse]:
        """Build sanitized runner payloads for an unsaved module sequence.

        Draft modules are allowed so admins can preview a version before
        publishing; archived modules are rejected.

        Args:
            session: Async database session.
            body: Ordered module ids plus optional per-module question overrides.

        Returns:
            One candidate-shaped test payload per module, in composer order.

        Raises:
            ClientPackageError: A module is missing or archived.
        """
        ordered: list[UUID] = list(dict.fromkeys(body.module_ids))
        rows = (
            await session.execute(
                select(GlobalModule).where(
                    GlobalModule.id.in_(ordered),
                    GlobalModule.is_active.is_(True),
                )
            )
        ).scalars().all()
        by_id = {r.id: r for r in rows}
        if len(by_id) != len(ordered):
            raise ClientPackageError("One or more modules are missing or archived")

        overrides = body.module_question_overrides or {}
        out: list[CandidateTestResponse] = []
        for mid in ordered:
            module = by_id[mid]
            override = overrides.get(str(mid))
            questions = override if isinstance(override, list) else (module.questions or [])
            out.append(
                build_runner_payload(
                    assessment_id=module.id,
                    title=module.title,
                    description=module.description,
                    questions=questions,
                    time_limit_minutes=module.time_limit_minutes,
                    duration_seconds=getattr(module, "duration_seconds", None),
                    timer_mode=getattr(module, "timer_mode", None),
                    shuffle=bool(getattr(module, "shuffle_questions", False)),
                    seed=f"preview:{module.id}",
                )
            )
        return out

    @staticmethod
    async def _load_cart(
        session: AsyncSession, package_id: UUID
    ) -> tuple[list[UUID], list[CustomTechnicalQuestion]]:
        mods = (
            await session.execute(
                select(PackageModule)
                .where(PackageModule.package_id == package_id)
                .order_by(PackageModule.position)
            )
        ).scalars().all()
        custom = (
            await session.execute(
                select(CustomTechnicalQuestion)
                .where(CustomTechnicalQuestion.package_id == package_id)
                .order_by(CustomTechnicalQuestion.position)
            )
        ).scalars().all()
        return [m.global_module_id for m in mods], list(custom)

    @staticmethod
    async def get_draft(session: AsyncSession, package_id: UUID) -> DraftPackageResponse:
        """Load a package cart for the builder.

        Args:
            session: Async database session.
            package_id: Client package id.

        Returns:
            Draft payload including selected modules and custom items.

        Raises:
            LookupError: Package does not exist.
        """
        package = (
            await session.execute(select(Package).where(Package.id == package_id))
        ).scalar_one_or_none()
        if not package:
            raise LookupError("Package not found")
        module_ids, custom_rows = await ClientPackageService._load_cart(session, package_id)
        published = package.status == "published"
        return _draft_response(package, module_ids, custom_rows, published=published)

    @staticmethod
    async def create_company(
        session: AsyncSession, body: CompanyCreateRequest
    ) -> CompanyCreateResponse:
        """Insert a corporates row for the ops company picker.

        Args:
            session: Async database session.
            body: Display name and optional slug.

        Returns:
            Inserted company id, name, slug, and created_at.

        Raises:
            ClientPackageError: Slug collides after suffix attempts.
        """
        base = slugify_company_name(body.slug or body.name)
        slug = base
        for suffix in range(2, 60):
            taken = (
                await session.execute(select(Corporate.id).where(Corporate.slug == slug))
            ).scalar_one_or_none()
            if taken is None:
                break
            slug = f"{base}-{suffix}"
        else:
            raise ClientPackageError("Could not allocate a unique company slug")

        corporate = Corporate(name=body.name, slug=slug, contact_email=body.contact_email)
        session.add(corporate)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ClientPackageError("Company slug already exists") from exc
        await session.refresh(corporate)
        return _company_response(corporate)

    @staticmethod
    async def update_company(
        session: AsyncSession, company_id: UUID, body: CompanyUpdateRequest
    ) -> CompanyCreateResponse:
        """Apply a partial update to a corporates row.

        Args:
            session: Async database session.
            company_id: Target corporate UUID.
            body: Fields to change; unset fields are left untouched.

        Returns:
            The updated company.

        Raises:
            LookupError: No corporate exists with ``company_id``.
        """
        corporate = await _get_corporate_or_raise(session, company_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(corporate, field, value)
        await session.commit()
        await session.refresh(corporate)
        return _company_response(corporate)

    @staticmethod
    async def set_company_logo(
        session: AsyncSession, company_id: UUID, logo_url: str
    ) -> CompanyCreateResponse:
        """Persist a public logo URL on a corporates row.

        Args:
            session: Async database session.
            company_id: Target corporate UUID.
            logo_url: Public object URL returned by storage.

        Returns:
            The updated company.

        Raises:
            LookupError: No corporate exists with ``company_id``.
        """
        corporate = await _get_corporate_or_raise(session, company_id)
        corporate.logo_url = logo_url
        await session.commit()
        await session.refresh(corporate)
        return _company_response(corporate)

    @staticmethod
    async def get_admin_package(
        session: AsyncSession, package_id: UUID
    ) -> AdminPackageDetail:
        """Load one package with module associations and custom questions.

        Args:
            session: Async database session.
            package_id: Client package id.

        Returns:
            Package metadata plus ordered modules and custom items.

        Raises:
            LookupError: Package does not exist.
        """
        package = (
            await session.execute(select(Package).where(Package.id == package_id))
        ).scalar_one_or_none()
        if not package:
            raise LookupError("Package not found")

        join_rows = (
            await session.execute(
                select(PackageModule, GlobalModule)
                .join(GlobalModule, GlobalModule.id == PackageModule.global_module_id)
                .where(PackageModule.package_id == package_id)
                .order_by(PackageModule.position)
            )
        ).all()
        custom_rows = (
            await session.execute(
                select(CustomTechnicalQuestion)
                .where(CustomTechnicalQuestion.package_id == package_id)
                .order_by(CustomTechnicalQuestion.position)
            )
        ).scalars().all()

        published = package.status == "published"
        # Published suites are historical; only drafts follow newer module versions.
        latest_by_pinned = (
            {}
            if published
            else await _latest_published_for(session, [catalog for _link, catalog in join_rows])
        )

        modules: list[AdminPackageModule] = []
        seen_ids: set[UUID] = set()
        for link, pinned in join_rows:
            override = link.questions if isinstance(link.questions, list) else None
            catalog, questions = resolve_cart_row(
                pinned, latest_by_pinned.get(pinned.id, pinned), override
            )
            if catalog.id in seen_ids:
                continue
            seen_ids.add(catalog.id)
            modules.append(
                AdminPackageModule(
                    module_id=catalog.id,
                    sort_order=link.position,
                    slug=catalog.slug,
                    title=catalog.title,
                    description=catalog.description,
                    module_kind=catalog.module_kind,  # type: ignore[arg-type]
                    time_limit_minutes=catalog.time_limit_minutes,
                    duration_seconds=catalog.duration_seconds,
                    timer_mode=catalog.timer_mode or "flexible",  # type: ignore[arg-type]
                    version=catalog.version or 1,
                    upgraded_from_version=(pinned.version or 1) if catalog.id != pinned.id else None,
                    question_count=len(questions),
                    is_active=catalog.is_active,
                    questions=questions,
                )
            )

        threshold = (
            float(package.passing_threshold)
            if package.passing_threshold is not None
            else None
        )
        return AdminPackageDetail(
            id=package.id,
            corporate_id=package.corporate_id,
            title=package.title,
            target_role=package.target_role,
            passing_threshold=threshold,
            status="published" if published else "draft",
            review_token=package.review_token,
            description=package.description,
            is_active=bool(package.is_active),
            access_code=package.access_code if published else None,
            open_time=package.open_time,
            close_time=package.close_time,
            modules=modules,
            custom_questions=[_to_custom_out(row) for row in custom_rows],
        )

    @staticmethod
    async def update_admin_package(
        session: AsyncSession, package_id: UUID, body: AdminPackageUpdateRequest
    ) -> AdminPackageDetail:
        """Atomically update a draft package. Published rows are rejected.

        Args:
            session: Async database session.
            package_id: Target package id.
            body: Metadata, module ids, and optional custom questions.

        Returns:
            Updated package detail.

        Raises:
            LookupError: Package or company missing.
            PackageLockedError: Package is published.
            ClientPackageError: Invalid module selection.
        """
        package = (
            await session.execute(select(Package).where(Package.id == package_id))
        ).scalar_one_or_none()
        if not package:
            raise LookupError("Package not found")
        if package.status == "published":
            raise PackageLockedError(
                "Published packages are locked and cannot be modified."
            )

        corporate_id = body.corporate_id or package.corporate_id
        if body.custom_questions is None:
            _ids, existing_custom = await ClientPackageService._load_cart(
                session, package_id
            )
            custom_payload = [
                CustomQuestionIn(
                    id=row.id,
                    prompt=row.prompt,
                    question_type=QuestionType(row.question_type),
                    options=list(row.options or []),
                    correct_answer_or_rubric=row.correct_answer_or_rubric or "",
                    evaluated_competency=row.evaluated_competency,
                    weight=row.weight,
                    likert_label_1=row.likert_label_1,
                    likert_label_5=row.likert_label_5,
                )
                for row in existing_custom
            ]
        else:
            custom_payload = list(body.custom_questions)

        sent = body.model_fields_set
        draft = DraftPackageRequest(
            corporate_id=corporate_id,
            title=body.title,
            description=body.description
            if body.description is not None
            else (package.description or ""),
            target_role=body.target_role,
            passing_threshold=body.passing_threshold,
            module_ids=body.module_ids,
            custom_questions=custom_payload,
            module_question_overrides=body.module_question_overrides,
            open_time=body.open_time if "open_time" in sent else package.open_time,
            close_time=body.close_time if "close_time" in sent else package.close_time,
        )
        await ClientPackageService.save_draft(session, draft, package_id=package_id)
        return await ClientPackageService.get_admin_package(session, package_id)

    @staticmethod
    async def update_schedule(
        session: AsyncSession, package_id: UUID, body: PackageScheduleUpdate
    ) -> PackageScheduleResponse:
        """Change a package's deadline. Allowed on live suites, unlike content edits.

        Args:
            session: Async database session.
            package_id: Target package id.
            body: New ``close_time`` (None removes the deadline).

        Returns:
            The package window after the change.

        Raises:
            LookupError: Package does not exist.
            ClientPackageError: Deadline is not after the open time.
        """
        package = (
            await session.execute(select(Package).where(Package.id == package_id))
        ).scalar_one_or_none()
        if not package:
            raise LookupError("Package not found")
        if (
            body.close_time is not None
            and package.open_time is not None
            and body.close_time <= package.open_time
        ):
            raise ClientPackageError("Deadline must be after the package open time")

        package.close_time = body.close_time
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        await session.refresh(package)
        return PackageScheduleResponse(
            id=package.id, open_time=package.open_time, close_time=package.close_time
        )

    @staticmethod
    async def save_draft(
        session: AsyncSession, body: DraftPackageRequest, package_id: UUID | None = None
    ) -> DraftPackageResponse:
        """Create or replace a draft cart. Published packages cannot be edited.

        Args:
            session: Async database session.
            body: Target company, title, selected modules, custom items.
            package_id: Existing draft id, or None to create.

        Returns:
            Persisted draft with server ids.

        Raises:
            LookupError: Corporate or package missing.
            PackageLockedError: Package is already published.
            ClientPackageError: Selected module ids are invalid.
        """
        corporate = (
            await session.execute(select(Corporate).where(Corporate.id == body.corporate_id))
        ).scalar_one_or_none()
        if not corporate:
            raise LookupError("Company not found")

        package: Package | None = None
        if package_id:
            package = (
                await session.execute(select(Package).where(Package.id == package_id))
            ).scalar_one_or_none()
            if not package:
                raise LookupError("Package not found")
            if package.status == "published":
                raise PackageLockedError("Published packages are locked")

        unique_module_ids: list[UUID] = []
        seen: set[UUID] = set()
        for mid in body.module_ids:
            if mid in seen:
                continue
            seen.add(mid)
            unique_module_ids.append(mid)

        if unique_module_ids:
            found = (
                await session.execute(
                    select(GlobalModule.id).where(
                        GlobalModule.id.in_(unique_module_ids),
                        GlobalModule.is_active.is_(True),
                        GlobalModule.status == "published",
                    )
                )
            ).scalars().all()
            if set(found) != set(unique_module_ids):
                raise ClientPackageError("One or more modules are invalid")

        if package is None:
            access_code = _mint_access_code()
            for _ in range(8):
                exists = (
                    await session.execute(
                        select(Package.id).where(Package.access_code == access_code)
                    )
                ).scalar_one_or_none()
                if exists is None:
                    break
                access_code = _mint_access_code()
            package = Package(
                corporate_id=body.corporate_id,
                title=body.title,
                description=body.description.strip() or None,
                target_role=(body.target_role or "").strip() or None,
                passing_threshold=body.passing_threshold,
                access_code=access_code,
                status="draft",
                is_active=False,
                review_token=_review_token(),
                open_time=body.open_time,
                close_time=body.close_time,
            )
            session.add(package)
            await session.flush()
        else:
            package.corporate_id = body.corporate_id
            package.title = body.title
            package.description = body.description.strip() or None
            package.target_role = (body.target_role or "").strip() or None
            package.passing_threshold = body.passing_threshold
            if "open_time" in body.model_fields_set:
                package.open_time = body.open_time
            if "close_time" in body.model_fields_set:
                package.close_time = body.close_time
            if (
                package.open_time is not None
                and package.close_time is not None
                and package.close_time <= package.open_time
            ):
                raise ClientPackageError("Close time must be after open time")
            if not package.review_token:
                package.review_token = _review_token()

        await session.execute(
            delete(PackageModule).where(PackageModule.package_id == package.id)
        )
        await session.execute(
            delete(CustomTechnicalQuestion).where(
                CustomTechnicalQuestion.package_id == package.id
            )
        )

        overrides = body.module_question_overrides or {}
        # Eager snapshot: always persist a JSONB copy so later master-library
        # edits cannot leak into historical/in-progress package drafts.
        catalog_by_id: dict[UUID, list] = {}
        missing_ids = [
            mid
            for mid in unique_module_ids
            if not isinstance(overrides.get(str(mid)), list)
        ]
        if missing_ids:
            catalog_rows = (
                await session.execute(
                    select(GlobalModule).where(GlobalModule.id.in_(missing_ids))
                )
            ).scalars().all()
            for row in catalog_rows:
                catalog_by_id[row.id] = (
                    copy.deepcopy(row.questions)
                    if isinstance(row.questions, list)
                    else []
                )

        for index, mid in enumerate(unique_module_ids):
            override_qs = overrides.get(str(mid))
            if isinstance(override_qs, list):
                snapshot = copy.deepcopy(override_qs)
            else:
                snapshot = catalog_by_id.get(mid, [])
            session.add(
                PackageModule(
                    package_id=package.id,
                    global_module_id=mid,
                    position=index,
                    questions=snapshot,
                )
            )

        custom_rows: list[CustomTechnicalQuestion] = []
        for item in body.custom_questions:
            if not item.prompt.strip():
                continue
            row = CustomTechnicalQuestion(
                id=item.id or uuid4(),
                package_id=package.id,
                corporate_id=body.corporate_id,
                prompt=item.prompt.strip(),
                question_type=item.question_type.value
                if isinstance(item.question_type, QuestionType)
                else str(item.question_type),
                options=list(item.options or []),
                correct_answer_or_rubric=item.correct_answer_or_rubric or "",
                evaluated_competency=(item.evaluated_competency or "Technical").strip()
                or "Technical",
                weight=item.weight,
                likert_label_1=item.likert_label_1,
                likert_label_5=item.likert_label_5,
                position=len(custom_rows),
            )
            session.add(row)
            custom_rows.append(row)

        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        await session.refresh(package)
        return _draft_response(package, unique_module_ids, custom_rows, published=False)

    @staticmethod
    async def publish(session: AsyncSession, package_id: UUID) -> PublishPackageResponse:
        """Lock a draft, snapshot modules + custom items into assessments.

        Args:
            session: Async database session.
            package_id: Draft package id.

        Returns:
            Published package with review and candidate sharing paths.

        Raises:
            LookupError: Package not found.
            PackageLockedError: Already published.
            ClientPackageError: Empty cart.
        """
        package = (
            await session.execute(select(Package).where(Package.id == package_id))
        ).scalar_one_or_none()
        if not package:
            raise LookupError("Package not found")
        if package.status == "published":
            raise PackageLockedError("Package is already published")

        module_ids, custom_rows = await ClientPackageService._load_cart(session, package_id)
        if not module_ids and not custom_rows:
            raise ClientPackageError("Add at least one module or custom question")

        join_rows = (
            await session.execute(
                select(PackageModule, GlobalModule)
                .join(GlobalModule, GlobalModule.id == PackageModule.global_module_id)
                .where(PackageModule.package_id == package.id)
                .order_by(PackageModule.position)
            )
        ).all()
        latest_by_pinned = await _latest_published_for(
            session, [pinned for _link, pinned in join_rows]
        )
        resolved: list[tuple[GlobalModule, list[dict[str, Any]]]] = []
        for link, pinned in join_rows:
            override = link.questions if isinstance(link.questions, list) else None
            module, questions = resolve_cart_row(
                pinned, latest_by_pinned.get(pinned.id, pinned), override
            )
            if any(existing.id == module.id for existing, _qs in resolved):
                continue
            resolved.append((module, questions))
        module_ids = [module.id for module, _qs in resolved]

        await session.execute(
            delete(Assessment).where(Assessment.package_id == package.id)
        )

        position = 0
        for module, questions in resolved:
            session.add(
                Assessment(
                    corporate_id=package.corporate_id,
                    package_id=package.id,
                    title=module.title,
                    description=module.description,
                    time_limit_minutes=module.time_limit_minutes,
                    timer_mode=getattr(module, "timer_mode", None) or "flexible",
                    duration_seconds=getattr(module, "duration_seconds", None),
                    shuffle_questions=bool(getattr(module, "shuffle_questions", False)),
                    scoring_profile=getattr(module, "scoring_profile", None),
                    position=position,
                    questions=questions,
                    module_kind=module.module_kind,
                    global_module_id=module.id,
                )
            )
            position += 1

        if custom_rows:
            stored = [_custom_to_storage(row, i) for i, row in enumerate(custom_rows)]
            session.add(
                Assessment(
                    corporate_id=package.corporate_id,
                    package_id=package.id,
                    title="Custom Technical",
                    description="Client-specific technical items",
                    time_limit_minutes=max(10, 3 * len(stored)),
                    position=position,
                    questions=stored,
                    module_kind=TECHNICAL,
                    global_module_id=None,
                )
            )

        if not package.review_token:
            package.review_token = _review_token()
        package.status = "published"
        package.is_active = True
        package.published_at = datetime.now(timezone.utc)

        await session.commit()
        await session.refresh(package)

        token = package.review_token or ""
        return PublishPackageResponse(
            **_draft_response(package, module_ids, custom_rows, published=True).model_dump(),
            access_code=package.access_code,
            review_token=token,
            review_path=f"/client/review/{token}",
            candidate_path=f"/portal?code={package.access_code}",
        )

    @staticmethod
    async def get_blind_review(
        session: AsyncSession, review_token: str
    ) -> BlindReviewResponse:
        """Public review payload. Psychometric modules are never included.

        Args:
            session: Async database session.
            review_token: Opaque package token from the publish step.

        Returns:
            Title, company name, and technical questions only.

        Raises:
            LookupError: Unknown or unpublished token.
        """
        package = (
            await session.execute(
                select(Package).where(
                    Package.review_token == review_token,
                    Package.status == "published",
                )
            )
        ).scalar_one_or_none()
        if not package:
            raise LookupError("Review link is invalid or expired")

        corporate = (
            await session.execute(
                select(Corporate).where(Corporate.id == package.corporate_id)
            )
        ).scalar_one_or_none()
        assessments = (
            await session.execute(
                select(Assessment)
                .where(Assessment.package_id == package.id)
                .order_by(Assessment.position)
            )
        ).scalars().all()
        custom_rows = (
            await session.execute(
                select(CustomTechnicalQuestion)
                .where(CustomTechnicalQuestion.package_id == package.id)
                .order_by(CustomTechnicalQuestion.position)
            )
        ).scalars().all()

        return BlindReviewResponse(
            package_id=package.id,
            title=package.title,
            corporate_name=corporate.name if corporate else None,
            status=package.status,
            client_approved=bool(package.client_approved),
            reviewed_at=package.reviewed_at,
            questions=public_review_questions(list(custom_rows), list(assessments)),
        )

    @staticmethod
    async def approve_blind_review(
        session: AsyncSession, review_token: str
    ) -> dict[str, Any]:
        """Mark a published package as client-approved via review token.

        Args:
            session: Async database session.
            review_token: Opaque package token from the publish step.

        Returns:
            Success payload for the public review CTA.

        Raises:
            LookupError: Unknown token or package not published.
        """
        package = (
            await session.execute(
                select(Package).where(
                    Package.review_token == review_token,
                    Package.status == "published",
                )
            )
        ).scalar_one_or_none()
        if not package:
            raise LookupError("Review link is invalid or expired")

        if not package.client_approved:
            package.client_approved = True
            package.reviewed_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(package)

        return {
            "success": True,
            "message": "Assessment approved successfully",
        }

    @staticmethod
    async def list_client_pipeline(
        session: AsyncSession, corporate_id: UUID
    ) -> list[ClientPipelineRow]:
        """HR-scoped candidate rows for the read-only client dashboard.

        Args:
            session: Async database session.
            corporate_id: Authenticated HR tenant.

        Returns:
            Pipeline rows with Pending / Scoring / Completed status.
        """
        candidates = (
            await session.execute(
                select(Candidate)
                .where(Candidate.corporate_id == corporate_id)
                .order_by(Candidate.created_at.desc())
            )
        ).scalars().all()
        if not candidates:
            return []

        package_ids = {c.package_id for c in candidates}
        packages = (
            await session.execute(
                select(Package).where(
                    Package.id.in_(package_ids),
                    Package.corporate_id == corporate_id,
                )
            )
        ).scalars().all()
        titles = {p.id: p.title for p in packages}

        agg = await _candidate_aggregates(session, list(candidates))

        rows: list[ClientPipelineRow] = []
        for cand in candidates:
            total = agg.total_for(cand)
            completed = agg.completed.get(cand.id, 0)
            jd_fit = agg.fit.get(cand.id)
            status = pipeline_status(
                completed=completed,
                total=total,
                logged_in=bool(cand.logged_in_at),
                jd_fit=jd_fit,
            )
            tech_score = agg.avg_score.get(cand.id)
            package_done = total > 0 and completed >= total
            rows.append(
                ClientPipelineRow(
                    id=cand.id,
                    package_id=cand.package_id,
                    package_title=titles.get(cand.package_id, ""),
                    full_name=cand.full_name,
                    email=cand.email,
                    pipeline_status=status,
                    completed_assessments=completed,
                    total_assessments=total,
                    avg_score=tech_score,
                    technical_score=tech_score,
                    jd_fit=jd_fit,
                    created_at=cand.created_at,
                    completed_at=agg.completed_at.get(cand.id) if package_done else None,
                )
            )
        return rows

    @staticmethod
    async def get_client_dashboard(
        session: AsyncSession, corporate_id: UUID
    ) -> ClientDashboardResponse:
        """Package-grouped, read-only dashboard for one HR tenant.

        Args:
            session: Async database session.
            corporate_id: Tenant from the verified client JWT. Every query
                below filters on it.

        Returns:
            Corporate branding plus published, active packages with their
            candidates and invited/completed totals.

        Raises:
            LookupError: The tenant's corporates row no longer exists.
        """
        corporate = (
            await session.execute(select(Corporate).where(Corporate.id == corporate_id))
        ).scalar_one_or_none()
        if corporate is None:
            raise LookupError("Company not found")

        packages = (
            await session.execute(
                select(Package)
                .where(
                    Package.corporate_id == corporate_id,
                    Package.status == "published",
                    Package.is_active.is_(True),
                )
                .order_by(Package.published_at.desc().nulls_last(), Package.title)
            )
        ).scalars().all()

        corporate_out = ClientCorporate(
            id=corporate.id, name=corporate.name, logo_url=corporate.logo_url
        )
        if not packages:
            return ClientDashboardResponse(corporate=corporate_out, packages=[])

        package_ids = [p.id for p in packages]
        candidates = (
            await session.execute(
                select(Candidate)
                .where(
                    Candidate.corporate_id == corporate_id,
                    Candidate.package_id.in_(package_ids),
                )
                .order_by(Candidate.created_at.desc())
            )
        ).scalars().all()

        agg = await _candidate_aggregates(session, list(candidates), package_ids)

        by_package: dict[UUID, list[ClientDashboardCandidate]] = {
            pid: [] for pid in package_ids
        }
        for cand in candidates:
            total = agg.total_for(cand)
            completed = agg.completed.get(cand.id, 0)
            status = client_status(
                completed=completed, total=total, logged_in=bool(cand.logged_in_at)
            )
            done = status == "completed"
            by_package[cand.package_id].append(
                ClientDashboardCandidate(
                    candidate_id=cand.id,
                    name=cand.full_name,
                    email=cand.email,
                    status=status,
                    raw_score=agg.avg_score.get(cand.id),
                    completed_assessments=completed,
                    total_assessments=total,
                    report_available=done,
                    report_path=f"/client/candidates/{cand.id}" if done else None,
                )
            )

        out: list[ClientDashboardPackage] = []
        for pkg in packages:
            rows = by_package[pkg.id]
            out.append(
                ClientDashboardPackage(
                    id=pkg.id,
                    title=pkg.title,
                    access_code=pkg.access_code,
                    target_role=pkg.target_role,
                    candidate_path=f"/portal?code={pkg.access_code}",
                    total_invited=len(rows),
                    total_completed=sum(1 for r in rows if r.status == "completed"),
                    candidates=rows,
                )
            )
        return ClientDashboardResponse(corporate=corporate_out, packages=out)

    @staticmethod
    async def get_client_scorecard(
        session: AsyncSession, candidate_id: UUID, corporate_id: UUID
    ) -> ClientScorecardResponse:
        """Gemini scorecard with psychometric assessments removed.

        Args:
            session: Async database session.
            candidate_id: Candidate to render.
            corporate_id: Authenticated HR tenant (must own the candidate).

        Returns:
            Sanitized scorecard. Evaluation payload is filtered to top-level
            fit fields; per-item psychometric evidence is dropped.

        Raises:
            LookupError: Candidate missing or not in tenant.
        """
        candidate = (
            await session.execute(
                select(Candidate).where(
                    Candidate.id == candidate_id,
                    Candidate.corporate_id == corporate_id,
                )
            )
        ).scalar_one_or_none()
        if not candidate:
            raise LookupError("Candidate not found")

        package = (
            await session.execute(select(Package).where(Package.id == candidate.package_id))
        ).scalar_one_or_none()

        assessments = (
            await session.execute(
                select(Assessment)
                .where(Assessment.package_id == candidate.package_id)
                .order_by(Assessment.position)
            )
        ).scalars().all()
        progress_rows = (
            await session.execute(
                select(CandidateProgress).where(
                    CandidateProgress.candidate_id == candidate_id
                )
            )
        ).scalars().all()
        progress_by_id = {p.assessment_id: p for p in progress_rows}

        eval_row = (
            await session.execute(
                select(CandidateEvaluation).where(
                    CandidateEvaluation.candidate_id == candidate_id
                )
            )
        ).scalar_one_or_none()

        technical_assessments: list[ClientScorecardAssessment] = []
        scores: list[float] = []
        for assessment in assessments:
            if (assessment.module_kind or TECHNICAL) == PSYCHOMETRIC:
                continue
            prog = progress_by_id.get(assessment.id)
            score = float(prog.score) if prog and prog.score is not None else None
            if score is not None:
                scores.append(score)
            technical_assessments.append(
                ClientScorecardAssessment(
                    id=assessment.id,
                    title=assessment.title,
                    module_kind=TECHNICAL,
                    status=prog.status if prog else "NOT_STARTED",
                    score=score,
                    completed_at=prog.completed_at if prog else None,
                )
            )

        payload = eval_row.payload if evaluation_is_ok(eval_row) else None
        sanitized: dict[str, Any] | None = None
        recommendation = None
        summary = None
        if payload:
            sanitized = {
                "overall_fit": payload.get("overall_fit"),
                "recommendation": payload.get("recommendation"),
                "executive_summary": payload.get("executive_summary")
                or payload.get("summary"),
                "strengths": payload.get("strengths"),
                "risks": payload.get("risks") or payload.get("gaps"),
            }
            recommendation = payload.get("recommendation")
            summary = sanitized.get("executive_summary")

        jd_fit = (
            float(eval_row.overall_fit)
            if eval_row and eval_row.overall_fit is not None
            else None
        )
        completed = sum(
            1 for p in progress_rows if p.status == "COMPLETED"
        )
        total = len(assessments)
        return ClientScorecardResponse(
            candidate_id=candidate.id,
            full_name=candidate.full_name,
            email=candidate.email,
            package_title=package.title if package else "",
            pipeline_status=pipeline_status(
                completed=completed,
                total=total,
                logged_in=bool(candidate.logged_in_at),
                jd_fit=jd_fit,
            ),
            avg_score=round(sum(scores) / len(scores), 1) if scores else None,
            jd_fit=jd_fit,
            recommendation=recommendation if isinstance(recommendation, str) else None,
            summary=summary if isinstance(summary, str) else None,
            assessments=technical_assessments,
            evaluation=sanitized,
        )
