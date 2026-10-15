"""Unit tests for Master Assessment Library helpers and isolation semantics."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.client_package import CustomQuestionIn
from app.schemas.library import TemplateQuestionCreate, TemplateUpdate
from app.schemas.package_builder import QuestionType
from app.services.library import (
    LibraryConflictError,
    LibraryError,
    LibraryService,
    ModuleLockedError,
    create_body_to_storage,
    custom_in_to_storage,
    payload_to_storage,
    row_to_question_out,
    slugify_template_title,
)


def test_slugify_template_title():
    assert slugify_template_title("Junior Data Analyst") == "junior-data-analyst"
    assert slugify_template_title("  ") == "template"


def test_payload_to_storage_normalizes_text_and_id():
    stored = payload_to_storage({"prompt": "What is SQL?", "type": "mcq"}, index=2)
    assert stored["text"] == "What is SQL?"
    assert stored["id"]
    assert "tq-003" in stored["id"] or stored["id"].startswith("tq-")


def test_custom_in_to_storage_maps_open_ended():
    item = CustomQuestionIn(
        prompt="Explain ACID",
        question_type=QuestionType.open_ended,
        correct_answer_or_rubric="Mentions atomicity",
        evaluated_competency="Databases",
        weight=4,
    )
    stored = custom_in_to_storage(item, 0)
    assert stored["text"] == "Explain ACID"
    assert stored["type"] == "open"
    assert stored["benchmark_rubric"] == "Mentions atomicity"
    assert stored["weight"] == 4


def test_create_body_to_storage_accepts_question_text_alias():
    body = TemplateQuestionCreate(
        question_text="Pick the join",
        evaluation_rubric="INNER JOIN",
        question_type=QuestionType.mcq,
        options=["INNER JOIN", "CROSS JOIN"],
    )
    stored = create_body_to_storage(body, 1)
    assert stored["text"] == "Pick the join"
    assert stored["type"] == "mcq"
    assert stored["correct_answer"] == "INNER JOIN"
    assert "INNER JOIN" in stored["options"]


def test_row_to_question_out_flattens_payload():
    qid = uuid4()
    tid = uuid4()
    row = SimpleNamespace(
        id=qid,
        template_id=tid,
        question_text="Q text",
        evaluation_rubric="rubric",
        question_payload={
            "type": "open",
            "builder_type": "open_ended",
            "options": [],
            "evaluated_competency": "SQL",
            "weight": 5,
        },
        is_active=True,
        position=2,
        created_at=None,
        updated_at=None,
    )
    out = row_to_question_out(row)
    assert out.id == qid
    assert out.question_type == "open_ended"
    assert out.evaluated_competency == "SQL"
    assert out.weight == 5


@pytest.mark.asyncio
async def test_add_template_eager_snapshot_copies_questions():
    package_id = uuid4()
    template_id = uuid4()
    catalog_qs = [
        {
            "id": "sql-01",
            "text": "What is INNER JOIN?",
            "type": "mcq",
            "options": ["A", "B"],
            "correct_answer": "A",
        }
    ]

    package = SimpleNamespace(id=package_id, status="draft")
    module = SimpleNamespace(
        id=template_id, is_active=True, questions=catalog_qs, title="SQL"
    )

    session = AsyncMock()
    # First execute: package lookup; second: module; third: template_questions;
    # fourth: existing PackageModule; fifth: max position
    package_result = MagicMock()
    package_result.scalar_one_or_none.return_value = package
    module_result = MagicMock()
    module_result.scalar_one_or_none.return_value = module
    tq_result = MagicMock()
    tq_result.scalars.return_value.all.return_value = []
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    pos_result = MagicMock()
    pos_result.scalar_one.return_value = -1

    session.execute = AsyncMock(
        side_effect=[
            package_result,
            module_result,
            module_result,  # snapshot_active_questions reloads module
            tq_result,
            existing_result,
            pos_result,
        ]
    )
    session.add = MagicMock()
    session.commit = AsyncMock()

    result = await LibraryService.add_template_to_package(session, package_id, template_id)

    assert result.package_id == package_id
    assert result.template_id == template_id
    assert result.question_count == 1
    assert result.questions[0]["text"] == "What is INNER JOIN?"
    assert result.created is True
    added = session.add.call_args[0][0]
    assert added.questions is not None
    assert added.questions[0]["text"] == "What is INNER JOIN?"
    # Isolation: mutated catalog must not change the already-built snapshot list
    catalog_qs[0]["text"] = "MUTATED"
    assert result.questions[0]["text"] == "What is INNER JOIN?"
    assert added.questions[0]["text"] == "What is INNER JOIN?"


@pytest.mark.asyncio
async def test_add_template_conflict_when_snapshot_exists():
    package_id = uuid4()
    template_id = uuid4()
    package = SimpleNamespace(id=package_id, status="draft")
    module = SimpleNamespace(id=template_id, is_active=True, questions=[])
    existing = SimpleNamespace(questions=[{"id": "q1", "text": "kept"}])

    session = AsyncMock()
    package_result = MagicMock()
    package_result.scalar_one_or_none.return_value = package
    module_result = MagicMock()
    module_result.scalar_one_or_none.return_value = module
    tq_result = MagicMock()
    tq_result.scalars.return_value.all.return_value = []
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing

    session.execute = AsyncMock(
        side_effect=[
            package_result,
            module_result,
            module_result,
            tq_result,
            existing_result,
        ]
    )

    with pytest.raises(LibraryConflictError):
        await LibraryService.add_template_to_package(session, package_id, template_id)


@pytest.mark.asyncio
async def test_sync_question_delegates_to_create_question():
    template_id = uuid4()
    body = CustomQuestionIn(
        prompt="New cherry pick",
        question_type=QuestionType.mcq,
        options=["A", "B"],
        correct_answer_or_rubric="A",
        weight=3,
    )
    expected = SimpleNamespace(id=uuid4(), question_text="New cherry pick")
    session = AsyncMock()

    with patch.object(
        LibraryService, "create_question", new_callable=AsyncMock, return_value=expected
    ) as create_mock:
        result = await LibraryService.sync_question(session, template_id, body)

    assert result is expected
    create_mock.assert_awaited_once()
    args = create_mock.await_args
    assert args.args[1] == template_id
    assert args.args[2].question_text == "New cherry pick"
    assert args.args[2].evaluation_rubric == "A"


def _module_row(
    template_id, *, is_active=True, title="SQL Basics", status="draft", version=1, lineage_id=None
):
    return SimpleNamespace(
        id=template_id,
        slug="sql-basics",
        title=title,
        description=None,
        module_kind="technical",
        assessment_category=None,
        time_limit_minutes=20,
        duration_seconds=1200,
        timer_mode="flexible",
        shuffle_questions=False,
        status=status,
        version=version,
        lineage_id=lineage_id or template_id,
        parent_module_id=None,
        published_at=None,
        questions=[],
        is_active=is_active,
        position=1,
        created_at=None,
        updated_at=None,
    )


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _count_result(n):
    result = MagicMock()
    result.scalar_one.return_value = n
    return result


def _empty_questions_result():
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    return result


def _detail_results(module, *, linked=0):
    """execute() results consumed by LibraryService.get_template."""
    return [_scalar_result(module), _empty_questions_result(), _count_result(linked)]


@pytest.mark.asyncio
async def test_archive_template_soft_deletes_when_no_live_packages():
    template_id = uuid4()
    module = _module_row(template_id)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(module), *_detail_results(module)])
    session.commit = AsyncMock()

    result = await LibraryService.archive_template(session, template_id)

    assert module.is_active is False
    assert result.is_active is False
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_archive_allowed_on_live_module_and_reports_links():
    """Live packages hold eager snapshots, so archive never destroys history."""
    template_id = uuid4()
    module = _module_row(template_id, title="Numerical Reasoning", status="published")
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_scalar_result(module), *_detail_results(module, linked=2)]
    )
    session.commit = AsyncMock()

    result = await LibraryService.archive_template(session, template_id)

    assert module.is_active is False
    assert result.linked_package_count == 2
    assert result.is_locked is True
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_link_count_only_counts_published_active_packages():
    template_id = uuid4()
    module = _module_row(template_id)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=_detail_results(module))

    await LibraryService.get_template(session, template_id)

    count_stmt = session.execute.await_args_list[2].args[0]
    compiled = str(count_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "packages.status = 'published'" in compiled
    assert "packages.is_active IS true" in compiled
    assert "package_modules.global_module_id" in compiled


@pytest.mark.asyncio
async def test_archive_template_is_idempotent_when_already_archived():
    template_id = uuid4()
    module = _module_row(template_id, is_active=False)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(module), *_detail_results(module)])
    session.commit = AsyncMock()

    result = await LibraryService.archive_template(session, template_id)

    assert result.is_active is False
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_archive_template_missing_raises_lookup():
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(None)])

    with pytest.raises(LookupError):
        await LibraryService.archive_template(session, uuid4())


@pytest.mark.asyncio
async def test_update_runner_config_on_published_module_raises_module_locked():
    template_id = uuid4()
    module = _module_row(template_id, status="published", version=3)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(module)])
    session.commit = AsyncMock()

    with pytest.raises(ModuleLockedError) as exc_info:
        await LibraryService.update_template(
            session, template_id, TemplateUpdate(duration_seconds=60)
        )

    assert exc_info.value.code == "MODULE_LOCKED"
    assert exc_info.value.version == 3
    assert "Clone it as v4" in str(exc_info.value)
    assert module.duration_seconds == 1200
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_runner_config_on_live_linked_draft_raises_module_locked():
    template_id = uuid4()
    module = _module_row(template_id)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(module), _count_result(1)])
    session.commit = AsyncMock()

    with pytest.raises(ModuleLockedError) as exc_info:
        await LibraryService.update_template(
            session, template_id, TemplateUpdate(timer_mode="strict")
        )

    assert "linked to 1 live package" in str(exc_info.value)
    assert isinstance(exc_info.value, LibraryConflictError)
    session.commit.assert_not_awaited()


def test_module_locked_maps_to_structured_409():
    from fastapi import HTTPException

    from app.api.v1.library import _raise_http

    module = _module_row(uuid4(), status="published", version=2)
    with pytest.raises(HTTPException) as exc_info:
        _raise_http(ModuleLockedError(module, "published"))
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["code"] == "MODULE_LOCKED"
    assert detail["version"] == 2
    assert detail["module_id"] == str(module.id)


@pytest.mark.asyncio
async def test_update_metadata_on_published_module_is_allowed():
    template_id = uuid4()
    module = _module_row(template_id, status="published")
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(module), *_detail_results(module)])
    session.commit = AsyncMock()

    result = await LibraryService.update_template(
        session, template_id, TemplateUpdate(title="Renamed")
    )

    assert result.title == "Renamed"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_question_on_published_module_raises_module_locked():
    template_id = uuid4()
    module = _module_row(template_id, status="published")
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(module)])
    session.commit = AsyncMock()
    body = TemplateQuestionCreate(
        payload={"type": "likert", "prompt": "I like teams", "reverse_scored": True}
    )

    with pytest.raises(ModuleLockedError):
        await LibraryService.create_question(session, template_id, body)
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_requires_at_least_one_question():
    template_id = uuid4()
    module = _module_row(template_id)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(module)])
    session.commit = AsyncMock()

    with patch.object(
        LibraryService, "rebuild_module_questions_json", AsyncMock(return_value=[])
    ):
        with pytest.raises(LibraryError, match="at least one question"):
            await LibraryService.publish_template(session, template_id)
    assert module.status == "draft"
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_sets_status_and_timestamp():
    template_id = uuid4()
    module = _module_row(template_id)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_scalar_result(module), *_detail_results(module)])
    session.commit = AsyncMock()

    with patch.object(
        LibraryService, "rebuild_module_questions_json", AsyncMock(return_value=[{"id": "q"}])
    ):
        result = await LibraryService.publish_template(session, template_id)

    assert module.status == "published"
    assert module.published_at is not None
    assert result.status == "published"
    assert result.is_locked is True


@pytest.mark.asyncio
async def test_clone_version_returns_existing_open_draft():
    lineage = uuid4()
    source = _module_row(uuid4(), status="published", version=1, lineage_id=lineage)
    draft = _module_row(uuid4(), status="draft", version=2, lineage_id=lineage)
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_scalar_result(source), _scalar_result(draft), *_detail_results(draft)]
    )
    session.add = MagicMock()

    result = await LibraryService.clone_version(session, source.id)

    assert result.id == draft.id
    assert result.version == 2
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_clone_version_increments_version_and_copies_questions():
    lineage = uuid4()
    source = _module_row(uuid4(), status="published", version=2, lineage_id=lineage)
    source.slug = "sql-basics-v2"
    question_row = SimpleNamespace(
        question_text="Q1",
        evaluation_rubric="",
        question_payload={"id": "tq-001", "type": "mcq", "options": ["a", "b"], "correct_keys": [0]},
    )
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [question_row]
    max_version = MagicMock()
    max_version.scalar_one.return_value = 2

    added: list = []
    session = AsyncMock()
    session.add = MagicMock(side_effect=added.append)
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(source),
            _scalar_result(None),
            max_version,
            _scalar_result(None),
            rows_result,
        ]
    )
    detail = SimpleNamespace(version=3)

    with (
        patch.object(LibraryService, "rebuild_module_questions_json", AsyncMock(return_value=[])),
        patch.object(LibraryService, "get_template", AsyncMock(return_value=detail)),
    ):
        result = await LibraryService.clone_version(session, source.id)

    clone, copied = added[0], added[1]
    assert result is detail
    assert clone.version == 3
    assert clone.status == "draft"
    assert clone.lineage_id == lineage
    assert clone.parent_module_id == source.id
    assert clone.slug == "sql-basics-v3"
    assert copied.template_id == clone.id
    assert copied.question_payload["correct_keys"] == [0]
    assert "id" not in copied.question_payload
    assert question_row.question_payload["id"] == "tq-001"
    session.commit.assert_awaited_once()


def test_eager_snapshot_logic_prefers_override_over_catalog():
    """Mirrors save_draft eager-snapshot selection without a live DB."""
    mid = uuid4()
    overrides = {str(mid): [{"id": "local", "text": "override"}]}
    catalog_by_id = {mid: [{"id": "cat", "text": "catalog"}]}

    override_qs = overrides.get(str(mid))
    if isinstance(override_qs, list):
        snapshot = list(override_qs)
    else:
        snapshot = catalog_by_id.get(mid, [])

    assert snapshot[0]["text"] == "override"

    overrides2: dict = {}
    override_qs2 = overrides2.get(str(mid))
    if isinstance(override_qs2, list):
        snapshot2 = list(override_qs2)
    else:
        snapshot2 = catalog_by_id.get(mid, [])
    assert snapshot2[0]["text"] == "catalog"
    assert snapshot2 is not None
