"""Gemini call hardening: pin, timeout/retry, validation, cost visibility."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.prompts.jd_scoring import PROMPT_VERSION
from app.services import gemini_client
from app.services.gemini_client import (
    estimate_cost_usd,
    extract_usage,
    is_pinned_model_id,
    retry_delay_seconds,
    retry_sync,
)
from app.services.jd_scoring import (
    BANNED_LANGUAGE_ERROR,
    EVAL_STATUS_FAILED,
    EVAL_STATUS_OK,
    BannedLanguageError,
    ModelText,
    JdScoringService,
    find_banned_words,
    score_against_jd_with_model,
    synthesis_cache_key,
)
from app.services.report_synthesis import ModuleOutcome


class RateLimitError(Exception):
    def __init__(self, code: int = 429, status: str = "RESOURCE_EXHAUSTED"):
        self.code = code
        self.status = status
        super().__init__(f"{code} {status}")


VALID_SYNTHESIS = {
    "headline": "Results align with the role's analytical priorities and leave composure to explore.",
    "key_takeaways": [
        "Strong alignment with analytical thinking priorities.",
        "May prefer clearer guidance when priorities shift.",
        "Treat self-report results as supporting evidence only.",
    ],
    "executive_summary": "Solid quantitative reasoning with thin written evidence.",
    "role_alignment": [
        {
            "capability_key": "cap_analytical",
            "capability_label": "Analytical thinking and problem solving",
            "importance": "critical",
            "alignment": "results_strongly_align",
            "confidence": "high",
            "evidence": "CogniCheck band wording supports strong analytical performance for this role.",
        }
    ],
    "strengths": [
        "Accurate numerical reasoning under time pressure.",
        "Applies structured logic when solving work problems.",
        "Shows awareness of expected workplace conduct on judgment items.",
    ],
    "areas_to_explore": [
        "May take longer to commit when information is incomplete.",
        "May prefer clearer guidance when priorities shift.",
        "May benefit from checking how they handle fast-paced change.",
    ],
    "work_environment_notes": [
        "May settle well in roles with clear analytical ownership.",
        "May prefer steady collaboration over constant switching.",
    ],
    "interview_focus_areas": [
        "How they approach ambiguous analytical trade-offs.",
        "Comfort with shifting priorities.",
        "How they use judgment under time pressure.",
    ],
    "verify_separately": ["Required SQL experience"],
    "support_suggestions": ["Pair on first complex analytical delivery"],
    "reliability_notes": ["Open-ended evidence is thin for this package."],
    "competency_breakdown": [
        {
            "assessment_key": "A1",
            "assessment_name": "Math",
            "performance_summary": "Scored 80%, indicating strong numerical reasoning.",
            "role_relevance": "Supports the analytical demands of the target role.",
            "subscale_notes": [],
        }
    ],
    "category_summaries": [
        {
            "category": "Cognitive",
            "summary": "Strong quantitative reasoning for the role. Applies structured logic consistently.",
        }
    ],
}


@pytest.fixture(autouse=True)
def _gemini_settings(monkeypatch):
    s = gemini_client.settings
    monkeypatch.setattr(s, "GEMINI_MODEL", "gemini-3.5-flash")
    monkeypatch.setattr(s, "GEMINI_FALLBACK_MODELS", "gemini-3.6-flash")
    monkeypatch.setattr(s, "GEMINI_MAX_RETRIES", 3)
    monkeypatch.setattr(s, "GEMINI_TIMEOUT_SECONDS", 30.0)
    monkeypatch.setattr(s, "GEMINI_RETRY_BASE_SECONDS", 2.0)
    monkeypatch.setattr(s, "GEMINI_RETRY_MAX_DELAY_SECONDS", 30.0)
    monkeypatch.setattr(s, "GEMINI_INPUT_USD_PER_1M", 1.50)
    monkeypatch.setattr(s, "GEMINI_OUTPUT_USD_PER_1M", 9.00)
    monkeypatch.setattr(s, "GEMINI_LITE_INPUT_USD_PER_1M", 0.25)
    monkeypatch.setattr(s, "GEMINI_LITE_OUTPUT_USD_PER_1M", 1.50)


@pytest.mark.parametrize(
    "model, pinned",
    [
        ("gemini-3.5-flash", True),
        ("gemini-3.6-flash", True),
        ("gemini-3.5-flash-lite", True),
        ("gemini-flash-latest", False),
        ("gemini-3.1-pro-preview", False),
        ("gemini-2.0-flash-exp", False),
        ("", False),
    ],
)
def test_model_ids_are_explicitly_pinned(model, pinned):
    assert is_pinned_model_id(model) is pinned


def test_configured_primary_and_fallback_models_are_pinned():
    assert is_pinned_model_id(gemini_client.settings.GEMINI_MODEL)
    for name in gemini_client.fallback_models():
        assert is_pinned_model_id(name)


def test_retry_sync_recovers_from_429_with_exponential_backoff():
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError(code=429, status="RESOURCE_EXHAUSTED")
        return "ok"

    delays: list[float] = []
    assert retry_sync(fn, sleep=delays.append) == "ok"
    assert calls["n"] == 3
    assert delays == [retry_delay_seconds(1), retry_delay_seconds(2)]


def test_retry_sync_recovers_from_503():
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError(code=503, status="UNAVAILABLE")
        return "ok"

    assert retry_sync(fn, sleep=lambda _s: None) == "ok"
    assert calls["n"] == 2


def test_extract_usage_and_estimate_cost_from_response_metadata():
    response = SimpleNamespace(
        model_version="gemini-3.5-flash",
        usage_metadata=SimpleNamespace(
            prompt_token_count=1000,
            candidates_token_count=500,
            thoughts_token_count=100,
            total_token_count=1600,
        ),
    )
    usage = extract_usage(response, "gemini-3.5-flash")
    assert usage.prompt_tokens == 1000
    assert usage.candidates_tokens == 500
    assert usage.thoughts_tokens == 100
    assert usage.total_tokens == 1600
    # (1000/1e6)*1.50 + ((500+100)/1e6)*9.00
    assert usage.estimated_cost_usd == pytest.approx(0.0069)
    assert usage.as_dict()["estimated_cost_usd"] == pytest.approx(0.0069)


def test_lite_model_uses_lower_rate_table():
    cost = estimate_cost_usd(
        prompt_tokens=1_000_000,
        candidates_tokens=1_000_000,
        model="gemini-3.5-flash-lite",
    )
    assert cost == pytest.approx(0.25 + 1.50)


def test_banned_words_from_prompt_contract_are_detected():
    assert find_banned_words({"areas_to_explore": ["This is a red flag."]}) == ["red flag"]
    assert "anxious" in find_banned_words({"headline": "Appears anxious under load."})


def test_invalid_json_raises_after_retry_never_returns_broken_narrative():
    calls = {"n": 0}

    def complete(_prompt: str) -> str:
        calls["n"] += 1
        return "not-json {{{"

    with pytest.raises(Exception) as info:
        score_against_jd_with_model(
            job_description="Role",
            candidate_name="Pat",
            package_title="Pkg",
            evidence=[],
            assessment_scores=[
                {
                    "assessment_key": "A1",
                    "assessment_name": "Math",
                    "category": "Cognitive",
                    "score": 80.0,
                }
            ],
            complete=complete,
        )
    assert calls["n"] == 2
    assert "invalid_synthesis_json" in str(info.value) or "JSON" in str(info.value).upper()


def test_banned_language_retries_then_manual_review_flag():
    banned = {
        **VALID_SYNTHESIS,
        "areas_to_explore": [
            "This is a red flag for shifting priorities.",
            "May prefer clearer guidance when priorities shift.",
            "May take longer to commit when information is incomplete.",
        ],
    }
    calls = {"n": 0}

    def complete(_prompt: str) -> str:
        calls["n"] += 1
        return json.dumps(banned)

    with pytest.raises(BannedLanguageError) as info:
        score_against_jd_with_model(
            job_description="Role",
            candidate_name="Pat",
            package_title="Pkg",
            evidence=[],
            assessment_scores=[
                {
                    "assessment_key": "A1",
                    "assessment_name": "Math",
                    "category": "Cognitive",
                    "score": 80.0,
                }
            ],
            complete=complete,
        )
    assert calls["n"] == 2
    assert BANNED_LANGUAGE_ERROR in str(info.value)


def test_cache_key_includes_prompt_version(monkeypatch):
    outcomes = _outcomes()
    key_v5 = synthesis_cache_key("Role brief", outcomes)
    monkeypatch.setattr("app.services.jd_scoring.PROMPT_VERSION", "mindq-report-v6-test")
    key_v6 = synthesis_cache_key("Role brief", outcomes)
    assert key_v5 != key_v6
    assert PROMPT_VERSION == "mindq-report-v5"


class FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, _stmt):
        return _Result(self.existing)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class _Result:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


def _outcomes(score: float = 80.0) -> list[ModuleOutcome]:
    return [
        ModuleOutcome(
            key="A1",
            id=uuid4(),
            title="Math",
            category="cognitive",
            score=score,
            completed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]


def _scoring_kwargs(*, outcomes: list[ModuleOutcome] | None = None) -> dict[str, Any]:
    candidate = SimpleNamespace(
        id=uuid4(),
        corporate_id=uuid4(),
        package_id=uuid4(),
        full_name="Pat Candidate",
    )
    package = SimpleNamespace(
        title="Pkg",
        description="Role brief for an analyst.",
        target_role="Analyst",
    )
    return {
        "candidate": candidate,
        "package": package,
        "assessments": [],
        "progresses": [],
        "responses": [],
        "outcomes": outcomes if outcomes is not None else _outcomes(),
    }


@pytest.mark.asyncio
async def test_provider_outage_persists_manual_review_failed_row_not_broken_payload():
    session = FakeSession()

    def complete(_prompt: str) -> str:
        raise RuntimeError("503 UNAVAILABLE. model is experiencing high demand")

    evaluation, status = await JdScoringService.get_or_evaluate(
        session, complete=complete, **_scoring_kwargs()
    )
    assert evaluation is None
    assert status == "failed"
    row = session.added[0]
    assert row.status == EVAL_STATUS_FAILED
    assert row.payload == {}
    assert "503" in row.last_error
    assert row.usage is None


@pytest.mark.asyncio
async def test_successful_generation_persists_token_cost_usage():
    session = FakeSession()
    usage = {
        "prompt_tokens": 1200,
        "candidates_tokens": 800,
        "thoughts_tokens": 0,
        "total_tokens": 2000,
        "estimated_cost_usd": 0.009,
        "model": "gemini-3.5-flash",
    }

    def complete(_prompt: str) -> str:
        return ModelText.tagged(json.dumps(VALID_SYNTHESIS), "gemini-3.5-flash", usage)

    evaluation, status = await JdScoringService.get_or_evaluate(
        session, complete=complete, **_scoring_kwargs()
    )
    assert status == "generated"
    assert evaluation is not None
    row = session.added[0]
    assert row.status == EVAL_STATUS_OK
    assert row.usage == usage
    assert row.usage["estimated_cost_usd"] == 0.009
    assert "overall_fit" not in row.payload
