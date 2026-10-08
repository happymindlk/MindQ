"""Unit tests for client-package masking and pipeline status."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.services.client_package import (
    pipeline_status,
    public_review_questions,
    slugify_company_name,
    PackageLockedError,
    _strip_answer_keys,
)
from app.schemas.client_package import AdminPackageUpdateRequest, DraftPackageRequest, PackageUpdate


def test_strip_answer_keys_removes_scoring_fields():
    cleaned = _strip_answer_keys(
        {
            "id": "q1",
            "text": "What is INNER JOIN?",
            "type": "mcq",
            "options": ["A", "B"],
            "correct_answer": "A",
            "benchmark_rubric": "secret",
            "evaluated_competency": "SQL",
        }
    )
    assert cleaned["text"] == "What is INNER JOIN?"
    assert "correct_answer" not in cleaned
    assert "benchmark_rubric" not in cleaned
    assert cleaned["options"] == ["A", "B"]


def test_public_review_drops_psychometric_assessments():
    custom = []
    assessments = [
        SimpleNamespace(
            position=0,
            module_kind="psychometric",
            questions=[
                {
                    "id": "p1",
                    "text": "I stay calm under pressure.",
                    "type": "likert",
                    "correct_answer": "hidden",
                }
            ],
        ),
        SimpleNamespace(
            position=1,
            module_kind="technical",
            questions=[
                {
                    "id": "t1",
                    "text": "Which join is inner?",
                    "type": "mcq",
                    "options": ["INNER JOIN"],
                    "correct_answer": "INNER JOIN",
                    "builder_type": "mcq",
                    "evaluated_competency": "SQL",
                    "weight": 3,
                }
            ],
        ),
    ]
    items = public_review_questions(custom, assessments)
    assert len(items) == 1
    assert items[0].prompt == "Which join is inner?"
    assert items[0].id == "t1"
    assert items[0].options == ["INNER JOIN"]
    assert not hasattr(items[0], "weight") or "weight" not in items[0].model_dump()
    assert "weight" not in items[0].model_dump()


def test_public_review_prefers_custom_technical_questions():
    qid = uuid4()
    custom = [
        SimpleNamespace(
            id=qid,
            position=0,
            prompt="Explain CAP.",
            question_type="open_ended",
            options=[],
            evaluated_competency="Systems",
            weight=5,
            likert_label_1=None,
            likert_label_5=None,
        )
    ]
    assessments = [
        SimpleNamespace(
            position=0,
            module_kind="psychometric",
            questions=[{"id": "p1", "text": "secret psych item", "type": "likert"}],
        )
    ]
    items = public_review_questions(custom, assessments)
    assert len(items) == 1
    assert items[0].id == str(qid)
    assert items[0].prompt == "Explain CAP."
    assert "psych" not in items[0].prompt.lower()


def test_pipeline_status_pending_scoring_completed():
    assert pipeline_status(completed=0, total=3, logged_in=False, jd_fit=None) == "pending"
    assert pipeline_status(completed=1, total=3, logged_in=True, jd_fit=None) == "scoring"
    assert pipeline_status(completed=3, total=3, logged_in=True, jd_fit=None) == "scoring"
    assert pipeline_status(completed=3, total=3, logged_in=True, jd_fit=81.0) == "completed"


def test_slugify_company_name_strips_and_hyphenates():
    assert slugify_company_name("Acme Labs!") == "acme-labs"
    assert slugify_company_name("  Hello   World  ") == "hello-world"


def test_published_lock_message():
    err = PackageLockedError()
    assert str(err) == "Published packages are locked and cannot be modified."


def test_admin_package_update_accepts_questions_and_target_role_aliases():
    body = AdminPackageUpdateRequest.model_validate(
        {
            "title": "Analyst pack",
            "target_role": "Quant Analyst",
            "questions": [
                {"prompt": "Explain CAP theorem", "question_type": "open_ended"},
            ],
            "unknown_client_field": "ignored",
        }
    )
    assert body.target_role == "Quant Analyst"
    assert body.custom_questions is not None
    assert body.custom_questions[0].prompt.startswith("Explain CAP")

    blank = PackageUpdate.model_validate(
        {"title": "Analyst pack", "target_role": "", "passing_threshold": ""}
    )
    assert blank.target_role is None
    assert blank.passing_threshold is None


def test_draft_package_request_maps_questions_dict_to_overrides():
    module_id = str(uuid4())
    body = DraftPackageRequest.model_validate(
        {
            "corporate_id": str(uuid4()),
            "title": "Draft",
            "target_role": "",
            "passing_threshold": "",
            "questions": {module_id: [{"id": "q1", "prompt": "Stay calm"}]},
        }
    )
    assert body.target_role is None
    assert body.passing_threshold is None
    assert module_id in (body.module_question_overrides or {})
