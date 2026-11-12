"""ARQ enqueue helpers and task wrappers (durable job queue)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import candidate as candidate_api
from app.api.v1 import invites as invites_api
from app.api.v1.candidate_reports import router as reports_data_router
from app.auth import HRUserContext, get_current_candidate, get_current_hr_user
from app.database import get_db
from app.jobs import enqueue as enqueue_mod
from app.jobs.enqueue import (
    _job_id_finalize,
    _job_id_invite,
    _job_id_refresh,
    enqueue_candidate_invite,
    enqueue_finalize_and_score_ai,
    enqueue_nudge_email,
    enqueue_refresh_report_synthesis,
    enqueue_store_cached_report,
)
from app.jobs.settings import set_arq_pool_for_tests
from app.jobs import tasks as tasks_mod
from app.services.jd_scoring import CachedSynthesis


@pytest.fixture(autouse=True)
def _reset_arq_pool():
    set_arq_pool_for_tests(None)
    yield
    set_arq_pool_for_tests(None)


@pytest.mark.asyncio
async def test_enqueue_finalize_uses_deterministic_job_id():
    candidate_id = uuid4()
    assessment_id = uuid4()
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=SimpleNamespace(job_id="j1"))
    set_arq_pool_for_tests(pool)

    await enqueue_finalize_and_score_ai(candidate_id, assessment_id)

    pool.enqueue_job.assert_awaited_once()
    args, kwargs = pool.enqueue_job.await_args
    assert args[0] == "task_finalize_and_score_ai"
    assert args[1:] == (str(candidate_id), str(assessment_id))
    assert kwargs["_job_id"] == _job_id_finalize(candidate_id, assessment_id)


@pytest.mark.asyncio
async def test_enqueue_refresh_uses_deterministic_job_id():
    candidate_id = uuid4()
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=SimpleNamespace(job_id="j2"))
    set_arq_pool_for_tests(pool)

    await enqueue_refresh_report_synthesis(candidate_id)

    args, kwargs = pool.enqueue_job.await_args
    assert args[0] == "task_refresh_report_synthesis"
    assert args[1:] == (str(candidate_id),)
    assert kwargs["_job_id"] == _job_id_refresh(candidate_id)


@pytest.mark.asyncio
async def test_enqueue_dedup_returns_none_without_inline_rerun():
    candidate_id = uuid4()
    assessment_id = uuid4()
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=None)
    set_arq_pool_for_tests(pool)

    with patch.object(
        enqueue_mod, "task_finalize_and_score_ai", new_callable=AsyncMock
    ) as task:
        result = await enqueue_finalize_and_score_ai(candidate_id, assessment_id)

    assert result is None
    task.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_inline_fallback_runs_task_when_pool_missing():
    candidate_id = uuid4()
    assessment_id = uuid4()
    set_arq_pool_for_tests(None)

    with patch.object(
        enqueue_mod, "task_finalize_and_score_ai", new_callable=AsyncMock
    ) as task:
        await enqueue_finalize_and_score_ai(candidate_id, assessment_id)

    task.assert_awaited_once()


@pytest.mark.asyncio
async def test_task_wrappers_delegate_to_background_and_email():
    candidate_id = uuid4()
    assessment_id = uuid4()

    with (
        patch.object(tasks_mod, "finalize_and_score_ai", new_callable=AsyncMock) as fin,
        patch.object(tasks_mod, "refresh_report_synthesis", new_callable=AsyncMock) as ref,
        patch(
            "app.api.v1.invites._dispatch_candidate_invite",
            new_callable=AsyncMock,
        ) as invite,
        patch.object(
            tasks_mod.EmailService, "send_nudge_email", new_callable=AsyncMock
        ) as nudge,
        patch.object(tasks_mod, "run_in_threadpool", new_callable=AsyncMock) as pool,
    ):
        await tasks_mod.task_finalize_and_score_ai({}, candidate_id, assessment_id)
        await tasks_mod.task_refresh_report_synthesis({}, str(candidate_id))
        await tasks_mod.task_dispatch_candidate_invite(
            {},
            candidate_email="a@ex.com",
            candidate_name="A",
            access_code="HM-1",
            package_title="Pack",
            corporate_name="Acme",
            origin="http://localhost:5173",
            close_time=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        )
        await tasks_mod.task_send_nudge_email({}, "a@ex.com", "A", "HM-1", "Pack")
        await tasks_mod.task_send_package_share({}, "hr@ex.com", "Subject", "<p>hi</p>")
        await tasks_mod.task_store_cached_report(
            {}, uuid4(), candidate_id, "cachekey", b"%PDF"
        )

    fin.assert_awaited_once_with(candidate_id, assessment_id)
    ref.assert_awaited_once_with(candidate_id)
    invite.assert_awaited_once()
    nudge.assert_awaited_once()
    assert pool.await_count == 2


@pytest.mark.asyncio
async def test_submit_route_enqueues_finalize_not_background_tasks(monkeypatch):
    assessment_id = uuid4()
    candidate = SimpleNamespace(id=uuid4(), corporate_id=uuid4())
    progress = SimpleNamespace(
        assessment_id=assessment_id,
        status="COMPLETED",
        completed_at=None,
    )
    enqueued: list[tuple] = []

    async def _submit(*_a, **_k):
        return progress, False

    async def _company(*_a, **_k):
        return "Acme"

    async def _enqueue(cid, aid):
        enqueued.append((cid, aid))

    monkeypatch.setattr(candidate_api.CandidateService, "submit_test", _submit)
    monkeypatch.setattr(candidate_api.CandidateService, "get_company_name", _company)
    monkeypatch.setattr(candidate_api, "enqueue_finalize_and_score_ai", _enqueue)

    app = FastAPI()
    app.include_router(candidate_api.router, prefix="/api/v1/candidate")

    async def _cand():
        return candidate

    async def _db():
        yield MagicMock()

    app.dependency_overrides[get_current_candidate] = _cand
    app.dependency_overrides[get_db] = _db

    res = TestClient(app).post(f"/api/v1/candidate/test/{assessment_id}/submit", json={})
    assert res.status_code == 200
    assert res.json()["jd_scoring_queued"] is True
    assert enqueued == [(candidate.id, assessment_id)]


def test_invite_route_enqueues_with_invite_job_id(monkeypatch):
    package_id = uuid4()
    corp_id = uuid4()
    candidate = SimpleNamespace(
        id=uuid4(),
        email="pat@ex.com",
        full_name="Pat",
        first_name="Pat",
        access_code="HM-AAAAAA-C",
        package_id=package_id,
        corporate_id=corp_id,
    )
    package = SimpleNamespace(
        id=package_id,
        title="Pack",
        corporate_id=corp_id,
        status="published",
        close_time=None,
    )
    corporate = SimpleNamespace(id=corp_id, name="Acme")
    captured: dict = {}

    async def _invite(*_a, **_k):
        return candidate, True

    async def _enqueue(**kwargs):
        captured.update(kwargs)

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalars(self):
            return SimpleNamespace(first=lambda: self._value)

        def scalar_one_or_none(self):
            return self._value

    db = MagicMock()
    calls = {"n": 0}

    async def _execute(_stmt):
        calls["n"] += 1
        return _Result(package if calls["n"] == 1 else corporate)

    db.execute = AsyncMock(side_effect=_execute)

    app = FastAPI()
    app.include_router(invites_api.router, prefix="/api/candidates")

    async def _hr():
        return HRUserContext(
            user_id=uuid4(), corporate_id=corp_id, email="hr@ex.com", role="admin"
        )

    async def _db():
        yield db

    app.dependency_overrides[get_current_hr_user] = _hr
    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(invites_api.CandidateService, "invite", _invite)
    monkeypatch.setattr(invites_api, "enqueue_candidate_invite", _enqueue)
    monkeypatch.setattr(invites_api, "resolve_frontend_origin", lambda _r: "http://x")
    monkeypatch.setattr(
        invites_api, "enforce_user_rate_limit", lambda *_a, **_k: None
    )

    res = TestClient(app).post(
        "/api/candidates/invite",
        json={
            "candidate_email": "pat@ex.com",
            "package_id": str(package_id),
            "corporate_id": str(corp_id),
        },
    )
    assert res.status_code == 202
    assert captured["access_code"] == "HM-AAAAAA-C"
    assert _job_id_invite(captured["candidate_email"], captured["access_code"]).startswith(
        "invite:pat@ex.com:"
    )


def test_report_data_enqueues_refresh_with_refresh_job_id(monkeypatch):
    from app.api.v1 import candidate_reports as cr

    candidate_id = uuid4()
    corp_id = uuid4()
    package_id = uuid4()
    assessment_id = uuid4()
    candidate = SimpleNamespace(
        id=candidate_id,
        corporate_id=corp_id,
        package_id=package_id,
        full_name="Pat",
        email="pat@ex.com",
    )
    enqueued: list = []

    async def _enqueue(cid):
        enqueued.append(cid)

    monkeypatch.setattr(cr, "enqueue_refresh_report_synthesis", _enqueue)
    monkeypatch.setattr(cr, "claim_report_refresh", lambda *_a, **_k: True)
    monkeypatch.setattr(cr, "is_ai_job_inflight", lambda *_a, **_k: False)
    monkeypatch.setattr(cr, "read_report_snapshot", AsyncMock(return_value=None))
    monkeypatch.setattr(cr, "load_catalog_categories", AsyncMock(return_value={}))
    monkeypatch.setattr(
        cr.TechnicalEvalService,
        "has_missing_open_evals",
        staticmethod(lambda *_a, **_k: False),
    )

    async def _read_cached(*_a, **_k):
        return CachedSynthesis(None, "missing", needs_refresh=True)

    monkeypatch.setattr(cr.JdScoringService, "read_cached", staticmethod(_read_cached))

    def _scalar(value):
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        return result

    def _scalars(values):
        result = MagicMock()
        result.scalars.return_value.all.return_value = values
        return result

    assessment = SimpleNamespace(
        id=assessment_id,
        title="SQL",
        module_kind="technical",
        global_module_id=None,
        questions=[],
        position=0,
    )
    progress = SimpleNamespace(
        assessment_id=assessment_id,
        score=80,
        status="COMPLETED",
        completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        facet_scores=None,
        derived_profile=None,
        score_details=None,
        overtime=False,
    )
    results = [
        _scalar(candidate),
        _scalar(SimpleNamespace(id=package_id, target_role="Analyst", title="Pack")),
        _scalar(SimpleNamespace(id=corp_id, name="Acme", logo_url=None)),
        _scalars([assessment]),
        _scalars([progress]),
        _scalars([]),
    ]
    db = MagicMock()
    db.execute = AsyncMock(side_effect=results)

    app = FastAPI()
    app.include_router(reports_data_router, prefix="/api/v1/candidates")

    async def _hr():
        return HRUserContext(
            user_id=uuid4(), corporate_id=corp_id, email="hr@ex.com", role="admin"
        )

    async def _db():
        yield db

    app.dependency_overrides[get_current_hr_user] = _hr
    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(cr, "enforce_user_rate_limit", lambda *_a, **_k: None)

    res = TestClient(app).get(f"/api/v1/candidates/{candidate_id}/report-data")
    assert res.status_code == 200
    assert res.json()["synthesis_status"] == "generating"
    assert enqueued == [candidate_id]
    assert _job_id_refresh(candidate_id) == f"refresh:{candidate_id}"


@pytest.mark.asyncio
async def test_nudge_and_store_enqueue_helpers():
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=SimpleNamespace(job_id="j"))
    set_arq_pool_for_tests(pool)
    candidate_id = uuid4()
    corporate_id = uuid4()

    await enqueue_nudge_email(
        "a@ex.com", "A", "HM-1", "Pack", candidate_id=candidate_id
    )
    await enqueue_store_cached_report(corporate_id, candidate_id, "abc123", b"%PDF")
    await enqueue_candidate_invite(
        candidate_email="a@ex.com",
        candidate_name="A",
        access_code="HM-1",
        package_title="Pack",
        corporate_name="Acme",
        origin="http://x",
    )

    names = [c.args[0] for c in pool.enqueue_job.await_args_list]
    assert names == [
        "task_send_nudge_email",
        "task_store_cached_report",
        "task_dispatch_candidate_invite",
    ]
