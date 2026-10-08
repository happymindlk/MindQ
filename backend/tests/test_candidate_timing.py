"""Strict-timer enforcement and telemetry persistence in CandidateService."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.exceptions import AssessmentTimeExpiredError
from app.schemas.response import ResponseSave
from app.services import candidate_service
from app.services.candidate_service import CandidateService, is_strict_expired
from app.services.runner_payload import STRICT_GRACE_SECONDS

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _assessment(*, timer_mode="strict", duration_seconds=180, questions=None, scoring_profile=None):
    return SimpleNamespace(
        id=uuid4(),
        timer_mode=timer_mode,
        duration_seconds=duration_seconds,
        time_limit_minutes=None,
        questions=questions or [],
        scoring_profile=scoring_profile,
    )


def _progress(started_seconds_ago):
    return SimpleNamespace(
        status="IN_PROGRESS",
        started_at=NOW - timedelta(seconds=started_seconds_ago),
        completed_at=None,
        score=None,
        facet_scores=None,
        client_duration_seconds=None,
        server_duration_seconds=None,
        overtime=None,
    )


@pytest.mark.parametrize(
    "timer_mode, elapsed, expected",
    [
        ("strict", 180 + STRICT_GRACE_SECONDS - 1, False),
        ("strict", 180 + STRICT_GRACE_SECONDS + 1, True),
        ("flexible", 10_000, False),
    ],
)
def test_is_strict_expired_respects_grace_and_mode(timer_mode, elapsed, expected):
    assert is_strict_expired(_assessment(timer_mode=timer_mode), _progress(elapsed), NOW) is expected


def test_untimed_strict_module_never_expires():
    assert is_strict_expired(_assessment(duration_seconds=None), _progress(99_999), NOW) is False


def test_not_started_attempt_is_not_expired():
    assert is_strict_expired(_assessment(), None, NOW) is False


@pytest.mark.asyncio
async def test_autosave_rejects_after_strict_deadline(monkeypatch):
    assessment = _assessment()
    progress = _progress(1000)
    monkeypatch.setattr(
        CandidateService,
        "require_writable_assessment",
        AsyncMock(return_value=(assessment, progress)),
    )
    monkeypatch.setattr(candidate_service, "_utcnow", lambda: NOW)
    session = AsyncMock()
    body = ResponseSave(assessment_id=assessment.id, question_id="q1", response={"answer": "a"}, elapsed_seconds=4.2)

    with pytest.raises(AssessmentTimeExpiredError):
        await CandidateService.autosave_response(session, SimpleNamespace(id=uuid4(), corporate_id=uuid4()), body)
    session.commit.assert_not_awaited()


def _empty_result():
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.scalars.return_value.all.return_value = []
    return result


@pytest.mark.asyncio
async def test_submit_after_deadline_discards_pending_and_flags_overtime(monkeypatch):
    assessment = _assessment(duration_seconds=60)
    progress = _progress(500)
    monkeypatch.setattr(
        CandidateService,
        "require_writable_assessment",
        AsyncMock(return_value=(assessment, progress)),
    )
    monkeypatch.setattr(CandidateService, "is_package_complete", AsyncMock(return_value=False))
    monkeypatch.setattr(candidate_service, "_utcnow", lambda: NOW)
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=_empty_result())
    pending = [ResponseSave(assessment_id=assessment.id, question_id="late", response={"answer": "x"})]

    result, _ = await CandidateService.submit_test(
        session,
        SimpleNamespace(id=uuid4(), corporate_id=uuid4()),
        assessment.id,
        pending_responses=pending,
        client_duration_seconds=58.4,
    )

    session.add.assert_not_called()
    assert result.status == "COMPLETED"
    assert float(result.server_duration_seconds) == 500.0
    assert float(result.client_duration_seconds) == 58.4
    assert result.overtime is True


@pytest.mark.asyncio
async def test_submit_in_time_stores_elapsed_and_facets(monkeypatch):
    questions = [{"id": "l1", "type": "likert", "facet": "Pace", "reverse_scored": True}]
    assessment = _assessment(timer_mode="flexible", duration_seconds=600, questions=questions)
    progress = _progress(120)
    monkeypatch.setattr(
        CandidateService,
        "require_writable_assessment",
        AsyncMock(return_value=(assessment, progress)),
    )
    monkeypatch.setattr(CandidateService, "is_package_complete", AsyncMock(return_value=True))
    monkeypatch.setattr(candidate_service, "_utcnow", lambda: NOW)

    added: list = []
    saved_row = SimpleNamespace(question_id="l1", response={"answer": 2})
    all_rows = MagicMock()
    all_rows.scalars.return_value.all.return_value = [saved_row]
    session = AsyncMock()
    session.add = MagicMock(side_effect=added.append)
    session.execute = AsyncMock(side_effect=[_empty_result(), all_rows])
    pending = [
        ResponseSave(assessment_id=assessment.id, question_id="l1", response={"answer": 2}, elapsed_seconds=7.456)
    ]

    result, complete = await CandidateService.submit_test(
        session,
        SimpleNamespace(id=uuid4(), corporate_id=uuid4()),
        assessment.id,
        pending_responses=pending,
    )

    assert complete is True
    assert float(added[0].elapsed_seconds) == 7.46
    assert result.facet_scores == {"Pace": {"mean": 4.0, "n": 1}}
    assert result.derived_profile is None
    assert result.overtime is False
    assert result.client_duration_seconds is None


OCTANT_CODES = ("PA", "BC", "DE", "FG", "HI", "JK", "LM", "NO")


def _ipc_questions():
    return [
        {"id": f"{octant}{i}", "type": "likert", "facet": octant}
        for octant in OCTANT_CODES
        for i in range(4)
    ]


def _ipc_rows(dominant: str):
    return [
        SimpleNamespace(
            question_id=q["id"],
            response={"answer": 5 if q["facet"] == dominant else 3},
            elapsed_seconds=None,
        )
        for q in _ipc_questions()
    ]


async def _submit_ipc(monkeypatch, rows):
    assessment = _assessment(
        timer_mode="flexible",
        duration_seconds=1800,
        questions=_ipc_questions(),
        scoring_profile="ipip_ipc_v1",
    )
    progress = _progress(300)
    monkeypatch.setattr(
        CandidateService,
        "require_writable_assessment",
        AsyncMock(return_value=(assessment, progress)),
    )
    monkeypatch.setattr(CandidateService, "is_package_complete", AsyncMock(return_value=False))
    monkeypatch.setattr(candidate_service, "_utcnow", lambda: NOW)
    all_rows = MagicMock()
    all_rows.scalars.return_value.all.return_value = rows
    session = AsyncMock()
    session.add = MagicMock()
    session.execute = AsyncMock(return_value=all_rows)
    result, _ = await CandidateService.submit_test(
        session, SimpleNamespace(id=uuid4(), corporate_id=uuid4()), assessment.id
    )
    session.commit.assert_awaited_once()
    return result


@pytest.mark.asyncio
async def test_submit_persists_derived_profile_for_ipc(monkeypatch):
    result = await _submit_ipc(monkeypatch, _ipc_rows("PA"))
    assert result.status == "COMPLETED"
    assert result.derived_profile["resolver"] == "ipip_ipc_v1"
    assert result.derived_profile["status"] == "complete"
    assert result.derived_profile["data"]["style_code"] == "PA"


@pytest.mark.asyncio
async def test_submit_with_sparse_octant_stores_insufficient_data(monkeypatch):
    rows = [r for r in _ipc_rows("PA") if r.question_id not in {"NO0", "NO1"}]
    result = await _submit_ipc(monkeypatch, rows)
    assert result.derived_profile["status"] == "insufficient_data"
    assert result.derived_profile["data"]["missing_octants"] == ["NO"]


@pytest.mark.asyncio
async def test_resolver_crash_does_not_block_submission(monkeypatch):
    def _boom(_key, _inputs):
        raise RuntimeError("resolver bug")

    monkeypatch.setattr(candidate_service, "resolve_profile", _boom)
    result = await _submit_ipc(monkeypatch, _ipc_rows("PA"))
    assert result.status == "COMPLETED"
    assert result.derived_profile is None
    assert result.facet_scores["PA"] == {"mean": 5.0, "n": 4}
