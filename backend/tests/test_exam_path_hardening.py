"""P1 Batch A: precise ALREADY_SUBMITTED mapping, expiry sweep isolation + SQL."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.exceptions import (
    PROGRESS_UNIQUE_CONSTRAINT,
    AssessmentAlreadySubmittedError,
    is_progress_unique_violation,
)
from app.services import assessment_expiry, candidate_service
from app.services.candidate_service import CandidateService

NOW = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)


def _integrity(sqlstate: str | None, constraint: str | None, text: str = "boom"):
    orig = Exception(text)
    if sqlstate:
        orig.sqlstate = sqlstate
    if constraint:
        orig.constraint_name = constraint
    return IntegrityError("stmt", {}, orig)


# --- P1-01: only the progress unique constraint means "already submitted" ----


def test_progress_unique_violation_detected_by_constraint_name():
    assert is_progress_unique_violation(_integrity("23505", PROGRESS_UNIQUE_CONSTRAINT))


def test_other_unique_violation_is_not_already_submitted():
    assert not is_progress_unique_violation(
        _integrity("23505", "candidate_session_logs_pkey")
    )


def test_fk_or_check_violation_is_not_already_submitted():
    assert not is_progress_unique_violation(_integrity("23503", None))
    assert not is_progress_unique_violation(_integrity("23514", None))


def test_constraint_name_in_message_fallback():
    exc = _integrity(
        None, None, f'duplicate key value violates unique constraint "{PROGRESS_UNIQUE_CONSTRAINT}"'
    )
    assert is_progress_unique_violation(exc)


@pytest.mark.asyncio
async def test_submit_non_progress_integrity_error_is_not_masked(monkeypatch):
    """A rolled-back submit must surface as an error (503), never as 409."""
    assessment = SimpleNamespace(
        id=uuid.uuid4(), duration_seconds=None, time_limit_minutes=None,
        title=None, scoring_profile=None, questions=[],
    )
    monkeypatch.setattr(
        CandidateService,
        "require_writable_assessment",
        AsyncMock(return_value=(assessment, None)),
    )
    monkeypatch.setattr(candidate_service, "_utcnow", lambda: NOW)
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock(side_effect=_integrity("23503", "fk_session_logs_assessment"))

    with pytest.raises(IntegrityError):
        await CandidateService.submit_test(
            session, SimpleNamespace(id=uuid.uuid4(), corporate_id=uuid.uuid4()), assessment.id
        )
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_progress_duplicate_still_maps_to_already_submitted(monkeypatch):
    assessment = SimpleNamespace(
        id=uuid.uuid4(), duration_seconds=None, time_limit_minutes=None,
        title=None, scoring_profile=None, questions=[],
    )
    monkeypatch.setattr(
        CandidateService,
        "require_writable_assessment",
        AsyncMock(return_value=(assessment, None)),
    )
    monkeypatch.setattr(candidate_service, "_utcnow", lambda: NOW)
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock(side_effect=_integrity("23505", PROGRESS_UNIQUE_CONSTRAINT))

    with pytest.raises(AssessmentAlreadySubmittedError) as info:
        await CandidateService.submit_test(
            session, SimpleNamespace(id=uuid.uuid4(), corporate_id=uuid.uuid4()), assessment.id
        )
    assert info.value.code == "ALREADY_SUBMITTED"


# --- P1-06: bounded, indexed, SKIP LOCKED sweep with per-row isolation -------


@pytest.mark.asyncio
async def test_claim_query_uses_index_skip_locked_and_limit():
    captured = {}

    async def _execute(stmt):
        captured["sql"] = str(
            stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False})
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    session = AsyncMock()
    session.execute = _execute
    assert await assessment_expiry.claim_expired_in_progress(session) == []
    sql = captured["sql"].upper()
    assert "CANDIDATE_PROGRESS.EXPIRES_AT <= NOW()" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "LIMIT" in sql
    assert "JOIN" not in sql  # no full IN_PROGRESS x assessments scan


def _progress_row():
    return SimpleNamespace(
        id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        assessment_id=uuid.uuid4(),
        expires_at=NOW - timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_one_bad_row_does_not_abort_the_sweep(monkeypatch):
    bad, good = _progress_row(), _progress_row()
    candidates = [
        SimpleNamespace(id=bad.candidate_id, corporate_id=uuid.uuid4()),
        SimpleNamespace(id=good.candidate_id, corporate_id=uuid.uuid4()),
    ]
    monkeypatch.setattr(
        assessment_expiry,
        "claim_expired_in_progress",
        AsyncMock(return_value=[bad, good]),
    )

    async def _finalize(_session, *, candidate, assessment_id, completed_at):
        if assessment_id == bad.assessment_id:
            raise RuntimeError("package closed / module deleted")
        return True

    monkeypatch.setattr(assessment_expiry, "finalize_one_expired", _finalize)
    enqueue = AsyncMock()
    monkeypatch.setattr(assessment_expiry, "enqueue_finalize_and_score_ai", enqueue)

    cand_result = MagicMock()
    cand_result.scalars.return_value.all.return_value = candidates
    session = AsyncMock()
    session.execute = AsyncMock(return_value=cand_result)

    finalized = await assessment_expiry.finalize_expired_assessments(session, now=NOW)

    assert finalized == [(good.candidate_id, good.assessment_id)]
    enqueue.assert_awaited_once_with(good.candidate_id, good.assessment_id)
    session.rollback.assert_awaited()  # failed row's transaction was cleaned up


# --- P1-06: HR read paths no longer run the sweep synchronously --------------


def test_hr_paths_do_not_call_the_sweep():
    import inspect

    from app.api.v1 import client as client_api

    for fn in (client_api.client_dashboard, client_api.client_pipeline):
        assert "ensure_expired_assessments_finalized" not in inspect.getsource(fn)
    assert "ensure_expired_assessments_finalized" not in inspect.getsource(
        CandidateService.get_candidates
    )
