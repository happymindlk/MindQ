import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.schemas.technical_eval import TechnicalItemEvaluation
from app.services.technical_eval import (
    AI_EVAL_FAILED,
    TechnicalEvalService,
    already_evaluated,
    evaluate_item,
    is_gradable_technical_assessment,
    is_open_technical_question,
    merge_evaluation_into_response,
    merge_unavailable_into_response,
    parse_item_evaluation_json,
    UNAVAILABLE_FEEDBACK,
)


def test_parse_item_evaluation_strips_fences():
    raw = "```json\n" + json.dumps(
        {"score": 81, "feedback": "Clear indexing rationale.", "scorecard": ["Depth: strong"]}
    ) + "\n```"
    result = parse_item_evaluation_json(raw)
    assert result.score == 81
    assert "indexing" in result.feedback
    assert result.scorecard == ["Depth: strong"]


def test_merge_preserves_answer():
    evaluation = TechnicalItemEvaluation(
        score=70,
        feedback="Partial coverage of CAP.",
        scorecard=["Consistency: mentioned"],
    )
    merged = merge_evaluation_into_response({"answer": "CAP is hard"}, evaluation)
    assert merged["answer"] == "CAP is hard"
    assert merged["ai_score"] == 70
    assert merged["ai_evaluation"] == "Partial coverage of CAP."
    assert merged["scorecard"] == ["Consistency: mentioned"]
    assert merged["ai_eval_status"] == "ok"


def test_already_evaluated():
    assert already_evaluated({"answer": "x"}) is False
    assert already_evaluated({"answer": "x", "ai_evaluation": "ok", "ai_score": 50}) is True
    assert (
        already_evaluated(
            {
                "answer": "x",
                "ai_evaluation": UNAVAILABLE_FEEDBACK,
                "ai_eval_status": AI_EVAL_FAILED,
                "ai_score": None,
            }
        )
        is False
    )
    assert (
        already_evaluated(
            {
                "answer": "x",
                "ai_evaluation": "legacy",
                "ai_eval_status": "unavailable",
            }
        )
        is False
    )


def test_open_vs_mcq():
    assert is_open_technical_question({"type": "open", "text": "Explain"})
    assert is_open_technical_question({"type": "open_ended"})
    assert not is_open_technical_question({"type": "mcq"})
    assert not is_open_technical_question({"type": "likert"})


def test_custom_technical_detection():
    custom = SimpleNamespace(
        module_kind="technical", global_module_id=None, title="Custom Technical"
    )
    psych = SimpleNamespace(
        module_kind="psychometric", global_module_id=uuid4(), title="Big Five"
    )
    library = SimpleNamespace(
        module_kind="technical", global_module_id=uuid4(), title="SQL Fundamentals"
    )
    assert is_gradable_technical_assessment(custom)
    assert is_gradable_technical_assessment(library)
    assert not is_gradable_technical_assessment(psych)


def test_missing_evals_detected_for_library_module():
    assessment = SimpleNamespace(
        id=uuid4(),
        module_kind="technical",
        global_module_id=uuid4(),
        title="SQL Fundamentals",
        questions=[
            {"id": "sql-01", "type": "mcq", "text": "Join?"},
            {"id": "sql-02", "type": "open", "text": "Write a query"},
        ],
    )
    responses = {assessment.id: {"sql-02": {"answer": "SELECT 1"}}}
    assert TechnicalEvalService.has_missing_open_evals([assessment], responses)

    graded = {
        assessment.id: {
            "sql-02": {"answer": "SELECT 1", "ai_score": 70, "ai_evaluation": "ok"}
        }
    }
    assert not TechnicalEvalService.has_missing_open_evals([assessment], graded)


def test_evaluate_item_uses_stub():
    captured = {}

    def complete(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(
            {"score": 88, "feedback": "Solid retries story.", "scorecard": ["Backoff: yes"]}
        )

    result = evaluate_item(
        question={
            "id": "c1",
            "text": "How do you handle rate limits?",
            "type": "open",
            "benchmark_rubric": "Mention exponential backoff",
            "evaluated_competency": "Reliability",
        },
        answer="Retry with jittered backoff",
        complete=complete,
    )
    assert result.score == 88
    assert "rate limits" in captured["prompt"]
    assert "exponential backoff" in captured["prompt"]
    assert "Retry with jittered backoff" in captured["prompt"]


@pytest.mark.asyncio
async def test_evaluate_assessment_is_sequential(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("app.services.technical_eval.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "app.services.technical_eval.settings.GEMINI_INTER_REQUEST_SECONDS", 0.5
    )

    assessment_id = uuid4()
    assessment = SimpleNamespace(
        id=assessment_id,
        title="Custom Technical",
        module_kind="technical",
        global_module_id=None,
        questions=[
            {"id": "c1", "type": "open", "text": "Q1"},
            {"id": "c2", "type": "open", "text": "Q2"},
            {"id": "c3", "type": "mcq", "text": "skip me"},
        ],
    )
    row1 = SimpleNamespace(question_id="c1", response={"answer": "a1"})
    row2 = SimpleNamespace(question_id="c2", response={"answer": "a2"})
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row1, row2]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    calls: list[str] = []

    def complete(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(
            {"score": 60, "feedback": f"note-{len(calls)}", "scorecard": ["ok"]}
        )

    stored = await TechnicalEvalService.evaluate_assessment(
        session,
        candidate=SimpleNamespace(id=uuid4()),
        assessment=assessment,
        complete=complete,
    )
    assert stored == 2
    assert len(calls) == 2
    assert sleeps == [0.5]
    assert row1.response["ai_evaluation"] == "note-1"
    assert row1.response["answer"] == "a1"
    assert row2.response["ai_score"] == 60
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_evaluate_assessment_stores_fallback_on_gemini_error():
    assessment_id = uuid4()
    assessment = SimpleNamespace(
        id=assessment_id,
        title="Custom Technical",
        module_kind="technical",
        global_module_id=None,
        questions=[{"id": "c1", "type": "open", "text": "Q1"}],
    )
    row = SimpleNamespace(question_id="c1", response={"answer": "thin"})
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    def complete(_prompt: str) -> str:
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    stored = await TechnicalEvalService.evaluate_assessment(
        session,
        candidate=SimpleNamespace(id=uuid4()),
        assessment=assessment,
        complete=complete,
    )
    assert stored == 1
    assert row.response["answer"] == "thin"
    assert row.response["ai_evaluation"] == UNAVAILABLE_FEEDBACK
    assert row.response["ai_score"] is None
    assert row.response["ai_eval_status"] == AI_EVAL_FAILED
    assert already_evaluated(row.response) is False
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_evaluate_assessment_writes_fallback_when_no_api_key(monkeypatch):
    monkeypatch.setattr("app.services.technical_eval.settings.GEMINI_API_KEY", "")
    assessment_id = uuid4()
    assessment = SimpleNamespace(
        id=assessment_id,
        title="Custom Technical",
        module_kind="technical",
        global_module_id=None,
        questions=[{"id": "c1", "type": "open", "text": "Q1"}],
    )
    row = SimpleNamespace(question_id="c1", response={"answer": "kept"})
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    stored = await TechnicalEvalService.evaluate_assessment(
        session,
        candidate=SimpleNamespace(id=uuid4()),
        assessment=assessment,
        complete=None,
    )
    assert stored == 1
    assert row.response["answer"] == "kept"
    assert row.response["ai_evaluation"] == UNAVAILABLE_FEEDBACK
    assert row.response["ai_score"] is None
    assert row.response["ai_eval_status"] == AI_EVAL_FAILED
    assert "GEMINI_API_KEY" in row.response["ai_eval_error"]
    session.commit.assert_awaited()


def test_has_missing_open_evals():
    aid = uuid4()
    assessment = SimpleNamespace(
        id=aid,
        title="Custom Technical",
        module_kind="technical",
        global_module_id=None,
        questions=[{"id": "c1", "type": "open", "text": "Q1"}],
    )
    assert TechnicalEvalService.has_missing_open_evals(
        [assessment], {aid: {"c1": {"answer": "x"}}}
    )
    assert TechnicalEvalService.has_missing_open_evals(
        [assessment],
        {
            aid: {
                "c1": {
                    "answer": "x",
                    "ai_evaluation": UNAVAILABLE_FEEDBACK,
                    "ai_eval_status": AI_EVAL_FAILED,
                    "ai_score": None,
                }
            }
        },
    )
    assert not TechnicalEvalService.has_missing_open_evals(
        [assessment],
        {aid: {"c1": {"answer": "x", "ai_evaluation": "ok", "ai_score": 40}}},
    )


def test_merge_unavailable_keeps_answer():
    merged = merge_unavailable_into_response({"answer": "kept"}, RuntimeError("503"))
    assert merged["answer"] == "kept"
    assert merged["ai_score"] is None
    assert merged["ai_evaluation"] == UNAVAILABLE_FEEDBACK
    assert merged["ai_eval_status"] == AI_EVAL_FAILED
    assert "503" in merged["ai_eval_error"]
