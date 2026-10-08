"""Tests for GET /api/v1/candidates/{id}/report-data."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.candidate_reports import router
from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db


@pytest.fixture
def corp_id():
    return uuid4()


@pytest.fixture
def candidate_id():
    return uuid4()


@pytest.fixture
def app(corp_id):
    application = FastAPI()
    application.include_router(router, prefix="/api/v1/candidates")

    async def _hr():
        return HRUserContext(
            user_id=uuid4(),
            corporate_id=corp_id,
            email="hr@test.com",
            role="hr",
        )

    async def _db():
        yield MagicMock()

    application.dependency_overrides[get_current_hr_user] = _hr
    application.dependency_overrides[get_db] = _db
    return application


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def test_report_data_forbids_other_tenant(app, corp_id, candidate_id):
    other = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id,
        corporate_id=other,
        package_id=uuid4(),
        full_name="Pat",
        email="pat@ex.com",
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=_scalar_result(candidate))

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    client = TestClient(app)
    res = client.get(f"/api/v1/candidates/{candidate_id}/report-data")
    assert res.status_code == 403


def test_report_data_includes_ai_evaluation(app, corp_id, candidate_id):
    package_id = uuid4()
    tech_id = uuid4()
    custom_id = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id,
        corporate_id=corp_id,
        package_id=package_id,
        full_name="Pat Lee",
        email="pat@ex.com",
    )
    package = SimpleNamespace(id=package_id, target_role="Analyst")
    corporate = SimpleNamespace(
        id=corp_id,
        name="Acme",
        logo_url="https://cdn.example.com/acme-logo.png",
    )
    assessments = [
        SimpleNamespace(
            id=uuid4(),
            title="Big Five",
            module_kind="psychometric",
            global_module_id=uuid4(),
            questions=[{"id": "p1", "text": "I stay calm", "trait": "N"}],
            position=0,
        ),
        SimpleNamespace(
            id=tech_id,
            title="SQL Basics",
            module_kind="technical",
            global_module_id=uuid4(),
            questions=[],
            position=1,
        ),
        SimpleNamespace(
            id=custom_id,
            title="Custom Technical",
            module_kind="technical",
            global_module_id=None,
            questions=[
                {
                    "id": "c1",
                    "prompt": "Explain indexes",
                    "type": "open_ended",
                    "correct_answer_or_rubric": "secret",
                    "evaluated_competency": "SQL",
                },
                {
                    "id": "c2",
                    "prompt": "Which isolation level?",
                    "type": "mcq",
                    "correct_answer": "A",
                },
            ],
            position=2,
        ),
    ]
    progress = [
        SimpleNamespace(
            assessment_id=tech_id,
            score=80,
            status="COMPLETED",
            completed_at=None,
        )
    ]
    responses = [
        SimpleNamespace(
            assessment_id=custom_id,
            question_id="c1",
            response={
                "answer": "B-trees",
                "ai_score": 86,
                "ai_evaluation": "Clear explanation of B-tree indexes.",
                "ai_eval_status": "ok",
                "scorecard": ["Correctness: strong"],
            },
        ),
        SimpleNamespace(
            assessment_id=custom_id,
            question_id="c2",
            response={"answer": "A"},
        ),
    ]
    evaluation = SimpleNamespace(
        payload={
            "overall_fit": 78,
            "hiring_recommendation": "strong_hire",
            "summary": "Strong SQL fundamentals.",
            "strengths": ["Solid indexing rationale"],
            "risks": ["Light on isolation trade-offs"],
            "competencies": [
                {"name": "SQL", "score": 82},
                {"name": "Systems", "score": 70},
            ],
            "per_assessment": [
                {"title": "Custom Technical", "fit": 78, "notes": "Solid open-ended depth."}
            ],
        }
    )

    call_results = [
        _scalar_result(candidate),
        _scalar_result(package),
        _scalar_result(corporate),
        _scalars_result(assessments),
        _scalars_result(progress),
        _scalars_result(responses),
        _scalar_result(evaluation),
    ]
    db = MagicMock()
    db.execute = AsyncMock(side_effect=call_results)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    client = TestClient(app)
    res = client.get(f"/api/v1/candidates/{candidate_id}/report-data")
    assert res.status_code == 200
    payload = res.json()
    assert payload["ai_summary"] == "Strong SQL fundamentals."
    assert payload["overall_fit"] == 78.0
    assert payload["recommendation_key"] == "strong_hire"
    assert payload["recommendation_label"] == "Strong Hire"
    assert payload["strengths"] == ["Solid indexing rationale"]
    assert payload["risks"] == ["Light on isolation trade-offs"]
    assert payload["competencies"] == [
        {"name": "SQL", "score": 82.0},
        {"name": "Systems", "score": 70.0},
    ]
    assert payload["mcq_score"] == 100.0
    assert payload["company_logo_url"] == "https://cdn.example.com/acme-logo.png"
    assert "Big Five" not in [m["title"] for m in payload["modules"]]
    assert len(payload["custom_questions"]) == 2
    cq = next(q for q in payload["custom_questions"] if q["id"] == "c1")
    assert cq["prompt"] == "Explain indexes"
    assert cq["ai_evaluation"] == "Clear explanation of B-tree indexes."
    assert cq["score"] == 86.0
    assert cq["ai_eval_status"] == "ok"
    assert cq["scorecard"] == ["Correctness: strong"]
    assert cq["response_summary"] == "B-trees"
    assert "correct_answer" not in str(payload)
    assert "trait" not in str(payload)


def test_report_data_filters_localhost_logo(app, corp_id, candidate_id):
    package_id = uuid4()
    custom_id = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id,
        corporate_id=corp_id,
        package_id=package_id,
        full_name="Pat Lee",
        email="pat@ex.com",
    )
    package = SimpleNamespace(id=package_id, target_role="Analyst")
    corporate = SimpleNamespace(
        id=corp_id,
        name="Acme",
        logo_url="http://127.0.0.1:54321/storage/v1/object/public/logos/x.png",
    )
    assessments = [
        SimpleNamespace(
            id=custom_id,
            title="Custom Technical",
            module_kind="technical",
            global_module_id=None,
            questions=[{"id": "c1", "prompt": "Q", "type": "open_ended"}],
            position=0,
        )
    ]
    progress = [
        SimpleNamespace(
            assessment_id=custom_id, score=50, status="COMPLETED", completed_at=None
        )
    ]
    responses = [
        SimpleNamespace(
            assessment_id=custom_id,
            question_id="c1",
            response={"answer": "x", "ai_score": 50, "ai_evaluation": "ok", "ai_eval_status": "ok"},
        )
    ]
    evaluation = SimpleNamespace(payload={"summary": "Brief"})

    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(candidate),
            _scalar_result(package),
            _scalar_result(corporate),
            _scalars_result(assessments),
            _scalars_result(progress),
            _scalars_result(responses),
            _scalar_result(evaluation),
        ]
    )

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    client = TestClient(app)
    res = client.get(f"/api/v1/candidates/{candidate_id}/report-data")
    assert res.status_code == 200
    assert res.json()["company_logo_url"] is None


def test_report_data_includes_failed_ai_eval_keys(app, corp_id, candidate_id):
    """Failed Gemini grading must still surface non-null ai_evaluation + status."""
    package_id = uuid4()
    custom_id = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id,
        corporate_id=corp_id,
        package_id=package_id,
        full_name="Pat Lee",
        email="pat@ex.com",
    )
    package = SimpleNamespace(id=package_id, target_role="Analyst")
    corporate = SimpleNamespace(id=corp_id, name="Acme", logo_url=None)
    assessments = [
        SimpleNamespace(
            id=custom_id,
            title="Custom Technical",
            module_kind="technical",
            global_module_id=None,
            questions=[
                {
                    "id": "c1",
                    "prompt": "Explain indexes",
                    "type": "open_ended",
                    "evaluated_competency": "SQL",
                }
            ],
            position=0,
        ),
    ]
    progress = [
        SimpleNamespace(
            assessment_id=custom_id,
            score=None,
            status="COMPLETED",
            completed_at=None,
        )
    ]
    responses = [
        SimpleNamespace(
            assessment_id=custom_id,
            question_id="c1",
            response={
                "answer": "B-trees",
                "ai_score": None,
                "ai_evaluation": (
                    "Evaluation pending or unavailable due to temporary "
                    "upstream provider latency."
                ),
                "ai_eval_status": "failed",
                "ai_eval_error": "503",
            },
        )
    ]

    call_results = [
        _scalar_result(candidate),
        _scalar_result(package),
        _scalar_result(corporate),
        _scalars_result(assessments),
        _scalars_result(progress),
        _scalars_result(responses),
        _scalar_result(None),
    ]
    db = MagicMock()
    db.execute = AsyncMock(side_effect=call_results)

    async def _db():
        yield db

    from app.services.jd_scoring import JdScoringService
    from app.services.technical_eval import TechnicalEvalService

    original_has_missing = TechnicalEvalService.has_missing_open_evals

    def _no_missing(*_a, **_k):
        return False

    TechnicalEvalService.has_missing_open_evals = staticmethod(_no_missing)

    async def _jd_skip(*_a, **_k):
        return None, "skipped"

    original_jd = JdScoringService.get_or_evaluate
    JdScoringService.get_or_evaluate = staticmethod(_jd_skip)

    try:
        app.dependency_overrides[get_db] = _db
        client = TestClient(app)
        res = client.get(f"/api/v1/candidates/{candidate_id}/report-data")
    finally:
        TechnicalEvalService.has_missing_open_evals = original_has_missing
        JdScoringService.get_or_evaluate = original_jd

    assert res.status_code == 200
    body = res.json()
    cq = body["custom_questions"][0]
    assert cq["ai_evaluation"] is not None
    assert "latency" in cq["ai_evaluation"]
    assert cq["score"] is None
    assert cq["ai_eval_status"] == "failed"
    assert body["overall_fit"] is None
    assert body["recommendation_key"] is None
    assert body["strengths"] == []
    assert body["risks"] == []
    assert body["competencies"] == []
