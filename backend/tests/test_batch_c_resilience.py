"""P1 Batch C: readiness, offloading, erasure purge retries, bounded queries,
Gemini executor, Sentry telemetry, and DB error mapping."""
from __future__ import annotations

import asyncio
import threading
import uuid
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from arq import Retry
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import main as main_mod
from app.jobs import tasks as tasks_mod
from app.services import storage

# --- P1-12: readiness ---------------------------------------------------------


@pytest.mark.asyncio
async def test_health_stays_dependency_free(async_client):
    res = await async_client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_ready_ok_when_db_ok_and_redis_optional(async_client, monkeypatch):
    monkeypatch.setattr(main_mod, "_check_database", AsyncMock(return_value="ok"))
    res = await async_client.get("/health/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "checks": {"database": "ok", "redis": "skipped"}}


@pytest.mark.asyncio
async def test_ready_503_when_database_down(async_client, monkeypatch):
    monkeypatch.setattr(
        main_mod, "_check_database", AsyncMock(side_effect=asyncio.TimeoutError())
    )
    res = await async_client.get("/health/ready")
    assert res.status_code == 503
    assert res.json()["checks"]["database"] == "fail"


@pytest.mark.asyncio
async def test_ready_pings_redis_and_fails_on_timeout(async_client, monkeypatch):
    monkeypatch.setattr(main_mod, "_check_database", AsyncMock(return_value="ok"))

    async def _hang():
        await asyncio.sleep(5)

    pool = MagicMock()
    pool.ping = _hang
    monkeypatch.setattr(main_mod, "get_arq_pool", lambda: pool)
    monkeypatch.setattr(main_mod, "READINESS_TIMEOUT_SECONDS", 0.05)
    res = await async_client.get("/health/ready")
    assert res.status_code == 503
    assert res.json()["checks"]["redis"] == "fail"


@pytest.mark.asyncio
async def test_ready_requires_redis_in_production(async_client, monkeypatch):
    monkeypatch.setattr(main_mod, "_check_database", AsyncMock(return_value="ok"))
    monkeypatch.setattr(main_mod.settings, "ENVIRONMENT", "production")
    res = await async_client.get("/health/ready")
    assert res.status_code == 503
    assert res.json()["checks"]["redis"] == "fail"


# --- P1-16: erasure purge job ------------------------------------------------


@pytest.mark.asyncio
async def test_purge_job_retries_then_fails_loudly(monkeypatch):
    def _boom(*_a, **_k):
        raise storage.StoragePurgeError("s3 down")

    monkeypatch.setattr(tasks_mod.storage_service, "purge_candidate_report_files", _boom)
    captured = []
    monkeypatch.setattr(tasks_mod, "capture_silent_failure", lambda *a, **k: captured.append(a[0]))
    corp, cand = str(uuid.uuid4()), str(uuid.uuid4())

    with pytest.raises(Retry):
        await tasks_mod.task_purge_candidate_report_files({"job_try": 1}, corp, cand)
    with pytest.raises(storage.StoragePurgeError):
        await tasks_mod.task_purge_candidate_report_files(
            {"job_try": tasks_mod.PURGE_MAX_TRIES}, corp, cand
        )
    assert captured == ["erasure_purge_failed"]


@pytest.mark.asyncio
async def test_purge_job_runs_strict_purge(monkeypatch):
    calls = []

    def _purge(corp, cand, *, strict):
        calls.append(strict)
        return 4

    monkeypatch.setattr(tasks_mod.storage_service, "purge_candidate_report_files", _purge)
    assert await tasks_mod.task_purge_candidate_report_files({}, uuid.uuid4(), uuid.uuid4()) == 4
    assert calls == [True]


def test_purge_job_registered_with_more_tries():
    from app.jobs.worker import WorkerSettings

    purge = [
        f for f in WorkerSettings.functions
        if getattr(f, "name", "") == "task_purge_candidate_report_files"
    ]
    assert purge and purge[0].max_tries == tasks_mod.PURGE_MAX_TRIES


def _s3_with_pages(pages):
    client = MagicMock()
    client.list_objects_v2.side_effect = pages
    return client


def test_strict_purge_raises_and_lenient_purge_returns_zero(monkeypatch):
    monkeypatch.setattr(storage, "_reports_bucket_safe", lambda: True)
    monkeypatch.setattr(storage.settings, "R2_REPORTS_BUCKET_NAME", "reports")
    client = MagicMock()
    client.list_objects_v2.side_effect = RuntimeError("timeout")
    monkeypatch.setattr(storage, "_s3_client", lambda: client)
    monkeypatch.setattr(storage, "capture_silent_failure", lambda *a, **k: None)
    corp, cand = uuid.uuid4(), uuid.uuid4()
    assert storage.purge_cached_reports(corp, cand) == 0
    with pytest.raises(storage.StoragePurgeError):
        storage.purge_cached_reports(corp, cand, strict=True)


def test_listing_follows_continuation_tokens():
    client = _s3_with_pages(
        [
            {"Contents": [{"Key": "a"}, {"Key": "b"}], "IsTruncated": True, "NextContinuationToken": "t1"},
            {"Contents": [{"Key": "c"}], "IsTruncated": False},
        ]
    )
    assert storage._list_object_keys(client, "bkt", "p/") == ["a", "b", "c"]
    assert client.list_objects_v2.call_args_list[1].kwargs["ContinuationToken"] == "t1"


# --- P1-11: storage off the event loop ---------------------------------------


def test_route_storage_calls_are_offloaded():
    import inspect

    from app.api.v1 import admin_ops, corporates, notifications

    for src in (
        inspect.getsource(admin_ops.upload_company_logo),
        inspect.getsource(corporates.upload_corporate_logo),
    ):
        assert "await run_in_threadpool(" in src
    reset_src = inspect.getsource(notifications)
    assert "run_in_threadpool(\n        storage_service.purge_cached_reports" in reset_src


# --- P1-17: bounded queries ---------------------------------------------------


@pytest.mark.asyncio
async def test_progress_summaries_is_one_grouped_query():
    from sqlalchemy.dialects import postgresql

    from app.services.progress_summary import progress_summaries

    seen = []

    async def _execute(stmt):
        seen.append(str(stmt.compile(dialect=postgresql.dialect())).upper())
        result = MagicMock()
        cid = uuid.uuid4()
        result.all.return_value = [(cid, 2, 1, 75.5)]
        return result

    session = SimpleNamespace(execute=_execute)
    out = await progress_summaries(session, [uuid.uuid4() for _ in range(50)])
    assert len(seen) == 1 and "GROUP BY" in seen[0]
    (summary,) = out.values()
    assert (summary.completed, summary.in_progress, summary.avg_score) == (2, 1, 75.5)


@pytest.mark.asyncio
async def test_progress_summaries_skips_empty_input():
    from app.services.progress_summary import assessment_counts, progress_summaries

    session = SimpleNamespace(execute=AsyncMock())
    assert await progress_summaries(session, []) == {}
    assert await assessment_counts(session, []) == {}
    session.execute.assert_not_awaited()


def test_zip_part_filename():
    from app.services.report_zip import zip_content_disposition

    assert "(part 2).zip" in zip_content_disposition("Big Round", 2)
    assert "(part" not in zip_content_disposition("Big Round")


# --- P1-19: Gemini executor ---------------------------------------------------

_probe: ContextVar[str] = ContextVar("probe", default="unset")


@pytest.mark.asyncio
async def test_gemini_calls_use_dedicated_threads_and_keep_context():
    from app.services import gemini_client

    gemini_client.shutdown_gemini_executor()
    _probe.set("background")

    def _work():
        return threading.current_thread().name, _probe.get()

    name, value = await gemini_client.run_gemini_call(_work)
    assert name.startswith("gemini")
    assert value == "background"  # retry-profile ContextVar survives the hop
    gemini_client.shutdown_gemini_executor()


# --- P1-18: Sentry ------------------------------------------------------------


def test_capture_silent_failure_is_noop_without_sentry():
    from app.sentry_init import capture_silent_failure

    capture_silent_failure("report_cache_upload_failed", RuntimeError("x"), key="k")


def test_capture_silent_failure_tags_event(monkeypatch):
    import sentry_sdk

    from app.sentry_init import capture_silent_failure

    client = MagicMock()
    client.is_active.return_value = True
    monkeypatch.setattr(sentry_sdk, "get_client", lambda: client)
    captured = []
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda exc: captured.append(exc))
    err = RuntimeError("s3")
    capture_silent_failure("erasure_purge_failed", err, candidate_id="c1")
    assert captured == [err]


# --- P1-20: DB error mapping + recovery ---------------------------------------


def _dbapi_error(cls, sqlstate=None, text="boom"):
    orig = Exception(text)
    if sqlstate:
        orig.sqlstate = sqlstate
    return cls("stmt", {}, orig)


@pytest.mark.asyncio
async def test_integrity_error_maps_to_409(async_client):
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/__test/integrity")
    async def _raise():
        raise _dbapi_error(IntegrityError, "23505", "duplicate key")

    main_mod.app.include_router(router)
    res = await async_client.get("/__test/integrity")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_deadlock_maps_to_503_with_retry_after(async_client):
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/__test/deadlock")
    async def _raise():
        raise _dbapi_error(DBAPIError, "40P01", "deadlock detected")

    main_mod.app.include_router(router)
    res = await async_client.get("/__test/deadlock")
    assert res.status_code == 503
    assert res.headers["retry-after"] == "1"


@pytest.mark.asyncio
async def test_retry_on_deadlock_reruns_once_then_succeeds():
    from app.database import retry_on_deadlock

    session = AsyncMock()
    op = AsyncMock(side_effect=[_dbapi_error(DBAPIError, "40P01"), "ok"])
    assert await retry_on_deadlock(op, session=session) == "ok"
    assert op.await_count == 2
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_on_deadlock_does_not_retry_other_errors():
    from app.database import retry_on_deadlock

    op = AsyncMock(side_effect=_dbapi_error(IntegrityError, "23505"))
    with pytest.raises(IntegrityError):
        await retry_on_deadlock(op, session=AsyncMock())
    assert op.await_count == 1


def test_disconnect_invalidates_only_the_broken_connection():
    from app.database import _invalidate_only_broken_connection

    ctx = SimpleNamespace(is_disconnect=True, invalidate_pool_on_disconnect=True)
    _invalidate_only_broken_connection(ctx)
    assert ctx.invalidate_pool_on_disconnect is False
    other = SimpleNamespace(is_disconnect=False, invalidate_pool_on_disconnect=True)
    _invalidate_only_broken_connection(other)
    assert other.invalidate_pool_on_disconnect is True


@pytest.mark.asyncio
async def test_run_db_op_with_retry_never_disposes_the_engine(monkeypatch):
    from app import database

    dispose = AsyncMock()
    monkeypatch.setattr(database, "engine", SimpleNamespace(dispose=dispose))
    err = _dbapi_error(DBAPIError, "08006", "connection reset")
    err.connection_invalidated = True
    op = AsyncMock(side_effect=[err, "ok"])
    assert await database.run_db_op_with_retry(op, session=AsyncMock()) == "ok"
    dispose.assert_not_awaited()


@pytest.mark.asyncio
async def test_autosave_route_retries_deadlock_victim(async_client, monkeypatch):
    from app.auth import get_current_candidate
    from app.database import get_db
    from app.services.candidate_service import CandidateService

    fake = SimpleNamespace(id=uuid.uuid4(), corporate_id=uuid.uuid4(), package_id=uuid.uuid4())

    async def _cand():
        return fake

    async def _db():
        yield AsyncMock()

    resp = SimpleNamespace(id=uuid.uuid4(), saved_at="2026-11-26T09:00:00Z")
    save = AsyncMock(side_effect=[_dbapi_error(DBAPIError, "40P01"), resp])
    monkeypatch.setattr(CandidateService, "autosave_response", save)
    main_mod.app.dependency_overrides[get_current_candidate] = _cand
    main_mod.app.dependency_overrides[get_db] = _db
    try:
        res = await async_client.post(
            "/api/v1/candidate/autosave",
            json={"assessment_id": str(uuid.uuid4()), "question_id": "q1", "response": {"answer": "a"}},
        )
    finally:
        main_mod.app.dependency_overrides.clear()
    assert res.status_code == 200
    assert save.await_count == 2
