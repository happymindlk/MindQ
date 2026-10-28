"""Tests for GET /api/v1/candidates/{id}/report-data."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import candidate_reports
from app.api.v1.candidate_reports import router
from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db
from app.schemas.jd_evaluation import ReportSynthesis

DONE = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


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


@pytest.fixture
def synthesis_stub(monkeypatch):
    """Replace catalog lookup, technical backfill, and Gemini with controllable stubs."""
    state: dict = {"result": (None, "skipped"), "calls": []}

    async def _get_or_evaluate(_db, **kwargs):
        state["calls"].append(kwargs)
        result = state["result"]
        if isinstance(result, Exception):
            raise result
        return result

    async def _catalog(_db, _assessments):
        return state.get("catalog", {})

    monkeypatch.setattr(
        candidate_reports.JdScoringService, "get_or_evaluate", staticmethod(_get_or_evaluate)
    )
    monkeypatch.setattr(candidate_reports, "load_catalog_categories", _catalog)
    monkeypatch.setattr(
        candidate_reports.TechnicalEvalService,
        "has_missing_open_evals",
        staticmethod(lambda *_a, **_k: False),
    )
    return state


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _client(app, results):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=results)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _candidate(candidate_id, corp_id, package_id):
    return SimpleNamespace(
        id=candidate_id,
        corporate_id=corp_id,
        package_id=package_id,
        full_name="Pat Lee",
        email="pat@ex.com",
    )


def test_report_data_forbids_other_tenant(app, corp_id, candidate_id):
    candidate = _candidate(candidate_id, uuid4(), uuid4())
    client = _client(app, [_scalar_result(candidate)])
    res = client.get(f"/api/v1/candidates/{candidate_id}/report-data")
    assert res.status_code == 403


def _full_fixture(candidate_id, corp_id):
    package_id = uuid4()
    big_five_gm = uuid4()
    tech_id = uuid4()
    custom_id = uuid4()
    big_five_id = uuid4()
    pending_id = uuid4()
    candidate = _candidate(candidate_id, corp_id, package_id)
    package = SimpleNamespace(id=package_id, target_role="Data Analyst", title="Analyst pack")
    corporate = SimpleNamespace(
        id=corp_id, name="Acme", logo_url="https://cdn.example.com/acme-logo.png"
    )
    assessments = [
        SimpleNamespace(
            id=big_five_id,
            title="Big Five",
            module_kind="psychometric",
            global_module_id=big_five_gm,
            questions=[{"id": "p1", "text": "I stay calm", "type": "likert", "trait": "N"}],
            position=0,
        ),
        SimpleNamespace(
            id=tech_id, title="SQL Basics", module_kind="technical",
            global_module_id=uuid4(), questions=[], position=1,
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
                {"id": "c2", "prompt": "Which isolation level?", "type": "mcq", "correct_answer": "A"},
            ],
            position=2,
        ),
        SimpleNamespace(
            id=pending_id, title="Not Started", module_kind="technical",
            global_module_id=None, questions=[], position=3,
        ),
    ]
    progress = [
        SimpleNamespace(
            assessment_id=big_five_id, score=None, status="COMPLETED", completed_at=DONE,
            facet_scores={"N": {"mean": 4.0, "n": 2}},
        ),
        SimpleNamespace(
            assessment_id=tech_id, score=80, status="COMPLETED", completed_at=DONE, facet_scores=None
        ),
        SimpleNamespace(
            assessment_id=custom_id, score=90, status="COMPLETED", completed_at=DONE, facet_scores=None
        ),
        SimpleNamespace(
            assessment_id=pending_id, score=None, status="IN_PROGRESS", completed_at=None, facet_scores=None
        ),
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
        SimpleNamespace(assessment_id=custom_id, question_id="c2", response={"answer": "A"}),
    ]
    results = [
        _scalar_result(candidate),
        _scalar_result(package),
        _scalar_result(corporate),
        _scalars_result(assessments),
        _scalars_result(progress),
        _scalars_result(responses),
    ]
    return results, big_five_gm


SYNTHESIS = ReportSynthesis.model_validate(
    {
        "executive_summary": "Strong SQL fundamentals with calm temperament.",
        "strengths": ["Solid indexing rationale."],
        "risks_and_antipatterns": ["Light on isolation trade-offs."],
        "competency_breakdown": [
            {"assessment_key": "A1", "assessment_name": "Big Five", "performance_summary": "Calm and steady."},
            {"assessment_key": "A2", "assessment_name": "SQL Basics", "performance_summary": "Strong SQL. Hire now."},
        ],
        "category_summaries": [
            {"category": "Personality", "summary": "Calm and steady under pressure."},
        ],
    }
)


def test_report_data_returns_mindq_report_shape(app, corp_id, candidate_id, synthesis_stub):
    results, big_five_gm = _full_fixture(candidate_id, corp_id)
    synthesis_stub["catalog"] = {big_five_gm: "personality"}
    synthesis_stub["result"] = (SYNTHESIS, "generated")
    res = _client(app, results).get(f"/api/v1/candidates/{candidate_id}/report-data")
    assert res.status_code == 200
    body = res.json()

    assert body["candidate_full_name"] == "Pat Lee"
    assert body["candidate_email"] == "pat@ex.com"
    assert body["target_role"] == "Data Analyst"
    assert body["total_assessments_completed"] == 3
    assert body["category_averages"] is None
    assert body["executive_summary"] == "Strong SQL fundamentals with calm temperament."
    assert body["strengths"] == ["Solid indexing rationale."]
    assert body["risks_and_antipatterns"] == ["Light on isolation trade-offs."]
    assert body["synthesis_status"] == "ok"
    assert body["company_logo_url"] == "https://cdn.example.com/acme-logo.png"

    breakdown = body["competency_breakdown"]
    assert [(b["category"], b["assessment_name"], b["score"]) for b in breakdown] == [
        ("Personality", "Big Five", None),
        ("Technical", "SQL Basics", 80.0),
        ("Technical", "Custom Technical", 90.0),
    ]
    assert breakdown[0]["score_kind"] == "traits"
    assert breakdown[0]["subscales"][0]["name"] == "Emotional stability"
    assert breakdown[0]["subscales"][0]["position_pct"] == 25.0
    assert breakdown[1]["performance_summary"] == "Strong SQL."
    assert breakdown[2]["performance_summary"].startswith("Pat scored 90% on Custom Technical")
    assert body["category_summaries"] == [
        {"category": "Personality", "summary": "Calm and steady under pressure."}
    ]

    for forbidden in ("overall_fit", "recommendation_key", "recommendation_label", "jd_fit"):
        assert forbidden not in body

    assert len(body["custom_questions"]) == 2
    cq = next(q for q in body["custom_questions"] if q["id"] == "c1")
    assert cq["ai_evaluation"] == "Clear explanation of B-tree indexes."
    assert cq["score"] == 86.0
    assert cq["scorecard"] == ["Correctness: strong"]
    assert "correct_answer" not in str(body)
    assert "secret" not in str(body)
    assert "I stay calm" not in str(body)

    passed = synthesis_stub["calls"][0]["outcomes"]
    assert [o.key for o in passed] == ["A1", "A2", "A3"]


def test_report_data_falls_back_when_synthesis_fails(app, corp_id, candidate_id, synthesis_stub):
    results, _gm = _full_fixture(candidate_id, corp_id)
    synthesis_stub["result"] = RuntimeError("503 UNAVAILABLE")
    res = _client(app, results).get(f"/api/v1/candidates/{candidate_id}/report-data")
    assert res.status_code == 200
    body = res.json()
    assert body["synthesis_status"] == "failed"
    assert body["executive_summary"] == ""
    assert body["strengths"] == []
    assert body["risks_and_antipatterns"] == []
    assert len(body["competency_breakdown"]) == 3
    assert all(b["performance_summary"] for b in body["competency_breakdown"])
    # Pillar summaries fall back to server-computed prose when synthesis fails.
    assert [s["category"] for s in body["category_summaries"]] == ["Personality"]
    assert "Big Five" in body["category_summaries"][0]["summary"]
    assert "averaged 75" not in body["category_summaries"][0]["summary"]


def test_report_data_skipped_synthesis_status(app, corp_id, candidate_id, synthesis_stub):
    results, _gm = _full_fixture(candidate_id, corp_id)
    synthesis_stub["result"] = (None, "skipped")
    body = _client(app, results).get(f"/api/v1/candidates/{candidate_id}/report-data").json()
    assert body["synthesis_status"] == "skipped"


def test_report_data_filters_localhost_logo(app, corp_id, candidate_id, synthesis_stub):
    package_id = uuid4()
    custom_id = uuid4()
    candidate = _candidate(candidate_id, corp_id, package_id)
    package = SimpleNamespace(id=package_id, target_role=None, title="Analyst pack")
    corporate = SimpleNamespace(
        id=corp_id,
        name="Acme",
        logo_url="http://127.0.0.1:54321/storage/v1/object/public/logos/x.png",
    )
    assessments = [
        SimpleNamespace(
            id=custom_id, title="Custom Technical", module_kind="technical",
            global_module_id=None, questions=[{"id": "c1", "prompt": "Q", "type": "open_ended"}],
            position=0,
        )
    ]
    progress = [
        SimpleNamespace(
            assessment_id=custom_id, score=50, status="COMPLETED", completed_at=None, facet_scores=None
        )
    ]
    responses = [
        SimpleNamespace(
            assessment_id=custom_id,
            question_id="c1",
            response={"answer": "x", "ai_score": 50, "ai_evaluation": "ok", "ai_eval_status": "ok"},
        )
    ]
    client = _client(
        app,
        [
            _scalar_result(candidate),
            _scalar_result(package),
            _scalar_result(corporate),
            _scalars_result(assessments),
            _scalars_result(progress),
            _scalars_result(responses),
        ],
    )
    body = client.get(f"/api/v1/candidates/{candidate_id}/report-data").json()
    assert body["company_logo_url"] is None
    assert body["target_role"] == "Analyst pack"


def test_report_data_with_no_completed_assessments(app, corp_id, candidate_id, synthesis_stub):
    package_id = uuid4()
    candidate = _candidate(candidate_id, corp_id, package_id)
    package = SimpleNamespace(id=package_id, target_role="Analyst", title="Pack")
    corporate = SimpleNamespace(id=corp_id, name="Acme", logo_url=None)
    client = _client(
        app,
        [
            _scalar_result(candidate),
            _scalar_result(package),
            _scalar_result(corporate),
            _scalars_result([]),
            _scalars_result([]),
            _scalars_result([]),
        ],
    )
    body = client.get(f"/api/v1/candidates/{candidate_id}/report-data").json()
    assert body["total_assessments_completed"] == 0
    assert body["category_averages"] is None
    assert body["competency_breakdown"] == []
    assert body["completed_at"] is None


def test_report_data_includes_failed_ai_eval_keys(app, corp_id, candidate_id, synthesis_stub):
    """Failed Gemini grading must still surface non-null ai_evaluation + status."""
    package_id = uuid4()
    custom_id = uuid4()
    candidate = _candidate(candidate_id, corp_id, package_id)
    package = SimpleNamespace(id=package_id, target_role="Analyst", title="Pack")
    corporate = SimpleNamespace(id=corp_id, name="Acme", logo_url=None)
    assessments = [
        SimpleNamespace(
            id=custom_id,
            title="Custom Technical",
            module_kind="technical",
            global_module_id=None,
            questions=[
                {"id": "c1", "prompt": "Explain indexes", "type": "open_ended", "evaluated_competency": "SQL"}
            ],
            position=0,
        ),
    ]
    progress = [
        SimpleNamespace(
            assessment_id=custom_id, score=None, status="COMPLETED", completed_at=None, facet_scores=None
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
                    "Evaluation pending or unavailable due to temporary upstream provider latency."
                ),
                "ai_eval_status": "failed",
                "ai_eval_error": "503",
            },
        )
    ]
    client = _client(
        app,
        [
            _scalar_result(candidate),
            _scalar_result(package),
            _scalar_result(corporate),
            _scalars_result(assessments),
            _scalars_result(progress),
            _scalars_result(responses),
        ],
    )
    res = client.get(f"/api/v1/candidates/{candidate_id}/report-data")
    assert res.status_code == 200
    body = res.json()
    cq = body["custom_questions"][0]
    assert "latency" in cq["ai_evaluation"]
    assert cq["score"] is None
    assert cq["ai_eval_status"] == "failed"
    assert body["total_assessments_completed"] == 1
    assert body["competency_breakdown"] == []
    assert body["category_averages"] is None
