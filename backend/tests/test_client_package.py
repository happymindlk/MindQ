"""Unit tests for client-package masking and pipeline status."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.client_package import (
    pipeline_status,
    public_review_questions,
    slugify_company_name,
    PackageLockedError,
    _draft_response,
    _publish_response,
    _strip_answer_keys,
)
from app.schemas.client_package import (
    AdminPackageUpdateRequest,
    DraftPackageRequest,
    PackageUpdate,
    PublishPackageResponse,
)


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
    assert pipeline_status(completed=0, total=3, logged_in=False, evaluated=False) == "pending"
    assert pipeline_status(completed=1, total=3, logged_in=True, evaluated=False) == "scoring"
    # Module completion alone marks Completed; report synthesis must not gate it.
    assert pipeline_status(completed=3, total=3, logged_in=True, evaluated=False) == "completed"
    assert pipeline_status(completed=3, total=3, logged_in=True, evaluated=True) == "completed"
    assert pipeline_status(completed=1, total=3, logged_in=True, evaluated=True) == "scoring"


def test_slugify_company_name_strips_and_hyphenates():
    assert slugify_company_name("Acme Labs!") == "acme-labs"
    assert slugify_company_name("  Hello   World  ") == "hello-world"


def test_published_lock_message():
    err = PackageLockedError()
    assert str(err) == "Package is published and locked"


def _published_package(**overrides):
    base = dict(
        id=uuid4(),
        corporate_id=uuid4(),
        title="Ops Analyst Suite",
        description=None,
        target_role="Analyst",
        status="published",
        is_active=True,
        access_code="HM-TEST01-C",
        review_token="review-token-abc",
        track_secret="track-secret",
        published_at=datetime.now(timezone.utc),
        open_time=datetime(2026, 11, 5, 12, 26, tzinfo=timezone.utc),
        close_time=datetime(2026, 11, 6, 2, 30, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_publish_response_does_not_duplicate_draft_kwargs():
    """Published dump already carries access_code/review_*; re-passing them 500s.

    Regression: ``PublishPackageResponse(**draft.model_dump(), access_code=...)``
    raised ``TypeError: multiple values for keyword argument`` *after* commit, so
    the package was published while the UI showed Internal server error.
    """
    package = _published_package()
    module_ids = [uuid4(), uuid4()]

    with pytest.raises(TypeError, match="multiple values for keyword argument"):
        PublishPackageResponse(
            **_draft_response(package, module_ids, [], published=True).model_dump(),
            access_code=package.access_code,
            review_token=package.review_token,
            review_path=f"/client/review/{package.review_token}",
            candidate_path=f"/portal?code={package.access_code}",
        )

    resp = _publish_response(package, module_ids, [])
    assert resp.access_code == "HM-TEST01-C"
    assert resp.review_token == "review-token-abc"
    assert resp.review_path == "/client/review/review-token-abc"
    assert resp.candidate_path == "/portal?code=HM-TEST01-C"
    assert resp.status == "published"
    assert resp.module_ids == module_ids


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

    blank = PackageUpdate.model_validate({"title": "Analyst pack", "target_role": ""})
    assert blank.target_role is None
    assert not hasattr(blank, "passing_threshold")


def test_draft_package_request_maps_questions_dict_to_overrides():
    module_id = str(uuid4())
    body = DraftPackageRequest.model_validate(
        {
            "corporate_id": str(uuid4()),
            "title": "Draft",
            "target_role": "",
            "questions": {module_id: [{"id": "q1", "prompt": "Stay calm"}]},
        }
    )
    assert body.target_role is None
    assert not hasattr(body, "passing_threshold")
    assert module_id in (body.module_question_overrides or {})
