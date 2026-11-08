"""Report narrative off the request path: cache reads, refresh claims, background job."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services import background
from app.services.jd_scoring import (
    EVAL_STATUS_FAILED,
    EVAL_STATUS_OK,
    FAILED_RETRY_COOLDOWN,
    JdScoringService,
    synthesis_cache_key,
)
from app.services.report_synthesis import ModuleOutcome
from tests.test_candidate_report_data import SYNTHESIS

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
PACKAGE = SimpleNamespace(description="Analyse sales data.", target_role="Analyst", title="Pack")


@pytest.fixture(autouse=True)
def _isolated_job_state(monkeypatch):
    monkeypatch.setattr(background, "_ai_jobs_inflight", {})
    monkeypatch.setattr(background, "_last_view_refresh", {})


def _outcomes() -> list[ModuleOutcome]:
    return [
        ModuleOutcome(
            key="A1",
            id=uuid4(),
            title="SQL Basics",
            category="technical",
            score=80.0,
            completed_at=NOW,
        )
    ]


def _session_returning(row) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.first.return_value = row
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _row(*, digest: str, status: str, payload: dict, generated_at: datetime = NOW):
    return SimpleNamespace(
        jd_hash=digest, status=status, payload=payload, generated_at=generated_at
    )


async def _read(row, outcomes, *, now=NOW, package=PACKAGE):
    return await JdScoringService.read_cached(
        _session_returning(row),
        candidate=SimpleNamespace(id=uuid4()),
        package=package,
        outcomes=outcomes,
        now=now,
    )


@pytest.mark.asyncio
async def test_read_cached_returns_ok_narrative_without_refresh():
    outcomes = _outcomes()
    digest = synthesis_cache_key(PACKAGE.description, outcomes)
    row = _row(digest=digest, status=EVAL_STATUS_OK, payload=SYNTHESIS.model_dump())
    cached = await _read(row, outcomes)
    assert cached.state == "ok"
    assert cached.needs_refresh is False
    assert cached.narrative is not None
    assert cached.narrative.executive_summary == SYNTHESIS.executive_summary


@pytest.mark.asyncio
async def test_read_cached_missing_row_needs_refresh():
    cached = await _read(None, _outcomes())
    assert (cached.state, cached.needs_refresh, cached.narrative) == ("missing", True, None)


@pytest.mark.asyncio
async def test_read_cached_digest_mismatch_is_stale():
    row = _row(digest="old-scores", status=EVAL_STATUS_OK, payload=SYNTHESIS.model_dump())
    cached = await _read(row, _outcomes())
    assert (cached.state, cached.needs_refresh, cached.narrative) == ("stale", True, None)


@pytest.mark.asyncio
async def test_read_cached_corrupt_payload_is_stale_not_500():
    outcomes = _outcomes()
    digest = synthesis_cache_key(PACKAGE.description, outcomes)
    row = _row(digest=digest, status=EVAL_STATUS_OK, payload={"headline": 42})
    cached = await _read(row, outcomes)
    assert (cached.state, cached.needs_refresh) == ("stale", True)


@pytest.mark.asyncio
async def test_read_cached_recent_failure_waits_for_cooldown():
    outcomes = _outcomes()
    digest = synthesis_cache_key(PACKAGE.description, outcomes)
    row = _row(
        digest=digest,
        status=EVAL_STATUS_FAILED,
        payload={},
        generated_at=NOW - FAILED_RETRY_COOLDOWN + timedelta(seconds=30),
    )
    cached = await _read(row, outcomes)
    assert (cached.state, cached.needs_refresh) == ("failed", False)


@pytest.mark.asyncio
async def test_read_cached_old_failure_is_retried():
    outcomes = _outcomes()
    digest = synthesis_cache_key(PACKAGE.description, outcomes)
    row = _row(
        digest=digest,
        status=EVAL_STATUS_FAILED,
        payload={},
        generated_at=NOW - FAILED_RETRY_COOLDOWN,
    )
    cached = await _read(row, outcomes)
    assert (cached.state, cached.needs_refresh) == ("failed", True)


@pytest.mark.asyncio
async def test_read_cached_skips_without_role_or_outcomes():
    no_role = SimpleNamespace(description="", target_role="", title="")
    assert (await _read(None, _outcomes(), package=no_role)).state == "skipped"
    assert (await _read(None, [])).state == "skipped"


def test_claim_report_refresh_enforces_cooldown():
    candidate_id = uuid4()
    cooldown = FAILED_RETRY_COOLDOWN.total_seconds()
    assert background.claim_report_refresh(candidate_id, now=1000.0) is True
    assert background.claim_report_refresh(candidate_id, now=1000.0 + cooldown - 1) is False
    assert background.claim_report_refresh(candidate_id, now=1000.0 + cooldown) is True


def test_claim_report_refresh_refuses_while_job_inflight():
    candidate_id = uuid4()
    background._ai_jobs_inflight[candidate_id] = 1
    assert background.claim_report_refresh(candidate_id, now=0.0) is False
    assert candidate_id not in background._last_view_refresh


def _patch_session(monkeypatch, session: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(background, "SessionLocal", factory)
    return factory


def _job_session() -> MagicMock:
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=empty)
    session.rollback = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_refresh_skips_when_another_job_is_running(monkeypatch):
    candidate_id = uuid4()
    background._ai_jobs_inflight[candidate_id] = 1
    factory = _patch_session(monkeypatch, _job_session())
    await background.refresh_report_synthesis(candidate_id)
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_grades_technical_items_before_synthesis(monkeypatch):
    candidate_id = uuid4()
    candidate = SimpleNamespace(id=candidate_id, package_id=uuid4())
    order: list[str] = []
    seen_inflight: list[bool] = []

    async def _grade(*_a, **_k):
        order.append("technical")
        seen_inflight.append(background.is_ai_job_inflight(candidate_id))
        return 1

    async def _synthesis(_session, _candidate):
        order.append("synthesis")

    _patch_session(monkeypatch, _job_session())
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService, "evaluate_jd_if_package_complete", _synthesis
    )
    monkeypatch.setattr(
        background.TechnicalEvalService,
        "has_missing_open_evals",
        staticmethod(lambda *_a, **_k: True),
    )
    monkeypatch.setattr(background.TechnicalEvalService, "evaluate_candidate", _grade)

    await background.refresh_report_synthesis(candidate_id)

    assert order == ["technical", "synthesis"]
    assert seen_inflight == [True]
    assert background.is_ai_job_inflight(candidate_id) is False


@pytest.mark.asyncio
async def test_refresh_still_runs_synthesis_when_grading_fails(monkeypatch):
    candidate_id = uuid4()
    candidate = SimpleNamespace(id=candidate_id, package_id=uuid4())
    session = _job_session()
    synthesis = AsyncMock()

    _patch_session(monkeypatch, session)
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService, "evaluate_jd_if_package_complete", synthesis
    )
    monkeypatch.setattr(
        background.TechnicalEvalService,
        "has_missing_open_evals",
        staticmethod(lambda *_a, **_k: True),
    )
    monkeypatch.setattr(
        background.TechnicalEvalService,
        "evaluate_candidate",
        AsyncMock(side_effect=RuntimeError("503 UNAVAILABLE")),
    )

    await background.refresh_report_synthesis(candidate_id)

    session.rollback.assert_awaited_once()
    synthesis.assert_awaited_once_with(session, candidate)
    assert background.is_ai_job_inflight(candidate_id) is False


@pytest.mark.asyncio
async def test_refresh_swallows_synthesis_failure_and_releases_guard(monkeypatch):
    candidate_id = uuid4()
    candidate = SimpleNamespace(id=candidate_id, package_id=uuid4())
    _patch_session(monkeypatch, _job_session())
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService,
        "evaluate_jd_if_package_complete",
        AsyncMock(side_effect=TimeoutError("gemini deadline")),
    )
    monkeypatch.setattr(
        background.TechnicalEvalService,
        "has_missing_open_evals",
        staticmethod(lambda *_a, **_k: False),
    )

    await background.refresh_report_synthesis(candidate_id)

    assert background.is_ai_job_inflight(candidate_id) is False
