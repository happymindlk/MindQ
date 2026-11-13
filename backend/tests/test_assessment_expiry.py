"""Server-side auto-submit for timed assessments past their deadline."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.exceptions import AssessmentAlreadySubmittedError
from app.services.assessment_expiry import (
    finalize_expired_assessments,
    finalize_one_expired,
    list_expired_in_progress,
)
from app.services.runner_payload import STRICT_GRACE_SECONDS

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def _assessment(*, duration_seconds=180):
    return SimpleNamespace(
        id=uuid4(),
        duration_seconds=duration_seconds,
        time_limit_minutes=None,
        title="Timed Module",
        scoring_profile=None,
        questions=[],
    )


def _progress(*, started_seconds_ago, status="IN_PROGRESS"):
    return SimpleNamespace(
        id=uuid4(),
        candidate_id=uuid4(),
        assessment_id=uuid4(),
        status=status,
        started_at=NOW - timedelta(seconds=started_seconds_ago),
        completed_at=None,
    )


def _result_all(rows):
    result = MagicMock()
    result.all.return_value = rows
    result.scalars.return_value.all.return_value = [r[0] if isinstance(r, tuple) else r for r in rows]
    return result


@pytest.mark.asyncio
async def test_list_expired_in_progress_filters_by_deadline():
    expired_progress = _progress(started_seconds_ago=180 + STRICT_GRACE_SECONDS + 5)
    live_progress = _progress(started_seconds_ago=30)
    expired_assessment = _assessment()
    live_assessment = _assessment()
    expired_progress.assessment_id = expired_assessment.id
    live_progress.assessment_id = live_assessment.id

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=_result_all(
            [
                (expired_progress, expired_assessment),
                (live_progress, live_assessment),
            ]
        )
    )

    found = await list_expired_in_progress(session, now=NOW)

    assert len(found) == 1
    assert found[0][0] is expired_progress


@pytest.mark.asyncio
async def test_finalize_expired_transitions_and_enqueues_scoring(monkeypatch):
    assessment = _assessment(duration_seconds=60)
    progress = _progress(started_seconds_ago=500)
    progress.assessment_id = assessment.id
    candidate = SimpleNamespace(
        id=progress.candidate_id,
        corporate_id=uuid4(),
        package_id=uuid4(),
        deleted_at=None,
    )

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_all([(progress, assessment)]),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[candidate])))),
        ]
    )

    submit = AsyncMock(
        return_value=(
            SimpleNamespace(status="COMPLETED", assessment_id=assessment.id, completed_at=NOW),
            False,
        )
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(
        "app.services.assessment_expiry.CandidateService.submit_test",
        submit,
    )
    monkeypatch.setattr(
        "app.services.assessment_expiry.enqueue_finalize_and_score_ai",
        enqueue,
    )

    finalized = await finalize_expired_assessments(session, now=NOW, enqueue=True)

    assert finalized == [(candidate.id, assessment.id)]
    submit.assert_awaited_once()
    enqueue.assert_awaited_once_with(candidate.id, assessment.id)


@pytest.mark.asyncio
async def test_finalize_expired_is_idempotent_when_already_completed(monkeypatch):
    assessment = _assessment(duration_seconds=60)
    progress = _progress(started_seconds_ago=500)
    progress.assessment_id = assessment.id
    candidate = SimpleNamespace(
        id=progress.candidate_id,
        corporate_id=uuid4(),
        package_id=uuid4(),
        deleted_at=None,
    )

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result_all([(progress, assessment)]),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[candidate])))),
        ]
    )

    submit = AsyncMock(side_effect=AssessmentAlreadySubmittedError())
    enqueue = AsyncMock()
    monkeypatch.setattr(
        "app.services.assessment_expiry.CandidateService.submit_test",
        submit,
    )
    monkeypatch.setattr(
        "app.services.assessment_expiry.enqueue_finalize_and_score_ai",
        enqueue,
    )

    finalized = await finalize_expired_assessments(session, now=NOW, enqueue=True)

    assert finalized == []
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_one_expired_returns_false_on_race():
    session = AsyncMock()
    with patch(
        "app.services.assessment_expiry.CandidateService.submit_test",
        new=AsyncMock(side_effect=AssessmentAlreadySubmittedError()),
    ):
        claimed = await finalize_one_expired(
            session,
            candidate=SimpleNamespace(id=uuid4(), corporate_id=uuid4()),
            assessment_id=uuid4(),
        )
    assert claimed is False


@pytest.mark.asyncio
async def test_finalize_expired_twice_stays_idempotent(monkeypatch):
    """Second sweep finds nothing once status is COMPLETED."""
    assessment = _assessment(duration_seconds=60)
    progress = _progress(started_seconds_ago=500, status="COMPLETED")
    progress.assessment_id = assessment.id

    session = AsyncMock()
    # list_expired filters by is_strict_expired but status is still returned from
    # the query mock; the SQL WHERE status=IN_PROGRESS would exclude this row.
    # Simulate an empty second sweep.
    session.execute = AsyncMock(return_value=_result_all([]))

    enqueue = AsyncMock()
    monkeypatch.setattr(
        "app.services.assessment_expiry.enqueue_finalize_and_score_ai",
        enqueue,
    )

    first = await finalize_expired_assessments(session, now=NOW)
    second = await finalize_expired_assessments(session, now=NOW)

    assert first == []
    assert second == []
    enqueue.assert_not_awaited()
