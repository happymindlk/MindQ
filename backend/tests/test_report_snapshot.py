"""Pre-computed MindQ Report JSON snapshot helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.schemas.mindq_report import MindQReportResponse
from app.services import report_snapshot


def _report(candidate_id, **overrides) -> MindQReportResponse:
    base = dict(
        candidate_id=candidate_id,
        company_name="Acme",
        candidate_full_name="Pat Lee",
        candidate_email="pat@ex.com",
        target_role="Analyst",
        total_assessments_completed=1,
        executive_summary="Strong SQL fundamentals.",
        synthesis_status="ok",
    )
    base.update(overrides)
    return MindQReportResponse(**base)


@pytest.mark.asyncio
async def test_read_report_snapshot_returns_none_when_generating():
    candidate_id = uuid4()
    row = SimpleNamespace(
        synthesis_status="generating",
        payload=_report(candidate_id).model_dump(mode="json"),
    )
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result)

    assert await report_snapshot.read_report_snapshot(session, candidate_id) is None


@pytest.mark.asyncio
async def test_read_report_snapshot_returns_parsed_payload():
    candidate_id = uuid4()
    report = _report(candidate_id)
    row = SimpleNamespace(
        synthesis_status="ok",
        payload=report.model_dump(mode="json"),
    )
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result)

    loaded = await report_snapshot.read_report_snapshot(session, candidate_id)
    assert loaded is not None
    assert loaded.candidate_id == candidate_id
    assert loaded.executive_summary == "Strong SQL fundamentals."


@pytest.mark.asyncio
async def test_upsert_skips_generating_payloads():
    candidate = SimpleNamespace(id=uuid4(), corporate_id=uuid4(), package_id=uuid4())
    session = AsyncMock()
    await report_snapshot.upsert_report_snapshot(
        session, candidate, _report(candidate.id, synthesis_status="generating")
    )
    session.execute.assert_not_awaited()
