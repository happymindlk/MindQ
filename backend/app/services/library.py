"""Master Assessment Library: template CRUD, snapshot, and cherry-pick sync."""
from __future__ import annotations

import copy
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.global_module import (
    MODULE_STATUS_DRAFT,
    MODULE_STATUS_PUBLISHED,
    GlobalModule,
)
from app.models.package import Package
from app.models.package_module import PackageModule
from app.models.template_question import TemplateQuestion
from app.schemas.client_package import CustomQuestionIn
from app.schemas.library import (
    AddTemplateResponse,
    TemplateCreate,
    TemplateDetail,
    TemplateQuestionCreate,
    TemplateQuestionOut,
    TemplateQuestionUpdate,
    TemplateSummary,
    TemplateUpdate,
)
from app.schemas.package_builder import QuestionItem, QuestionType
from app.schemas.question_payload import QuestionPayload, payload_from_storage
from app.services.client_package import ClientPackageError, PackageLockedError
from app.services.package_generator import blueprint_question_to_storage


class LibraryError(ClientPackageError):
    """Domain error for master-library operations."""


class LibraryConflictError(LibraryError):
    """Raised when a template operation conflicts with package state."""


class ModuleLockedError(LibraryConflictError):
    """Raised when a destructive edit targets a published or live-linked module."""

    code = "MODULE_LOCKED"

    def __init__(self, module: GlobalModule, reason: str) -> None:
        self.module_id = module.id
        self.version = int(getattr(module, "version", 1) or 1)
        super().__init__(
            f'"{module.title}" v{self.version} is locked ({reason}). '
            f"Clone it as v{self.version + 1} to make changes."
        )


async def _live_package_attachment_count(session: AsyncSession, template_id: UUID) -> int:
    """Count live packages (published and active) that include a template.

    Args:
        session: Async database session.
        template_id: global_modules.id.

    Returns:
        Number of published, active packages with a package_modules row for the template.
    """
    count = (
        await session.execute(
            select(func.count())
            .select_from(PackageModule)
            .join(Package, Package.id == PackageModule.package_id)
            .where(
                PackageModule.global_module_id == template_id,
                Package.status == "published",
                Package.is_active.is_(True),
            )
        )
    ).scalar_one()
    return int(count or 0)


async def assert_module_editable(session: AsyncSession, module: GlobalModule) -> None:
    """Fail fast when a module's question bank or runner config is frozen.

    A module is frozen once it is published, or while any live published package
    links it (legacy rows predating versioning).

    Args:
        session: Async database session.
        module: Template about to be mutated.

    Returns:
        None when edits are allowed.

    Raises:
        ModuleLockedError: Module is published or linked to a live package.
    """
    if (getattr(module, "status", None) or MODULE_STATUS_DRAFT) == MODULE_STATUS_PUBLISHED:
        raise ModuleLockedError(module, "published")
    live = await _live_package_attachment_count(session, module.id)
    if live > 0:
        noun = "package" if live == 1 else "packages"
        raise ModuleLockedError(module, f"linked to {live} live {noun}")


def _sync_duration_fields(
    module: GlobalModule, *, minutes: int | None, seconds: int | None
) -> None:
    """Keep ``duration_seconds`` authoritative and ``time_limit_minutes`` in sync.

    Args:
        module: Row to mutate.
        minutes: Legacy minute value from older clients (None = untouched).
        seconds: New second-precision duration (None = untouched; 0 = untimed).

    Returns:
        None.
    """
    if seconds is not None:
        module.duration_seconds = seconds or None
        module.time_limit_minutes = -(-seconds // 60) if seconds else None
    elif minutes is not None:
        module.time_limit_minutes = minutes
        module.duration_seconds = minutes * 60


def slugify_template_title(title: str) -> str:
    """Build a URL-safe slug from a template title.

    Args:
        title: Display title entered by ops.

    Returns:
        Lowercase hyphenated slug with non-alphanumerics stripped.
    """
    ascii_name = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "template"


def _rubric_from_payload(payload: dict[str, Any]) -> str:
    """Extract rubric/answer text from a portal-shaped question dict.

    Args:
        payload: Stored question JSON.

    Returns:
        Rubric or correct-answer string (may be empty).
    """
    for key in (
        "correct_answer_or_rubric",
        "benchmark_rubric",
        "correct_answer",
        "evaluation_rubric",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _text_from_payload(payload: dict[str, Any]) -> str:
    """Extract prompt text from a portal-shaped question dict.

    Args:
        payload: Stored question JSON.

    Returns:
        Question prompt/text.
    """
    for key in ("text", "prompt", "question_text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def payload_to_storage(payload: dict[str, Any], index: int = 0) -> dict[str, Any]:
    """Normalize a question_payload (or catalog item) into portal storage shape.

    Args:
        payload: Raw question dict (catalog or template_questions.question_payload).
        index: Zero-based position for stable id generation when missing.

    Returns:
        Deep-copied portal-compatible question dict.
    """
    if not isinstance(payload, dict):
        return {}
    stored = copy.deepcopy(payload)
    text = _text_from_payload(stored)
    if text:
        stored["text"] = text
    if "id" not in stored or not stored["id"]:
        stored["id"] = f"tq-{index + 1:03d}-{uuid4().hex[:8]}"
    return stored


def custom_in_to_storage(item: CustomQuestionIn, index: int = 0) -> dict[str, Any]:
    """Map a CustomQuestionIn into assessments.questions JSONB shape.

    Args:
        item: Ops-authored custom / sync payload.
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


def create_body_to_storage(body: TemplateQuestionCreate, index: int = 0) -> dict[str, Any]:
    """Map TemplateQuestionCreate into portal storage JSON.

    Args:
        body: Master question create payload.
        index: Zero-based position.

    Returns:
        Portal-compatible question dict.
    """
    prompt = (body.prompt or body.question_text or "").strip()
    rubric = body.correct_answer_or_rubric
    if rubric is None:
        rubric = body.evaluation_rubric or ""
    mapped = CustomQuestionIn(
        prompt=prompt,
        question_type=body.question_type,
        options=list(body.options or []),
        correct_answer_or_rubric=rubric or "",
        evaluated_competency=body.evaluated_competency or "Technical",
        weight=body.weight,
        likert_label_1=body.likert_label_1,
        likert_label_5=body.likert_label_5,
    )
    return custom_in_to_storage(mapped, index)


def builder_payload_to_row_fields(payload: QuestionPayload) -> tuple[str, str, dict[str, Any]]:
    """Derive template_questions columns from a dynamic-builder payload.

    Only open-ended items keep a rubric column; for keyed types the answer key
    lives in the JSON payload so ``rebuild_module_questions_json`` never
    overwrites multi-key or weighted answers with a flat string.

    Args:
        payload: Validated polymorphic question.

    Returns:
        Tuple of (question_text, evaluation_rubric, storage dict without id).
    """
    stored = payload.to_storage()
    rubric = stored.get("benchmark_rubric", "") if payload.type == "open_ended" else ""
    return payload.prompt, str(rubric or ""), stored


def _is_builder_keyed(payload: dict[str, Any]) -> bool:
    """Whether a stored question carries its own structured answer key."""
    builder = payload.get("builder_type") or payload.get("type")
    return builder in ("sjt", "crt") or "correct_keys" in payload or "reverse_scored" in payload


def row_to_question_out(row: TemplateQuestion) -> TemplateQuestionOut:
    """Serialize a TemplateQuestion ORM row for API responses.

    Args:
        row: Persisted master question.

    Returns:
        TemplateQuestionOut with flattened scoring fields and the editor payload.
    """
    payload = row.question_payload if isinstance(row.question_payload, dict) else {}
    qtype = payload.get("builder_type") or payload.get("type") or payload.get("question_type") or "mcq"
    if qtype == "open":
        qtype = "open_ended"
    builder_payload = payload_from_storage({**payload, "text": row.question_text or payload.get("text")})
    if builder_payload is not None and qtype in ("open_ended",) and row.evaluation_rubric:
        builder_payload["rubric"] = row.evaluation_rubric
    return TemplateQuestionOut(
        id=row.id,
        template_id=row.template_id,
        question_text=row.question_text or _text_from_payload(payload),
        evaluation_rubric=row.evaluation_rubric or _rubric_from_payload(payload),
        question_type=str(qtype),
        options=list(payload.get("options") or []),
        evaluated_competency=str(payload.get("evaluated_competency") or "Technical"),
        weight=int(payload.get("weight") or 3),
        likert_label_1=payload.get("likert_label_1"),
        likert_label_5=payload.get("likert_label_5"),
        question_payload=copy.deepcopy(payload),
        builder_payload=builder_payload,
        is_active=row.is_active,
        position=row.position,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _facets_of(payloads: list[dict[str, Any]]) -> set[str]:
    facets = {
        str(p.get("facet") or p.get("evaluated_competency") or "").strip()
        for p in payloads
        if isinstance(p, dict)
    }
    facets.discard("")
    return facets


def _module_to_summary(
    module: GlobalModule,
    question_count: int,
    *,
    facet_count: int = 0,
    linked_package_count: int = 0,
) -> TemplateSummary:
    kind = module.module_kind if module.module_kind in ("technical", "psychometric") else "technical"
    status = getattr(module, "status", None) or MODULE_STATUS_DRAFT
    duration = getattr(module, "duration_seconds", None)
    if duration is None and module.time_limit_minutes:
        duration = module.time_limit_minutes * 60
    return TemplateSummary(
        id=module.id,
        slug=module.slug,
        title=module.title,
        description=module.description,
        category=kind,  # type: ignore[arg-type]
        module_kind=kind,  # type: ignore[arg-type]
        assessment_category=getattr(module, "assessment_category", None),
        time_limit_minutes=module.time_limit_minutes,
        duration_seconds=duration,
        timer_mode=getattr(module, "timer_mode", None) or "flexible",
        shuffle_questions=bool(getattr(module, "shuffle_questions", False)),
        status=status,
        version=int(getattr(module, "version", 1) or 1),
        lineage_id=getattr(module, "lineage_id", None) or module.id,
        parent_module_id=getattr(module, "parent_module_id", None),
        published_at=getattr(module, "published_at", None),
        is_locked=status == MODULE_STATUS_PUBLISHED or linked_package_count > 0,
        linked_package_count=linked_package_count,
        question_count=question_count,
        facet_count=facet_count,
        position=module.position,
        is_active=module.is_active,
        created_at=module.created_at,
        updated_at=module.updated_at,
    )


class LibraryService:
    """CRUD + snapshot/sync for the Master Assessment Library."""

    @staticmethod
    async def rebuild_module_questions_json(
        session: AsyncSession, template_id: UUID
    ) -> list[dict[str, Any]]:
        """Rewrite global_modules.questions from active template_questions.

        Args:
            session: Async database session.
            template_id: global_modules.id.

        Returns:
            The rebuilt questions list written to the catalog row.

        Raises:
            LookupError: Template does not exist.
        """
        module = (
            await session.execute(select(GlobalModule).where(GlobalModule.id == template_id))
        ).scalar_one_or_none()
        if not module:
            raise LookupError("Template not found")

        rows = (
            await session.execute(
                select(TemplateQuestion)
                .where(
                    TemplateQuestion.template_id == template_id,
                    TemplateQuestion.is_active.is_(True),
                )
                .order_by(TemplateQuestion.position, TemplateQuestion.created_at)
            )
        ).scalars().all()

        questions: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            payload = row.question_payload if isinstance(row.question_payload, dict) else {}
            stored = payload_to_storage(payload, index)
            if row.question_text:
                stored["text"] = row.question_text
            rubric = row.evaluation_rubric or ""
            if rubric and not _is_builder_keyed(stored):
                qtype = stored.get("type") or stored.get("builder_type") or ""
                if qtype in ("open", "open_ended"):
                    stored["benchmark_rubric"] = rubric
                elif qtype == "mcq":
                    stored["correct_answer"] = rubric
                else:
                    stored["benchmark_rubric"] = rubric
            stored["id"] = str(row.id)
            questions.append(stored)

        module.questions = questions
        await session.flush()
        return questions

    @staticmethod
    async def list_templates(
        session: AsyncSession, *, include_inactive: bool = False
    ) -> list[TemplateSummary]:
        """List master templates with active question counts.

        Args:
            session: Async database session.
            include_inactive: When True, include deactivated templates.

        Returns:
            Template summary rows sorted by kind then position.
        """
        query = select(GlobalModule).order_by(
            GlobalModule.module_kind, GlobalModule.position, GlobalModule.title
        )
        if not include_inactive:
            query = query.where(GlobalModule.is_active.is_(True))
        modules = (await session.execute(query)).scalars().all()

        payloads_by_module: dict[UUID, list[dict[str, Any]]] = {}
        linked: dict[UUID, int] = {}
        if modules:
            ids = [m.id for m in modules]
            # One round-trip each for question payloads and live links (no N+1).
            question_rows = (
                await session.execute(
                    select(TemplateQuestion.template_id, TemplateQuestion.question_payload)
                    .where(
                        TemplateQuestion.template_id.in_(ids),
                        TemplateQuestion.is_active.is_(True),
                    )
                )
            ).all()
            for tid, payload in question_rows:
                payloads_by_module.setdefault(tid, []).append(
                    payload if isinstance(payload, dict) else {}
                )
            link_rows = (
                await session.execute(
                    select(PackageModule.global_module_id, func.count())
                    .join(Package, Package.id == PackageModule.package_id)
                    .where(
                        PackageModule.global_module_id.in_(ids),
                        Package.status == "published",
                        Package.is_active.is_(True),
                    )
                    .group_by(PackageModule.global_module_id)
                )
            ).all()
            linked = {mid: int(n) for mid, n in link_rows}

        out: list[TemplateSummary] = []
        for m in modules:
            payloads = payloads_by_module.get(m.id)
            if payloads is None:
                payloads = [q for q in (m.questions or []) if isinstance(q, dict)]
            out.append(
                _module_to_summary(
                    m,
                    len(payloads),
                    facet_count=len(_facets_of(payloads)),
                    linked_package_count=linked.get(m.id, 0),
                )
            )
        return out

    @staticmethod
    async def get_template(session: AsyncSession, template_id: UUID) -> TemplateDetail:
        """Load a template with its active questions.

        Args:
            session: Async database session.
            template_id: global_modules.id.

        Returns:
            Template detail including nested questions.

        Raises:
            LookupError: Template does not exist.
        """
        module = (
            await session.execute(select(GlobalModule).where(GlobalModule.id == template_id))
        ).scalar_one_or_none()
        if not module:
            raise LookupError("Template not found")

        rows = (
            await session.execute(
                select(TemplateQuestion)
                .where(
                    TemplateQuestion.template_id == template_id,
                    TemplateQuestion.is_active.is_(True),
                )
                .order_by(TemplateQuestion.position, TemplateQuestion.created_at)
            )
        ).scalars().all()
        questions = [row_to_question_out(r) for r in rows]
        linked = await _live_package_attachment_count(session, template_id)
        summary = _module_to_summary(
            module,
            len(questions),
            facet_count=len(_facets_of([q.question_payload for q in questions])),
            linked_package_count=linked,
        )
        return TemplateDetail(**summary.model_dump(), questions=questions)

    @staticmethod
    async def _load_module(session: AsyncSession, template_id: UUID) -> GlobalModule:
        module = (
            await session.execute(select(GlobalModule).where(GlobalModule.id == template_id))
        ).scalar_one_or_none()
        if not module:
            raise LookupError("Template not found")
        return module

    @staticmethod
    async def create_template(
        session: AsyncSession, body: TemplateCreate
    ) -> TemplateDetail:
        """Create a new global_modules template.

        Args:
            session: Async database session.
            body: Create payload.

        Returns:
            Newly created template (empty questions).

        Raises:
            LibraryError: Slug collision or invalid input.
        """
        base_slug = (body.slug or slugify_template_title(body.title)).strip()[:128]
        slug = base_slug
        suffix = 2
        while True:
            existing = (
                await session.execute(select(GlobalModule.id).where(GlobalModule.slug == slug))
            ).scalar_one_or_none()
            if not existing:
                break
            slug = f"{base_slug}-{suffix}"[:128]
            suffix += 1

        max_pos = (
            await session.execute(
                select(func.coalesce(func.max(GlobalModule.position), 0)).where(
                    GlobalModule.module_kind == body.category
                )
            )
        ).scalar_one()

        module_id = uuid4()
        module = GlobalModule(
            id=module_id,
            slug=slug,
            title=body.title.strip(),
            description=(body.description or "").strip() or None,
            module_kind=body.category,
            assessment_category=(
                body.assessment_category if body.category == "psychometric" else None
            ),
            time_limit_minutes=None,
            duration_seconds=None,
            timer_mode=body.timer_mode,
            shuffle_questions=body.shuffle_questions,
            status=MODULE_STATUS_DRAFT,
            version=1,
            lineage_id=module_id,
            questions=[],
            is_active=True,
            position=int(max_pos or 0) + 1,
        )
        _sync_duration_fields(
            module, minutes=body.time_limit_minutes, seconds=body.duration_seconds
        )
        session.add(module)
        await session.commit()
        await session.refresh(module)
        return await LibraryService.get_template(session, module.id)

    @staticmethod
    async def update_template(
        session: AsyncSession, template_id: UUID, body: TemplateUpdate
    ) -> TemplateDetail:
        """Update template metadata.

        Args:
            session: Async database session.
            template_id: global_modules.id.
            body: Partial update.

        Returns:
            Updated template detail.

        Raises:
            LookupError: Template does not exist.
            ModuleLockedError: Runner config or kind change on a locked module.
        """
        module = await LibraryService._load_module(session, template_id)

        if body.touches_runner_config() or (
            body.category is not None and body.category != module.module_kind
        ):
            await assert_module_editable(session, module)

        if body.title is not None:
            module.title = body.title.strip()
        if body.category is not None:
            module.module_kind = body.category
            if body.category != "psychometric":
                module.assessment_category = None
        if body.assessment_category is not None and module.module_kind == "psychometric":
            module.assessment_category = body.assessment_category
        if body.description is not None:
            module.description = body.description.strip() or None
        _sync_duration_fields(
            module, minutes=body.time_limit_minutes, seconds=body.duration_seconds
        )
        if body.timer_mode is not None:
            module.timer_mode = body.timer_mode
        if body.shuffle_questions is not None:
            module.shuffle_questions = body.shuffle_questions
        if body.is_active is not None:
            module.is_active = body.is_active
        if body.position is not None:
            module.position = body.position

        await session.commit()
        return await LibraryService.get_template(session, template_id)

    @staticmethod
    async def archive_template(session: AsyncSession, template_id: UUID) -> TemplateDetail:
        """Soft-archive a template so it disappears from the library and builder.

        Allowed even for live modules: published packages already hold eager
        question snapshots (package_modules.questions / assessments.questions),
        so historical responses and scores stay intact. Archiving only hides the
        module from new packages.

        Args:
            session: Async database session.
            template_id: global_modules.id.

        Returns:
            Archived template detail. Idempotent when already archived.

        Raises:
            LookupError: Template does not exist.
        """
        module = await LibraryService._load_module(session, template_id)

        if module.is_active:
            module.is_active = False
            await session.commit()

        return await LibraryService.get_template(session, template_id)

    @staticmethod
    async def publish_template(session: AsyncSession, template_id: UUID) -> TemplateDetail:
        """Freeze a draft module so packages can snapshot it.

        Args:
            session: Async database session.
            template_id: global_modules.id.

        Returns:
            Published template detail. Idempotent when already published.

        Raises:
            LookupError: Template does not exist.
            LibraryError: Module is archived or has no active questions.
        """
        module = await LibraryService._load_module(session, template_id)
        if (getattr(module, "status", None) or MODULE_STATUS_DRAFT) == MODULE_STATUS_PUBLISHED:
            return await LibraryService.get_template(session, template_id)
        if not module.is_active:
            raise LibraryError("Archived modules cannot be published")

        questions = await LibraryService.rebuild_module_questions_json(session, template_id)
        if not questions:
            raise LibraryError("Add at least one question before publishing")

        module.status = MODULE_STATUS_PUBLISHED
        module.published_at = datetime.now(timezone.utc)
        await session.commit()
        return await LibraryService.get_template(session, template_id)

    @staticmethod
    async def clone_version(session: AsyncSession, template_id: UUID) -> TemplateDetail:
        """Fork a module into a new draft version on the same lineage.

        Returns the existing open draft instead of minting a second one so two
        admins cannot create divergent v2 branches.

        Args:
            session: Async database session.
            template_id: Source global_modules.id (any version in the lineage).

        Returns:
            The draft version detail with deep-copied questions.

        Raises:
            LookupError: Template does not exist.
        """
        source = await LibraryService._load_module(session, template_id)
        lineage = getattr(source, "lineage_id", None) or source.id

        existing_draft = (
            await session.execute(
                select(GlobalModule)
                .where(
                    GlobalModule.lineage_id == lineage,
                    GlobalModule.status == MODULE_STATUS_DRAFT,
                    GlobalModule.is_active.is_(True),
                )
                .order_by(GlobalModule.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing_draft is not None:
            return await LibraryService.get_template(session, existing_draft.id)

        max_version = (
            await session.execute(
                select(func.coalesce(func.max(GlobalModule.version), 1)).where(
                    GlobalModule.lineage_id == lineage
                )
            )
        ).scalar_one()
        next_version = int(max_version or 1) + 1

        base_slug = re.sub(r"-v\d+$", "", source.slug)[:120]
        slug = f"{base_slug}-v{next_version}"
        suffix = 2
        while (
            await session.execute(select(GlobalModule.id).where(GlobalModule.slug == slug))
        ).scalar_one_or_none():
            slug = f"{base_slug}-v{next_version}-{suffix}"[:128]
            suffix += 1

        clone = GlobalModule(
            id=uuid4(),
            slug=slug,
            title=source.title,
            description=source.description,
            module_kind=source.module_kind,
            assessment_category=getattr(source, "assessment_category", None),
            time_limit_minutes=source.time_limit_minutes,
            duration_seconds=getattr(source, "duration_seconds", None),
            timer_mode=getattr(source, "timer_mode", None) or "flexible",
            shuffle_questions=bool(getattr(source, "shuffle_questions", False)),
            scoring_profile=getattr(source, "scoring_profile", None),
            status=MODULE_STATUS_DRAFT,
            version=next_version,
            lineage_id=lineage,
            parent_module_id=source.id,
            questions=[],
            is_active=True,
            position=source.position,
        )
        session.add(clone)
        await session.flush()

        rows = (
            await session.execute(
                select(TemplateQuestion)
                .where(
                    TemplateQuestion.template_id == source.id,
                    TemplateQuestion.is_active.is_(True),
                )
                .order_by(TemplateQuestion.position, TemplateQuestion.created_at)
            )
        ).scalars().all()
        for index, row in enumerate(rows):
            payload = copy.deepcopy(row.question_payload) if isinstance(row.question_payload, dict) else {}
            payload.pop("id", None)
            session.add(
                TemplateQuestion(
                    id=uuid4(),
                    template_id=clone.id,
                    question_text=row.question_text,
                    evaluation_rubric=row.evaluation_rubric,
                    question_payload=payload,
                    is_active=True,
                    position=index,
                )
            )
        await session.flush()
        await LibraryService.rebuild_module_questions_json(session, clone.id)
        await session.commit()
        return await LibraryService.get_template(session, clone.id)

    @staticmethod
    async def create_question(
        session: AsyncSession, template_id: UUID, body: TemplateQuestionCreate
    ) -> TemplateQuestionOut:
        """Insert a master question and rebuild catalog JSONB.

        Args:
            session: Async database session.
            template_id: Parent template id.
            body: Question create payload.

        Returns:
            Persisted question.

        Raises:
            LookupError: Template does not exist.
            ModuleLockedError: Module is published or linked to a live package.
        """
        module = await LibraryService._load_module(session, template_id)
        await assert_module_editable(session, module)

        max_pos = (
            await session.execute(
                select(func.coalesce(func.max(TemplateQuestion.position), -1)).where(
                    TemplateQuestion.template_id == template_id
                )
            )
        ).scalar_one()
        position = int(max_pos if max_pos is not None else -1) + 1
        if body.payload is not None:
            prompt, rubric, stored = builder_payload_to_row_fields(body.payload)
            stored["id"] = f"tq-{position + 1:03d}-{uuid4().hex[:8]}"
        else:
            stored = create_body_to_storage(body, position)
            prompt = (body.prompt or body.question_text or "").strip()
            rubric = body.correct_answer_or_rubric
            if rubric is None:
                rubric = body.evaluation_rubric or ""

        row = TemplateQuestion(
            id=uuid4(),
            template_id=template_id,
            question_text=prompt,
            evaluation_rubric=(rubric or "").strip(),
            question_payload=stored,
            is_active=True,
            position=position,
        )
        session.add(row)
        await session.flush()
        await LibraryService.rebuild_module_questions_json(session, template_id)
        await session.commit()
        await session.refresh(row)
        return row_to_question_out(row)

    @staticmethod
    async def update_question(
        session: AsyncSession,
        template_id: UUID,
        question_id: UUID,
        body: TemplateQuestionUpdate,
    ) -> TemplateQuestionOut:
        """Update a master question and rebuild catalog JSONB.

        Args:
            session: Async database session.
            template_id: Parent template id.
            question_id: template_questions.id.
            body: Partial update.

        Returns:
            Updated question.

        Raises:
            LookupError: Template or question not found.
            ModuleLockedError: Module is published or linked to a live package.
        """
        module = await LibraryService._load_module(session, template_id)
        await assert_module_editable(session, module)

        row = (
            await session.execute(
                select(TemplateQuestion).where(
                    TemplateQuestion.id == question_id,
                    TemplateQuestion.template_id == template_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            raise LookupError("Question not found")

        if body.payload is not None:
            prompt, rubric_text, stored = builder_payload_to_row_fields(body.payload)
            existing = row.question_payload if isinstance(row.question_payload, dict) else {}
            stored["id"] = existing.get("id") or str(row.id)
            row.question_text = prompt
            row.evaluation_rubric = rubric_text
            row.question_payload = stored
            if body.is_active is not None:
                row.is_active = body.is_active
            if body.position is not None:
                row.position = body.position
            await session.flush()
            await LibraryService.rebuild_module_questions_json(session, template_id)
            await session.commit()
            await session.refresh(row)
            return row_to_question_out(row)

        payload = copy.deepcopy(row.question_payload) if isinstance(row.question_payload, dict) else {}
        if body.question_text is not None:
            row.question_text = body.question_text.strip()
            payload["text"] = row.question_text
        if body.evaluation_rubric is not None:
            row.evaluation_rubric = body.evaluation_rubric
        if body.question_type is not None:
            qtype = body.question_type
            if isinstance(qtype, QuestionType):
                qtype_val = qtype.value
            else:
                qtype_val = str(qtype)
            payload["builder_type"] = qtype_val
            payload["type"] = "open" if qtype_val == "open_ended" else qtype_val
        if body.options is not None:
            payload["options"] = list(body.options)
        if body.evaluated_competency is not None:
            payload["evaluated_competency"] = body.evaluated_competency.strip() or "Technical"
        if body.weight is not None:
            payload["weight"] = body.weight
        if body.likert_label_1 is not None:
            payload["likert_label_1"] = body.likert_label_1
        if body.likert_label_5 is not None:
            payload["likert_label_5"] = body.likert_label_5
        if body.is_active is not None:
            row.is_active = body.is_active
        if body.position is not None:
            row.position = body.position

        # Keep rubric fields in payload aligned with evaluation_rubric.
        rubric = row.evaluation_rubric or ""
        qtype_now = payload.get("type") or payload.get("builder_type") or ""
        if not _is_builder_keyed(payload):
            if qtype_now in ("open", "open_ended"):
                payload["benchmark_rubric"] = rubric
            elif qtype_now == "mcq":
                payload["correct_answer"] = rubric

        row.question_payload = payload
        await session.flush()
        await LibraryService.rebuild_module_questions_json(session, template_id)
        await session.commit()
        await session.refresh(row)
        return row_to_question_out(row)

    @staticmethod
    async def deactivate_question(
        session: AsyncSession, template_id: UUID, question_id: UUID
    ) -> TemplateQuestionOut:
        """Soft-deactivate a master question and rebuild catalog JSONB.

        Args:
            session: Async database session.
            template_id: Parent template id.
            question_id: template_questions.id.

        Returns:
            Deactivated question.

        Raises:
            LookupError: Question not found.
        """
        return await LibraryService.update_question(
            session,
            template_id,
            question_id,
            TemplateQuestionUpdate(is_active=False),
        )

    @staticmethod
    async def snapshot_active_questions(
        session: AsyncSession, template_id: UUID
    ) -> list[dict[str, Any]]:
        """Build a deep-copied JSONB snapshot of active master questions.

        Prefers template_questions rows; falls back to global_modules.questions
        when the normalized table has not been backfilled yet.

        Args:
            session: Async database session.
            template_id: global_modules.id.

        Returns:
            List of portal-shaped question dicts.

        Raises:
            LookupError: Template does not exist.
        """
        module = (
            await session.execute(select(GlobalModule).where(GlobalModule.id == template_id))
        ).scalar_one_or_none()
        if not module:
            raise LookupError("Template not found")

        rows = (
            await session.execute(
                select(TemplateQuestion)
                .where(
                    TemplateQuestion.template_id == template_id,
                    TemplateQuestion.is_active.is_(True),
                )
                .order_by(TemplateQuestion.position, TemplateQuestion.created_at)
            )
        ).scalars().all()

        if rows:
            out: list[dict[str, Any]] = []
            for index, row in enumerate(rows):
                payload = row.question_payload if isinstance(row.question_payload, dict) else {}
                stored = payload_to_storage(payload, index)
                if row.question_text:
                    stored["text"] = row.question_text
                stored["id"] = str(row.id)
                out.append(stored)
            return out

        catalog = module.questions if isinstance(module.questions, list) else []
        return [payload_to_storage(q, i) for i, q in enumerate(catalog) if isinstance(q, dict)]

    @staticmethod
    async def add_template_to_package(
        session: AsyncSession, package_id: UUID, template_id: UUID
    ) -> AddTemplateResponse:
        """Fork a master template into a package cart with an eager JSONB snapshot.

        Args:
            session: Async database session.
            package_id: Draft package id.
            template_id: Master template (global_modules) id.

        Returns:
            Snapshot metadata including copied questions.

        Raises:
            LookupError: Package or template missing.
            PackageLockedError: Package is published.
            LibraryConflictError: Template already attached with a snapshot.
        """
        package = (
            await session.execute(select(Package).where(Package.id == package_id))
        ).scalar_one_or_none()
        if not package:
            raise LookupError("Package not found")
        if package.status == "published":
            raise PackageLockedError()

        module = (
            await session.execute(select(GlobalModule).where(GlobalModule.id == template_id))
        ).scalar_one_or_none()
        if not module:
            raise LookupError("Template not found")
        if not module.is_active:
            raise LibraryError("Template is inactive")
        if getattr(module, "status", MODULE_STATUS_PUBLISHED) != MODULE_STATUS_PUBLISHED:
            raise LibraryError("Publish the module before adding it to a package")

        snapshot = await LibraryService.snapshot_active_questions(session, template_id)

        existing = (
            await session.execute(
                select(PackageModule).where(
                    PackageModule.package_id == package_id,
                    PackageModule.global_module_id == template_id,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            if existing.questions is None:
                existing.questions = copy.deepcopy(snapshot)
                await session.commit()
                return AddTemplateResponse(
                    package_id=package_id,
                    template_id=template_id,
                    question_count=len(snapshot),
                    questions=copy.deepcopy(snapshot),
                    created=False,
                )
            raise LibraryConflictError("Template is already attached to this package")

        max_pos = (
            await session.execute(
                select(func.coalesce(func.max(PackageModule.position), -1)).where(
                    PackageModule.package_id == package_id
                )
            )
        ).scalar_one()

        session.add(
            PackageModule(
                package_id=package_id,
                global_module_id=template_id,
                position=int(max_pos or -1) + 1,
                questions=copy.deepcopy(snapshot),
            )
        )
        await session.commit()
        return AddTemplateResponse(
            package_id=package_id,
            template_id=template_id,
            question_count=len(snapshot),
            questions=copy.deepcopy(snapshot),
            created=True,
        )

    @staticmethod
    async def sync_question(
        session: AsyncSession, template_id: UUID, body: CustomQuestionIn
    ) -> TemplateQuestionOut:
        """Cherry-pick a custom question into the master library.

        Inserts a new template_questions row and rebuilds catalog JSONB.
        Does not mutate any package_modules snapshots.

        Args:
            session: Async database session.
            template_id: Target master template.
            body: Custom question payload from Package Builder.

        Returns:
            Newly inserted master question.

        Raises:
            LookupError: Template does not exist.
        """
        create_body = TemplateQuestionCreate(
            question_text=body.prompt,
            evaluation_rubric=body.correct_answer_or_rubric or "",
            question_type=body.question_type,
            options=list(body.options or []),
            evaluated_competency=body.evaluated_competency or "Technical",
            weight=body.weight,
            likert_label_1=body.likert_label_1,
            likert_label_5=body.likert_label_5,
            prompt=body.prompt,
            correct_answer_or_rubric=body.correct_answer_or_rubric or "",
        )
        return await LibraryService.create_question(session, template_id, create_body)
