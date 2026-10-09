from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.exceptions import (
    AssessmentAlreadySubmittedError,
    AssessmentNotFoundError,
    AssessmentTimeExpiredError,
)
from app.schemas.candidate import CandidateQuestion, CandidateTestResponse, strip_answer_keys
from app.services.candidate_service import CandidateService, ensure_not_submitted
from app.api.v1.candidate import _raise_integrity
from app.auth import get_current_candidate
from app.database import get_db
from app.main import app


LEAKY_QUESTION = {
    "id": "q1",
    "text": "What is 2+2?",
    "type": "mcq",
    "options": ["3", "4"],
    "correct_answer": "4",
    "is_correct": True,
}


def test_candidate_question_drops_answer_keys():
    question = CandidateQuestion.model_validate(LEAKY_QUESTION)
    dumped = question.model_dump()
    assert "correct_answer" not in dumped
    assert "is_correct" not in dumped
    assert dumped["id"] == "q1"
    assert dumped["options"] == ["3", "4"]


def test_candidate_test_response_strips_nested_keys():
    payload = CandidateTestResponse.model_validate(
        {
            "id": uuid4(),
            "title": "Math",
            "description": None,
            "time_limit_minutes": 10,
            "questions": [LEAKY_QUESTION],
        }
    )
    dumped = payload.model_dump()
    assert "correct_answer" not in dumped["questions"][0]
    assert "is_correct" not in dumped["questions"][0]


def test_ensure_not_submitted_allows_in_progress():
    ensure_not_submitted(None)
    ensure_not_submitted(SimpleNamespace(status="IN_PROGRESS"))
    ensure_not_submitted(SimpleNamespace(status="NOT_STARTED"))


def test_ensure_not_submitted_locks_completed():
    with pytest.raises(AssessmentAlreadySubmittedError) as exc:
        ensure_not_submitted(SimpleNamespace(status="COMPLETED"))
    assert str(exc.value) == "Assessment already completed. Modifications are locked."


def test_strip_answer_keys_pops_without_mutating_source():
    source = [dict(LEAKY_QUESTION)]
    source[0]["benchmark_rubric"] = "secret rubric"
    source[0]["correct_answer_or_rubric"] = "also secret"
    source[0]["allow_multiple"] = True
    sanitized = strip_answer_keys(source)
    assert "correct_answer" not in sanitized[0]
    assert "benchmark_rubric" not in sanitized[0]
    assert "correct_answer_or_rubric" not in sanitized[0]
    assert sanitized[0].get("allow_multiple") is True
    assert source[0]["correct_answer"] == "4"
    assert source[0]["benchmark_rubric"] == "secret rubric"
    assert source[0]["correct_answer_or_rubric"] == "also secret"


def test_answers_from_responses_extracts_values():
    rows = [
        SimpleNamespace(question_id="q1", response={"answer": "4"}),
        SimpleNamespace(question_id="q2", response={"value": 3}),
        SimpleNamespace(question_id="q3", response={"answer": ""}),
    ]
    assert CandidateService.answers_from_responses(rows) == {"q1": "4", "q2": 3}


def test_raise_integrity_409_contract():
    with pytest.raises(HTTPException) as exc:
        _raise_integrity(AssessmentAlreadySubmittedError())
    assert exc.value.status_code == 409
    assert exc.value.detail == "Assessment already completed. Modifications are locked."


def test_raise_integrity_404_contract():
    with pytest.raises(HTTPException) as exc:
        _raise_integrity(AssessmentNotFoundError())
    assert exc.value.status_code == 404
    assert exc.value.detail == "Test not found"


@pytest.fixture
def candidate_client(async_client):
    fake_candidate = SimpleNamespace(
        id=uuid4(),
        corporate_id=uuid4(),
        package_id=uuid4(),
    )

    async def _candidate():
        return fake_candidate

    async def _db():
        yield None

    app.dependency_overrides[get_current_candidate] = _candidate
    app.dependency_overrides[get_db] = _db
    try:
        yield async_client, fake_candidate
    finally:
        app.dependency_overrides.clear()


def _assessment(assessment_id, questions=None):
    return SimpleNamespace(
        id=assessment_id,
        title="Math",
        description="desc",
        time_limit_minutes=15,
        questions=questions or [LEAKY_QUESTION],
    )


@pytest.mark.asyncio
async def test_get_test_response_omits_answer_keys(candidate_client, monkeypatch):
    client, _ = candidate_client
    assessment_id = uuid4()
    fake = _assessment(assessment_id)

    async def require_writable(session, candidate, aid):
        assert aid == assessment_id
        return fake, None

    async def saved_answers(session, candidate_id, aid):
        assert aid == assessment_id
        return {"q1": "4"}

    async def ensure_started(session, candidate, assessment, progress):
        return SimpleNamespace(started_at=None)

    monkeypatch.setattr(CandidateService, "require_writable_assessment", require_writable)
    monkeypatch.setattr(CandidateService, "get_saved_answers", saved_answers)
    monkeypatch.setattr(CandidateService, "ensure_started", ensure_started)
    response = await client.get(f"/api/v1/candidate/test/{assessment_id}")
    assert response.status_code == 200
    body = response.json()
    question = body["questions"][0]
    assert question["text"] == "What is 2+2?"
    assert "correct_answer" not in question
    assert "is_correct" not in question
    assert body["answers"] == {"q1": "4"}


SERVER_ONLY_QUESTIONS = [
    {
        "id": "sjt1",
        "text": "A teammate misses a deadline.",
        "type": "sjt",
        "options": ["Escalate", "Help", "Ignore", "Blame"],
        "option_weights": [1, 3, 0, 0],
        "sme_rationale": "Help is the keyed best response.",
        "facet": "Teamwork",
        "media_url": "https://example.supabase.co/storage/v1/object/public/assessment-media/a.png",
    },
    {
        "id": "mcq1",
        "text": "Pick primes",
        "type": "mcq",
        "options": ["2", "4", "5"],
        "allow_multiple": True,
        "correct_keys": [0, 2],
        "correct_answer": ["2", "5"],
    },
    {
        "id": "crt1",
        "text": "Bat and ball",
        "type": "crt",
        "accepted_answers": ["5", "0.05"],
        "match": "numeric",
    },
    {
        "id": "lik1",
        "text": "I enjoy parties",
        "type": "likert",
        "reverse_scored": True,
        "likert_label_1": "Never",
        "likert_label_5": "Always",
    },
]


@pytest.mark.asyncio
async def test_get_test_never_leaks_weights_rationale_or_keys(candidate_client, monkeypatch):
    client, _ = candidate_client
    assessment_id = uuid4()
    fake = SimpleNamespace(
        id=assessment_id,
        title="Mixed",
        description=None,
        time_limit_minutes=None,
        duration_seconds=180,
        timer_mode="strict",
        shuffle_questions=False,
        questions=SERVER_ONLY_QUESTIONS,
    )

    async def require_writable(session, candidate, aid):
        return fake, None

    async def saved_answers(session, candidate_id, aid):
        return {}

    async def ensure_started(session, candidate, assessment, progress):
        return SimpleNamespace(started_at=None)

    monkeypatch.setattr(CandidateService, "require_writable_assessment", require_writable)
    monkeypatch.setattr(CandidateService, "get_saved_answers", saved_answers)
    monkeypatch.setattr(CandidateService, "ensure_started", ensure_started)
    response = await client.get(f"/api/v1/candidate/test/{assessment_id}")
    assert response.status_code == 200
    body = response.json()
    raw = response.text
    for secret in (
        "option_weights",
        "sme_rationale",
        "correct_keys",
        "correct_answer",
        "accepted_answers",
        "reverse_scored",
        "keyed best response",
        "0.05",
    ):
        assert secret not in raw, secret
    by_id = {q["id"]: q for q in body["questions"]}
    assert by_id["sjt1"]["media_url"].endswith("/assessment-media/a.png")
    assert by_id["lik1"]["likert_label_5"] == "Always"
    assert body["duration_seconds"] == 180
    assert body["timer_mode"] == "strict"


@pytest.mark.asyncio
async def test_get_test_409_when_already_submitted(candidate_client, monkeypatch):
    client, _ = candidate_client
    assessment_id = uuid4()

    async def require_writable(session, candidate, aid):
        raise AssessmentAlreadySubmittedError()

    monkeypatch.setattr(CandidateService, "require_writable_assessment", require_writable)
    response = await client.get(f"/api/v1/candidate/test/{assessment_id}")
    assert response.status_code == 409
    assert response.json() == {"detail": "Assessment already completed. Modifications are locked."}


@pytest.mark.asyncio
async def test_autosave_409_when_already_submitted(candidate_client, monkeypatch):
    client, _ = candidate_client

    async def autosave(session, candidate, save_data):
        raise AssessmentAlreadySubmittedError()

    monkeypatch.setattr(CandidateService, "autosave_response", autosave)
    response = await client.post(
        "/api/v1/candidate/autosave",
        json={
            "assessment_id": str(uuid4()),
            "question_id": "q1",
            "response": {"answer": "4"},
        },
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Assessment already completed. Modifications are locked."}


@pytest.mark.asyncio
async def test_autosave_409_time_expired_is_structured(candidate_client, monkeypatch):
    client, _ = candidate_client

    async def autosave(session, candidate, save_data):
        raise AssessmentTimeExpiredError()

    monkeypatch.setattr(CandidateService, "autosave_response", autosave)
    response = await client.post(
        "/api/v1/candidate/autosave",
        json={"assessment_id": str(uuid4()), "question_id": "q1", "response": {"answer": "4"}},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TIME_EXPIRED"


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed", [-1, 86_401])
async def test_autosave_rejects_out_of_bounds_elapsed(candidate_client, elapsed):
    client, _ = candidate_client
    response = await client.post(
        "/api/v1/candidate/autosave",
        json={
            "assessment_id": str(uuid4()),
            "question_id": "q1",
            "response": {"answer": "4"},
            "elapsed_seconds": elapsed,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_autosave_404_when_not_in_package(candidate_client, monkeypatch):
    client, _ = candidate_client

    async def autosave(session, candidate, save_data):
        raise AssessmentNotFoundError()

    monkeypatch.setattr(CandidateService, "autosave_response", autosave)
    response = await client.post(
        "/api/v1/candidate/autosave",
        json={
            "assessment_id": str(uuid4()),
            "question_id": "q1",
            "response": {"answer": "4"},
        },
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Test not found"}


@pytest.mark.asyncio
async def test_submit_409_when_already_submitted(candidate_client, monkeypatch):
    client, _ = candidate_client
    assessment_id = uuid4()

    async def submit(session, candidate, aid, pending_responses=None, client_duration_seconds=None):
        raise AssessmentAlreadySubmittedError()

    monkeypatch.setattr(CandidateService, "submit_test", submit)
    response = await client.post(f"/api/v1/candidate/test/{assessment_id}/submit")
    assert response.status_code == 409
    assert response.json() == {"detail": "Assessment already completed. Modifications are locked."}


@pytest.mark.asyncio
async def test_submit_passes_pending_responses_atomically(candidate_client, monkeypatch):
    client, _ = candidate_client
    assessment_id = uuid4()
    captured = {}

    async def submit(session, candidate, aid, pending_responses=None, client_duration_seconds=None):
        captured["aid"] = aid
        captured["pending"] = pending_responses
        captured["client_duration"] = client_duration_seconds
        progress = SimpleNamespace(
            assessment_id=aid,
            status="COMPLETED",
            score=100.0,
            completed_at=SimpleNamespace(isoformat=lambda: "2026-09-17T12:00:00+00:00"),
        )
        return progress, False

    monkeypatch.setattr(CandidateService, "submit_test", submit)

    async def _noop_score(*_a, **_k):
        return None

    monkeypatch.setattr(
        "app.api.v1.candidate.score_ai_for_candidate",
        _noop_score,
    )
    response = await client.post(
        f"/api/v1/candidate/test/{assessment_id}/submit",
        json={
            "responses": [
                {
                    "assessment_id": str(assessment_id),
                    "question_id": "q1",
                    "response": {"answer": "4"},
                    "elapsed_seconds": 12.5,
                }
            ],
            "total_module_duration_seconds": 95.25,
        },
    )
    assert response.status_code == 200
    assert captured["client_duration"] == 95.25
    assert captured["pending"][0].elapsed_seconds == 12.5
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["score"] == 100.0
    assert body["jd_scoring_queued"] is False
    assert captured["aid"] == assessment_id
    assert captured["pending"] is not None
    assert len(captured["pending"]) == 1
    assert captured["pending"][0].question_id == "q1"
    assert captured["pending"][0].response == {"answer": "4"}

