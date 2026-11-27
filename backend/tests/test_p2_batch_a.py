"""P2 Batch A: queue idempotency, DB clock sync, upload bounds.

Covers MINDQ_FAILURE_AUDIT items P2-01, P2-02, P2-03, P2-04, P2-05, P2-06
and P2-09.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.exceptions import AssessmentTimeExpiredError, PackageClosedError
from app.jobs import enqueue as enqueue_mod
from app.jobs import tasks as tasks_mod
from app.jobs.settings import set_arq_pool_for_tests
from app.services import background, candidate_service, sent_emails
from app.services.candidate_service import (
    DB_NOW_INFO_KEY,
    CandidateService,
    request_clock,
)

APP_NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
# The database clock is ahead of this app node by 10 minutes (clock skew).
DB_NOW = APP_NOW + timedelta(minutes=10)


def _sql(stmt) -> str:
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False})
    ).lower()


def _session_factory(session) -> MagicMock:
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.fixture(autouse=True)
def _no_pool():
    set_arq_pool_for_tests(None)
    yield
    set_arq_pool_for_tests(None)


# ---------------------------------------------------------------------------
# P2-01: email send idempotency
# ---------------------------------------------------------------------------

WORKER_CTX = {
    "job_id": "nudge:abc",
    "job_try": 1,
    "enqueue_time": datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc),
}


def test_idempotency_key_is_none_for_inline_runs():
    assert sent_emails.email_idempotency_key({}) is None
    assert sent_emails.email_idempotency_key(None) is None


def test_idempotency_key_scopes_reused_job_id_by_enqueue_time():
    first = sent_emails.email_idempotency_key(WORKER_CTX)
    rerun = sent_emails.email_idempotency_key({**WORKER_CTX, "job_try": 2})
    next_day = sent_emails.email_idempotency_key(
        {**WORKER_CTX, "enqueue_time": WORKER_CTX["enqueue_time"] + timedelta(days=1)}
    )
    assert first.startswith("nudge:abc@")
    # A restart re-run of the same queued job shares the key ...
    assert rerun == first
    # ... but a later, legitimate nudge reusing the job id does not.
    assert next_day != first


class _MarkerTable:
    """In-memory stand-in for ``sent_emails`` (primary key semantics)."""

    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.released: list[str] = []

    async def claim(self, key: str, *, kind: str) -> bool:
        del kind
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def release(self, key: str) -> None:
        self.released.append(key)
        self.keys.discard(key)


@pytest.fixture
def markers(monkeypatch) -> _MarkerTable:
    table = _MarkerTable()
    monkeypatch.setattr(tasks_mod, "claim_email_send", table.claim)
    monkeypatch.setattr(tasks_mod, "release_email_send", table.release)
    return table


@pytest.mark.asyncio
async def test_nudge_rerun_after_worker_restart_does_not_resend(markers):
    send = AsyncMock(return_value=True)
    with patch.object(tasks_mod.EmailService, "send_nudge_email", send):
        await tasks_mod.task_send_nudge_email(WORKER_CTX, "a@ex.com", "A", "HM-1", "Pack")
        # Worker restarted mid-job: ARQ re-runs the same job (same ctx).
        await tasks_mod.task_send_nudge_email(
            {**WORKER_CTX, "job_try": 2}, "a@ex.com", "A", "HM-1", "Pack"
        )
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_invite_rerun_does_not_resend(markers, monkeypatch):
    dispatch = AsyncMock(return_value=True)
    monkeypatch.setattr("app.api.v1.invites._dispatch_candidate_invite", dispatch)
    ctx = {**WORKER_CTX, "job_id": "invite:a@ex.com:HM-1"}
    kwargs = dict(
        candidate_email="a@ex.com",
        candidate_name="A",
        access_code="HM-1",
        package_title="Pack",
        corporate_name="Acme",
        origin="http://localhost:5173",
    )
    await tasks_mod.task_dispatch_candidate_invite(ctx, **kwargs)
    await tasks_mod.task_dispatch_candidate_invite(ctx, **kwargs)
    dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_package_share_rerun_does_not_resend(markers, monkeypatch):
    send = MagicMock(return_value={"id": "ses-1"})
    monkeypatch.setattr(tasks_mod, "send_transactional_email", send)
    ctx = {**WORKER_CTX, "job_id": "package_share:p:hr@ex.com"}
    await tasks_mod.task_send_package_share(ctx, "hr@ex.com", "S", "<p>x</p>")
    await tasks_mod.task_send_package_share(ctx, "hr@ex.com", "S", "<p>x</p>")
    assert send.call_count == 1


@pytest.mark.asyncio
async def test_failed_send_releases_marker_so_rerun_can_retry(markers):
    send = AsyncMock(side_effect=[False, True])
    with patch.object(tasks_mod.EmailService, "send_nudge_email", send):
        await tasks_mod.task_send_nudge_email(WORKER_CTX, "a@ex.com", "A", "HM-1", "Pack")
        await tasks_mod.task_send_nudge_email(WORKER_CTX, "a@ex.com", "A", "HM-1", "Pack")
    assert send.await_count == 2
    assert len(markers.released) == 1


@pytest.mark.asyncio
async def test_raising_send_releases_marker_and_propagates(markers):
    async def _boom():
        raise RuntimeError("ses down")

    with pytest.raises(RuntimeError):
        await tasks_mod._send_once(WORKER_CTX, kind="nudge", send=_boom)
    assert markers.released and not markers.keys


@pytest.mark.asyncio
async def test_inline_run_skips_marker_table(monkeypatch):
    claim = AsyncMock()
    monkeypatch.setattr(tasks_mod, "claim_email_send", claim)
    send = AsyncMock(return_value=True)
    with patch.object(tasks_mod.EmailService, "send_nudge_email", send):
        await tasks_mod.task_send_nudge_email({}, "a@ex.com", "A", "HM-1", "Pack")
    claim.assert_not_awaited()
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_claim_email_send_inserts_before_send_with_on_conflict(monkeypatch):
    result = MagicMock()
    result.scalar_one_or_none.return_value = "k"
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    monkeypatch.setattr(sent_emails, "SessionLocal", _session_factory(session))

    assert await sent_emails.claim_email_send("k", kind="nudge") is True
    sql = _sql(session.execute.await_args.args[0])
    assert "insert into sent_emails" in sql
    assert "on conflict (idempotency_key) do nothing" in sql
    assert "returning" in sql
    session.commit.assert_awaited_once()

    result.scalar_one_or_none.return_value = None
    assert await sent_emails.claim_email_send("k", kind="nudge") is False


@pytest.mark.asyncio
async def test_claim_email_send_fails_open_on_db_error(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(sent_emails, "SessionLocal", _session_factory(session))
    assert await sent_emails.claim_email_send("k", kind="invite") is True


# ---------------------------------------------------------------------------
# P2-02: HR completion email guard
# ---------------------------------------------------------------------------


def _hr_session():
    session = MagicMock()
    corporate = SimpleNamespace(contact_email="hr@acme.test", name="Acme")
    corp_result = MagicMock()
    corp_result.scalar_one_or_none.return_value = corporate
    session.execute = AsyncMock(return_value=corp_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _patch_hr_flow(monkeypatch, session):
    candidate = SimpleNamespace(
        id=uuid4(),
        package_id=uuid4(),
        corporate_id=uuid4(),
        full_name="Cand",
        email="c@ex.com",
    )
    monkeypatch.setattr(background, "SessionLocal", _session_factory(session))
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService, "is_package_complete", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        background.PackageService,
        "get_package",
        AsyncMock(return_value=SimpleNamespace(title="Pack")),
    )
    return candidate


@pytest.mark.asyncio
async def test_claim_hr_notification_is_conditional_update_returning():
    result = MagicMock()
    result.scalar_one_or_none.return_value = uuid4()
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    assert await background.claim_hr_notification(session, uuid4()) is True
    sql = _sql(session.execute.await_args.args[0])
    assert sql.startswith("update candidates set hr_notified_at=now()")
    assert "hr_notified_at is null" in sql
    assert "returning candidates.id" in sql


@pytest.mark.asyncio
async def test_concurrent_completions_send_one_hr_email(monkeypatch):
    session = _hr_session()
    _patch_hr_flow(monkeypatch, session)
    claimed: set = set()
    lock = asyncio.Lock()

    async def _claim(_session, candidate_id):
        async with lock:  # the row lock serializes the conditional UPDATE
            if candidate_id in claimed:
                return False
            claimed.add(candidate_id)
            return True

    monkeypatch.setattr(background, "claim_hr_notification", _claim)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(background.EmailService, "send_hr_completion_email", send)

    candidate_id = uuid4()
    await asyncio.gather(
        background.notify_hr_if_package_complete(candidate_id),
        background.notify_hr_if_package_complete(candidate_id),
    )
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_hr_email_already_claimed_is_skipped(monkeypatch):
    session = _hr_session()
    _patch_hr_flow(monkeypatch, session)
    monkeypatch.setattr(background, "claim_hr_notification", AsyncMock(return_value=False))
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(background.EmailService, "send_hr_completion_email", send)
    await background.notify_hr_if_package_complete(uuid4())
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_hr_email_releases_claim(monkeypatch):
    session = _hr_session()
    _patch_hr_flow(monkeypatch, session)
    monkeypatch.setattr(background, "claim_hr_notification", AsyncMock(return_value=True))
    release = AsyncMock()
    monkeypatch.setattr(background, "release_hr_notification", release)
    monkeypatch.setattr(
        background.EmailService, "send_hr_completion_email", AsyncMock(return_value=False)
    )
    candidate_id = uuid4()
    await background.notify_hr_if_package_complete(candidate_id)
    release.assert_awaited_once_with(session, candidate_id)


@pytest.mark.asyncio
async def test_hr_reset_clears_hr_notified_at():
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    candidate = SimpleNamespace(id=uuid4(), logged_in_at=APP_NOW, hr_notified_at=APP_NOW)
    await CandidateService.reset_assessment(session, candidate)
    assert candidate.hr_notified_at is None


# ---------------------------------------------------------------------------
# P2-03: expire / refresh job ids
# ---------------------------------------------------------------------------


def test_expire_job_id_is_scoped_to_attempt_start():
    cand, assess = uuid4(), uuid4()
    first = enqueue_mod._job_id_expire(cand, assess, APP_NOW)
    restarted = enqueue_mod._job_id_expire(cand, assess, APP_NOW + timedelta(minutes=5))
    assert first == f"expire:{cand}:{assess}:{int(APP_NOW.timestamp())}"
    assert first != restarted


@pytest.mark.asyncio
async def test_restart_after_reset_enqueues_new_expire_job():
    """ARQ dedupes on job id; the restarted attempt must get a fresh one."""
    seen: set[str] = set()

    async def _enqueue(_name, *_args, _job_id, **_kw):
        if _job_id in seen:
            return None
        seen.add(_job_id)
        return SimpleNamespace(job_id=_job_id)

    pool = MagicMock()
    pool.enqueue_job = AsyncMock(side_effect=_enqueue)
    set_arq_pool_for_tests(pool)
    cand, assess = uuid4(), uuid4()

    old = await enqueue_mod.enqueue_finalize_expired_assessment(
        cand, assess, defer_until=APP_NOW + timedelta(minutes=3), started_at=APP_NOW
    )
    restarted_at = APP_NOW + timedelta(minutes=1)
    new = await enqueue_mod.enqueue_finalize_expired_assessment(
        cand, assess, defer_until=restarted_at + timedelta(minutes=3), started_at=restarted_at
    )
    assert old is not None and new is not None
    assert new.job_id.endswith(str(int(restarted_at.timestamp())))


@pytest.mark.asyncio
async def test_refresh_rerun_uses_distinct_deferred_job_id():
    pool = MagicMock()
    pool.enqueue_job = AsyncMock(return_value=SimpleNamespace(job_id="x"))
    set_arq_pool_for_tests(pool)
    cand = uuid4()
    await enqueue_mod.enqueue_refresh_report_synthesis_rerun(cand, token="abc")
    args, kwargs = pool.enqueue_job.await_args
    assert args == ("task_refresh_report_synthesis", str(cand))
    assert kwargs["_job_id"] == f"refresh:{cand}:rerun:abc"
    assert kwargs["_job_id"] != enqueue_mod._job_id_refresh(cand)
    assert kwargs["_defer_by"] == enqueue_mod.REFRESH_RERUN_DELAY


@pytest.mark.asyncio
async def test_refresh_rerun_is_noop_without_redis():
    assert await enqueue_mod.enqueue_refresh_report_synthesis_rerun(uuid4(), token="t") is None


def _refresh_env(monkeypatch, digests: list[str | None]):
    monkeypatch.setattr(background, "_ai_jobs_inflight", {})
    monkeypatch.setattr(background, "prewarm_report_pdf", AsyncMock())
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=empty)
    session.rollback = AsyncMock()
    monkeypatch.setattr(background, "SessionLocal", _session_factory(session))
    candidate = SimpleNamespace(id=uuid4(), package_id=uuid4())
    monkeypatch.setattr(
        background.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    monkeypatch.setattr(
        background.CandidateService, "evaluate_jd_if_package_complete", AsyncMock()
    )
    monkeypatch.setattr(
        background.TechnicalEvalService,
        "has_missing_open_evals",
        staticmethod(lambda *_a, **_k: False),
    )
    digest_iter = iter(digests)
    monkeypatch.setattr(
        "app.services.jd_scoring.JdScoringService.current_input_digest",
        AsyncMock(side_effect=lambda *_a, **_k: next(digest_iter)),
    )
    rerun = AsyncMock()
    monkeypatch.setattr(enqueue_mod, "enqueue_refresh_report_synthesis_rerun", rerun)
    return candidate, rerun


@pytest.mark.asyncio
async def test_refresh_requeues_when_inputs_changed_during_run(monkeypatch):
    new_digest = "b" * 64
    candidate, rerun = _refresh_env(monkeypatch, ["a" * 64, new_digest])
    await background.refresh_report_synthesis(candidate.id)
    rerun.assert_awaited_once_with(candidate.id, token=new_digest[:16])


@pytest.mark.asyncio
async def test_refresh_does_not_requeue_when_inputs_unchanged(monkeypatch):
    candidate, rerun = _refresh_env(monkeypatch, ["a" * 64, "a" * 64])
    await background.refresh_report_synthesis(candidate.id)
    rerun.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_skipped_while_inflight_is_requeued(monkeypatch):
    candidate, rerun = _refresh_env(monkeypatch, [])
    background._ai_jobs_inflight[candidate.id] = 1
    await background.refresh_report_synthesis(candidate.id)
    rerun.assert_awaited_once()
    assert rerun.await_args.kwargs["token"].startswith("inflight-")


# ---------------------------------------------------------------------------
# P2-04: no PDF bytes in Redis job arguments
# ---------------------------------------------------------------------------


def test_store_cached_report_is_not_a_worker_function():
    from app.jobs.worker import WorkerSettings

    names = {getattr(f, "name", getattr(f, "__name__", None)) for f in WorkerSettings.functions}
    assert "task_store_cached_report" not in names


def test_no_registered_task_accepts_bytes():
    for entry in tasks_mod.TASK_FUNCTIONS:
        fn = getattr(entry, "coroutine", entry)
        for param in inspect.signature(fn).parameters.values():
            assert "bytes" not in str(param.annotation), (fn.__name__, param.name)


@pytest.mark.asyncio
async def test_enqueue_refuses_binary_payload_even_with_pool():
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    set_arq_pool_for_tests(pool)
    with pytest.raises(enqueue_mod.BinaryJobPayloadError):
        await enqueue_mod._enqueue_or_run(
            task_name="task_x",
            coroutine_factory=AsyncMock(),
            args=("key", b"%PDF-1.7"),
        )
    with pytest.raises(enqueue_mod.BinaryJobPayloadError):
        await enqueue_mod._enqueue_or_run(
            task_name="task_x",
            coroutine_factory=AsyncMock(),
            kwargs={"content": bytearray(b"x")},
        )
    pool.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_miss_uploads_in_process_not_via_redis(monkeypatch):
    pool = MagicMock()
    pool.enqueue_job = AsyncMock()
    set_arq_pool_for_tests(pool)
    store = MagicMock(return_value="key")
    monkeypatch.setattr(tasks_mod.storage_service, "store_cached_report", store)
    spawned = await enqueue_mod.enqueue_store_cached_report(uuid4(), uuid4(), "ck", b"%PDF")
    await spawned
    store.assert_called_once()
    pool.enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# P2-05: database clock for expiry / launchability / sweep
# ---------------------------------------------------------------------------


@pytest.fixture
def skewed_app_clock(monkeypatch):
    """This app node's clock lags the database by 10 minutes."""
    monkeypatch.setattr(candidate_service, "_utcnow", lambda: APP_NOW)
    from app.services import assessment_expiry

    monkeypatch.setattr(assessment_expiry, "_utcnow", lambda: APP_NOW)


def _timed_assessment(duration=180):
    return SimpleNamespace(
        id=uuid4(),
        package_id=uuid4(),
        duration_seconds=duration,
        time_limit_minutes=None,
        title="Timed",
        scoring_profile=None,
        questions=[],
    )


def _running(started_at, duration=180):
    return SimpleNamespace(
        id=uuid4(),
        candidate_id=uuid4(),
        assessment_id=uuid4(),
        status="IN_PROGRESS",
        started_at=started_at,
        expires_at=started_at + timedelta(seconds=duration),
        completed_at=None,
        client_duration_seconds=None,
        server_duration_seconds=None,
        overtime=None,
    )


def _session_with_row(row):
    result = MagicMock()
    result.first.return_value = row
    session = AsyncMock()
    session.info = {}
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_runner_gate_selects_db_now_and_uses_it_for_launchability(skewed_app_clock):
    candidate = SimpleNamespace(id=uuid4(), package_id=uuid4())
    assessment = _timed_assessment()
    # The package closed 5 minutes ago by the DB clock, but is still open by
    # the lagging app clock. Unstarted modules must not launch after close.
    close_time = APP_NOW + timedelta(minutes=5)
    session = _session_with_row((assessment, None, None, close_time, DB_NOW))

    with pytest.raises(PackageClosedError):
        await CandidateService.load_runner_context(session, candidate, assessment.id)
    assert "now() as db_now" in _sql(session.execute.await_args.args[0])
    assert request_clock(session) == DB_NOW


@pytest.mark.asyncio
async def test_autosave_gate_expires_on_db_clock(skewed_app_clock):
    candidate = SimpleNamespace(id=uuid4(), package_id=uuid4())
    assessment = _timed_assessment(duration=180)
    # By the app clock only 4 minutes elapsed (inside the deadline + grace);
    # by the DB clock 14 minutes elapsed.
    progress = _running(APP_NOW - timedelta(minutes=4) + timedelta(seconds=60))
    session = _session_with_row((assessment, progress, None, None, True, DB_NOW))

    with pytest.raises(AssessmentTimeExpiredError):
        await CandidateService._gate_autosave(session, candidate, assessment.id, "q1")
    assert "now() as db_now" in _sql(session.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_submit_and_start_stamp_from_db_clock(skewed_app_clock, monkeypatch):
    assessment = _timed_assessment(duration=3600)
    progress = _running(DB_NOW - timedelta(minutes=1), duration=3600)
    session = AsyncMock()
    session.info = {DB_NOW_INFO_KEY: DB_NOW}
    session.add = MagicMock()
    monkeypatch.setattr(
        CandidateService,
        "require_writable_assessment",
        AsyncMock(return_value=(assessment, progress)),
    )
    monkeypatch.setattr(
        CandidateService, "get_submit_meta", AsyncMock(return_value=(False, ""))
    )
    done, *_ = await CandidateService.submit_test(
        session, SimpleNamespace(id=uuid4(), corporate_id=uuid4()), assessment.id
    )
    assert done.completed_at == DB_NOW
    assert float(done.server_duration_seconds) == 60.0

    fresh = SimpleNamespace(status="NOT_STARTED", started_at=None, expires_at=None)
    started = await CandidateService.ensure_started(
        session, SimpleNamespace(id=uuid4(), corporate_id=uuid4()), assessment, fresh
    )
    assert started.started_at == DB_NOW
    assert started.expires_at == DB_NOW + timedelta(seconds=3600)


def test_request_clock_falls_back_to_app_clock_without_gate(skewed_app_clock):
    assert request_clock(SimpleNamespace(info={})) == APP_NOW
    assert request_clock(AsyncMock()) == APP_NOW


@pytest.mark.asyncio
async def test_expiry_listing_uses_db_now_column(skewed_app_clock):
    from app.services.assessment_expiry import list_expired_in_progress

    assessment = _timed_assessment(duration=180)
    # Expired 7 minutes ago by DB clock; still running by the app clock.
    progress = _running(APP_NOW, duration=180)
    progress.assessment_id = assessment.id
    result = MagicMock()
    result.all.return_value = [(progress, assessment, DB_NOW)]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    found = await list_expired_in_progress(session)
    assert [p for p, _a in found] == [progress]
    assert "now() as db_now" in _sql(session.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_sweep_claim_compares_against_db_now():
    from app.services.assessment_expiry import claim_expired_in_progress

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    await claim_expired_in_progress(session)
    sql = _sql(session.execute.await_args.args[0])
    assert "candidate_progress.expires_at <= now()" in sql


# ---------------------------------------------------------------------------
# P2-06: throttle last_seen writes
# ---------------------------------------------------------------------------


def _last_seen_db(stamp):
    result = MagicMock()
    result.scalar_one_or_none.return_value = stamp
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_last_seen_update_is_conditional_on_60s_window():
    from app.auth import touch_last_seen_throttled

    db = _last_seen_db(None)
    candidate = MagicMock()
    candidate.id = uuid4()
    assert await touch_last_seen_throttled(db, candidate) is False
    sql = _sql(db.execute.await_args.args[0])
    assert "update candidates set session_last_seen_at=now()" in sql
    assert "session_last_seen_at is null" in sql
    assert "session_last_seen_at < now() - interval '60 seconds'" in sql
    # Inside the window: no row written, so no commit and no refresh.
    db.commit.assert_not_awaited()
    db.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_last_seen_stale_writes_and_commits_once():
    from app.auth import touch_last_seen_throttled
    from app.models.candidate import Candidate

    db = _last_seen_db(DB_NOW)
    candidate = Candidate(id=uuid4(), session_last_seen_at=APP_NOW - timedelta(minutes=5))
    assert await touch_last_seen_throttled(db, candidate) is True
    db.commit.assert_awaited_once()
    assert candidate.session_last_seen_at == DB_NOW


@pytest.mark.asyncio
async def test_autosave_burst_does_not_commit_candidate_row(monkeypatch):
    """Repeated authenticated requests inside 60s never commit last_seen."""
    from app import auth

    candidate = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(
        auth.CandidateService, "get_candidate", AsyncMock(return_value=candidate)
    )
    token = auth.issue_candidate_token(
        SimpleNamespace(id=candidate.id, corporate_id=uuid4(), package_id=uuid4())
    )
    db = _last_seen_db(None)
    for _ in range(5):
        got = await auth.get_current_candidate(authorization=f"Bearer {token}", db=db)
        assert got is candidate
    assert db.execute.await_count == 5
    db.commit.assert_not_awaited()
    db.refresh.assert_not_awaited()


# ---------------------------------------------------------------------------
# P2-09: streaming upload size caps
# ---------------------------------------------------------------------------


class _ChunkedUpload:
    def __init__(self, total: int) -> None:
        self.remaining = total
        self.reads = 0
        self.size = None

    async def read(self, n: int = -1) -> bytes:
        self.reads += 1
        take = self.remaining if n < 0 else min(n, self.remaining)
        self.remaining -= take
        return b"x" * take


@pytest.mark.asyncio
async def test_read_upload_capped_stops_at_cap_without_reading_rest():
    from app.services.upload_limits import UploadTooLargeError, read_upload_capped

    upload = _ChunkedUpload(total=50 * 1024 * 1024)
    with pytest.raises(UploadTooLargeError):
        await read_upload_capped(upload, 1024 * 1024, chunk_size=64 * 1024)
    # Stopped right after crossing 1 MiB instead of reading all 50 MiB.
    assert upload.reads == 17
    assert upload.remaining > 40 * 1024 * 1024


@pytest.mark.asyncio
async def test_read_upload_capped_returns_bytes_within_cap():
    from app.services.upload_limits import read_upload_capped

    upload = _ChunkedUpload(total=1000)
    assert await read_upload_capped(upload, 1000, chunk_size=64) == b"x" * 1000


def test_content_length_precheck():
    from app.services.upload_limits import (
        MULTIPART_OVERHEAD_BYTES,
        UploadTooLargeError,
        check_content_length,
    )

    check_content_length(None, 10)
    check_content_length("garbage", 10)
    check_content_length(str(10 + MULTIPART_OVERHEAD_BYTES), 10)
    with pytest.raises(UploadTooLargeError):
        check_content_length(str(11 + MULTIPART_OVERHEAD_BYTES), 10)


@pytest.fixture
def logo_client():
    from app.api.v1.corporates import router
    from app.auth import HRUserContext, get_current_hr_user
    from app.database import get_db

    corp_id = uuid4()
    application = FastAPI()
    application.include_router(router, prefix="/corporates")

    async def _hr():
        return HRUserContext(user_id=uuid4(), corporate_id=corp_id, email="hr@test.com")

    async def _db():
        yield None

    application.dependency_overrides[get_current_hr_user] = _hr
    application.dependency_overrides[get_db] = _db
    return TestClient(application), corp_id


def test_logo_over_cap_is_413_and_never_uploaded(logo_client):
    from app.services.storage import LOGO_MAX_BYTES

    client, corp_id = logo_client
    big = b"\x89PNG\r\n\x1a\n" + b"x" * LOGO_MAX_BYTES
    with patch("app.api.v1.corporates.upload_logo") as upload:
        res = client.post(
            f"/corporates/{corp_id}/logo",
            files={"file": ("logo.png", BytesIO(big), "image/png")},
        )
    assert res.status_code == 413
    upload.assert_not_called()


def test_logo_declared_content_length_over_cap_skips_reading(logo_client):
    client, corp_id = logo_client
    with patch("app.api.v1.corporates.read_upload_capped") as read:
        res = client.post(
            f"/corporates/{corp_id}/logo",
            files={"file": ("logo.png", BytesIO(b"\x89PNG"), "image/png")},
            headers={"content-length": str(100 * 1024 * 1024)},
        )
    assert res.status_code == 413
    read.assert_not_called()


def _jd_client() -> TestClient:
    from app.api.v1.packages import router as packages_router
    from app.auth import HRUserContext, get_current_ops_user

    application = FastAPI()
    application.include_router(packages_router, prefix="/api/v1/packages")

    async def _ops():
        return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")

    application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application)


def test_jd_pdf_over_cap_is_413_without_parsing():
    from app.services.jd_pdf import MAX_PDF_BYTES

    with patch("app.api.v1.packages.extract_jd_text") as extract:
        res = _jd_client().post(
            "/api/v1/packages/jd/extract-pdf",
            files={"file": ("jd.pdf", BytesIO(b"%PDF-" + b"x" * MAX_PDF_BYTES), "application/pdf")},
        )
    assert res.status_code == 413
    extract.assert_not_called()


def test_jd_pdf_declared_content_length_over_cap_skips_reading():
    with patch("app.api.v1.packages.read_upload_capped") as read:
        res = _jd_client().post(
            "/api/v1/packages/jd/extract-pdf",
            files={"file": ("jd.pdf", BytesIO(b"%PDF-"), "application/pdf")},
            headers={"content-length": str(500 * 1024 * 1024)},
        )
    assert res.status_code == 413
    read.assert_not_called()
