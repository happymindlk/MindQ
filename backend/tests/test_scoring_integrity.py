"""Batch 2: late-autosave scoring, scoring retries/reconciler, submit-before-start."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from arq import Retry

from app.api.v1 import candidate as candidate_api
from app.auth import get_current_candidate
from app.config import settings
from app.database import get_db
from app.exceptions import AssessmentNotStartedError, AssessmentTimeExpiredError
from app.jobs import tasks as tasks_mod
from app.main import app
from app.schemas.response import ResponseSave
from app.services import background as background_mod
from app.services import candidate_service
from app.services.background import ScoringFailedError
from app.services.candidate_service import CandidateService

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)


def _timed_assessment(duration=600):
    return SimpleNamespace(
        id=uuid.uuid4(),
        timer_mode="flexible",
        duration_seconds=duration,
        time_limit_minutes=None,
        questions=[{"id": "q1", "type": "mcq"}],
        scoring_profile=None,
        title=None,
    )


def _candidate():
    return SimpleNamespace(id=uuid.uuid4(), corporate_id=uuid.uuid4(), package_id=uuid.uuid4())


# --- P0-03: timed module cannot be submitted before POST /start --------------


@pytest.mark.asyncio
@pytest.mark.parametrize("progress", [None, SimpleNamespace(started_at=None, expires_at=None)])
async def test_submit_timed_module_without_start_is_rejected(monkeypatch, progress):
    assessment = _timed_assessment()
    monkeypatch.setattr(
        CandidateService,
        "require_writable_assessment",
        AsyncMock(return_value=(assessment, progress)),
    )
    monkeypatch.setattr(candidate_service, "_utcnow", lambda: NOW)
    session = AsyncMock()
    session.add = MagicMock()

    with pytest.raises(AssessmentNotStartedError):
        await CandidateService.submit_test(session, _candidate(), assessment.id)
    session.commit.assert_not_awaited()
    session.add.assert_not_called()


@pytest.fixture
def candidate_client(async_client):
    fake = _candidate()

    async def _cand():
        return fake

    async def _db():
        yield None

    app.dependency_overrides[get_current_candidate] = _cand
    app.dependency_overrides[get_db] = _db
    try:
        yield async_client, fake
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_submit_http_not_started_is_409(candidate_client, monkeypatch):
    client, _fake = candidate_client

    async def _raise(*_a, **_k):
        raise AssessmentNotStartedError()

    monkeypatch.setattr(CandidateService, "submit_test", _raise)
    enqueue = AsyncMock()
    monkeypatch.setattr(candidate_api, "enqueue_finalize_and_score_ai", enqueue)
    res = await client.post(
        f"/api/v1/candidate/test/{uuid.uuid4()}/submit", json={"responses": []}
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "NOT_STARTED"
    enqueue.assert_not_awaited()


# --- P0-01: late autosave that finalizes the module queues scoring -----------


@pytest.mark.asyncio
async def test_late_autosave_marks_exception_auto_finalized(monkeypatch):
    monkeypatch.setattr(
        CandidateService,
        "_gate_autosave",
        AsyncMock(side_effect=AssessmentTimeExpiredError()),
    )
    monkeypatch.setattr(
        CandidateService,
        "submit_test",
        AsyncMock(return_value=(SimpleNamespace(), True, "Acme", "Mod")),
    )
    save = ResponseSave(assessment_id=uuid.uuid4(), question_id="q1", response={"answer": "a"})
    with pytest.raises(AssessmentTimeExpiredError) as info:
        await CandidateService.autosave_response(AsyncMock(), _candidate(), save)
    assert info.value.auto_finalized is True
    assert info.value.package_complete is True


@pytest.mark.asyncio
async def test_late_autosave_http_enqueues_scoring_and_synthesis(candidate_client, monkeypatch):
    client, fake = candidate_client
    assessment_id = uuid.uuid4()

    async def _raise(*_a, **_k):
        exc = AssessmentTimeExpiredError()
        exc.auto_finalized = True
        exc.package_complete = True
        raise exc

    monkeypatch.setattr(CandidateService, "autosave_response", _raise)
    score = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr(candidate_api, "enqueue_finalize_and_score_ai", score)
    monkeypatch.setattr(candidate_api, "enqueue_refresh_report_synthesis", refresh)

    res = await client.post(
        "/api/v1/candidate/autosave",
        json={"assessment_id": str(assessment_id), "question_id": "q1", "response": {"answer": "a"}},
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "TIME_EXPIRED"
    score.assert_awaited_once_with(fake.id, assessment_id, await_inline=False)
    refresh.assert_awaited_once_with(fake.id, await_inline=False)


@pytest.mark.asyncio
async def test_late_autosave_http_already_submitted_does_not_enqueue(candidate_client, monkeypatch):
    client, _fake = candidate_client

    async def _raise(*_a, **_k):
        raise AssessmentTimeExpiredError()  # auto_finalized stays False

    monkeypatch.setattr(CandidateService, "autosave_response", _raise)
    score = AsyncMock()
    monkeypatch.setattr(candidate_api, "enqueue_finalize_and_score_ai", score)
    res = await client.post(
        "/api/v1/candidate/autosave",
        json={"assessment_id": str(uuid.uuid4()), "question_id": "q1", "response": {"answer": "a"}},
    )
    assert res.status_code == 409
    score.assert_not_awaited()


# --- P0-02: scoring failures are retried, not swallowed ----------------------


@pytest.mark.asyncio
async def test_finalize_scoring_failure_raises_and_skips_later_stages(monkeypatch):
    @asynccontextmanager
    async def _session():
        yield AsyncMock()

    monkeypatch.setattr(background_mod, "SessionLocal", _session)
    monkeypatch.setattr(
        CandidateService, "get_candidate", AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    )
    monkeypatch.setattr(
        CandidateService,
        "finalize_submission_scores",
        AsyncMock(side_effect=RuntimeError("pooler blip")),
    )
    ai = AsyncMock()
    monkeypatch.setattr(background_mod, "score_ai_for_candidate", ai)

    with pytest.raises(ScoringFailedError):
        await background_mod.finalize_and_score_ai(uuid.uuid4(), uuid.uuid4())
    ai.assert_not_awaited()


def _failing_finalize(monkeypatch):
    async def _fail(cid, aid):
        raise ScoringFailedError(cid, aid)

    monkeypatch.setattr(tasks_mod, "finalize_and_score_ai", _fail)


@pytest.mark.asyncio
async def test_task_scoring_failure_retries_under_arq(monkeypatch):
    _failing_finalize(monkeypatch)
    with pytest.raises(Retry):
        await tasks_mod.task_finalize_and_score_ai(
            {"job_try": 1}, str(uuid.uuid4()), str(uuid.uuid4())
        )


@pytest.mark.asyncio
async def test_task_scoring_failure_on_last_try_fails_job(monkeypatch):
    _failing_finalize(monkeypatch)
    with pytest.raises(ScoringFailedError):
        await tasks_mod.task_finalize_and_score_ai(
            {"job_try": settings.ARQ_MAX_TRIES}, str(uuid.uuid4()), str(uuid.uuid4())
        )


@pytest.mark.asyncio
async def test_task_scoring_failure_inline_does_not_raise(monkeypatch):
    _failing_finalize(monkeypatch)
    assert await tasks_mod.task_finalize_and_score_ai({}, uuid.uuid4(), uuid.uuid4()) is None


# --- P0-02: reconciler re-queues COMPLETED rows without score_details -------


@pytest.mark.asyncio
async def test_reconciler_enqueues_with_finalize_job_ids(monkeypatch):
    pairs = [(uuid.uuid4(), uuid.uuid4()), (uuid.uuid4(), uuid.uuid4())]
    finder = AsyncMock(return_value=pairs)
    monkeypatch.setattr(tasks_mod, "find_unscored_completed", finder)
    redis = MagicMock()
    # Second pair is already queued/retrying -> ARQ dedups (returns None).
    redis.enqueue_job = AsyncMock(side_effect=[SimpleNamespace(job_id="j"), None])

    assert await tasks_mod.task_reconcile_unscored({"redis": redis}) == 1
    finder.assert_awaited_once_with(
        lookback=timedelta(hours=settings.SCORING_RECONCILE_LOOKBACK_HOURS)
    )
    calls = redis.enqueue_job.await_args_list
    assert [c.kwargs["_job_id"] for c in calls] == [f"finalize:{c}:{a}" for c, a in pairs]
    assert all(c.args[0] == "task_finalize_and_score_ai" for c in calls)


@pytest.mark.asyncio
async def test_reconciler_noop_when_nothing_unscored(monkeypatch):
    monkeypatch.setattr(tasks_mod, "find_unscored_completed", AsyncMock(return_value=[]))
    redis = MagicMock()
    redis.enqueue_job = AsyncMock()
    assert await tasks_mod.task_reconcile_unscored({"redis": redis}) == 0
    redis.enqueue_job.assert_not_awaited()


def test_reconciler_registered_as_worker_cron():
    from app.jobs.worker import WorkerSettings

    names = [getattr(c, "name", "") for c in WorkerSettings.cron_jobs]
    assert any("task_reconcile_unscored" in n for n in names)
    assert tasks_mod.task_reconcile_unscored in WorkerSettings.functions
