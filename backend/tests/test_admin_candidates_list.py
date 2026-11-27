"""Ops GET /admin/candidates: candidate_overview rows served behind the ops JWT."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.admin_ops import router as admin_router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db


def _client(session: AsyncMock, *, ops: bool = True) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router, prefix="/admin")

    async def _db():
        yield session

    async def _ops():
        if not ops:
            raise HTTPException(status_code=403, detail="Operations role required")
        return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application)


def _row(package_id):
    return {
        "id": uuid4(),
        "corporate_id": uuid4(),
        "package_id": package_id,
        "full_name": "Ada Candidate",
        "email": "ada@example.com",
        "access_code": "ABC123",
        "logged_in_at": None,
        "created_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
        "package_title": "Suite",
        "total_assessments": 3,
        "completed_assessments": 2,
        "technical_score": Decimal("71.5"),
        "avg_score": Decimal("71.5"),
        "evaluated": False,
        "completed_at": None,
    }


def _session(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def test_lists_candidates_filtered_by_package():
    package_id = uuid4()
    session = _session([_row(package_id)])

    res = _client(session).get(f"/admin/candidates?package_id={package_id}")

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["package_id"] == str(package_id)
    assert body[0]["avg_score"] == 71.5
    assert body[0]["completed_assessments"] == 2
    params = session.execute.await_args.args[1]
    assert params == {"package_id": str(package_id)}


def test_lists_all_candidates_without_filter():
    session = _session([])

    res = _client(session).get("/admin/candidates")

    assert res.status_code == 200
    assert res.json() == []
    assert session.execute.await_args.args[1] == {"package_id": None}


def test_rejects_non_ops_user():
    session = _session([])

    res = _client(session, ops=False).get("/admin/candidates")

    assert res.status_code == 403
    session.execute.assert_not_called()


def _result(rows):
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    result.mappings.return_value.first.return_value = rows[0] if rows else None
    return result


def test_scorecard_returns_all_sections():
    package_id = uuid4()
    candidate = _row(package_id)
    assessment_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _result([candidate]),
            _result([{
                "payload": {"summary": "ok"},
                "status": "ok",
                "generated_at": datetime(2026, 11, 2, tzinfo=timezone.utc),
            }]),
            _result([{"id": assessment_id, "title": "Logic", "position": 0, "questions": [{"id": "q1"}]}]),
            _result([{"assessment_id": assessment_id, "question_id": "q1", "response": {"value": "a"}}]),
            _result([{
                "assessment_id": assessment_id,
                "status": "COMPLETED",
                "score": Decimal("80.00"),
                "completed_at": None,
            }]),
        ]
    )

    res = _client(session).get(f"/admin/candidates/{candidate['id']}/scorecard")

    assert res.status_code == 200
    body = res.json()
    assert body["candidate"]["id"] == str(candidate["id"])
    assert body["evaluation"]["payload"] == {"summary": "ok"}
    assert body["assessments"][0]["questions"] == [{"id": "q1"}]
    assert body["responses"][0]["response"] == {"value": "a"}
    assert body["progress"][0]["score"] == 80.0
    # Assessments are looked up by the candidate's package.
    assert session.execute.await_args_list[2].args[1] == {"package_id": str(package_id)}


def test_scorecard_without_evaluation_returns_null():
    candidate = _row(uuid4())
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_result([candidate]), _result([]), _result([]), _result([]), _result([])]
    )

    res = _client(session).get(f"/admin/candidates/{candidate['id']}/scorecard")

    assert res.status_code == 200
    assert res.json()["evaluation"] is None
    assert res.json()["progress"] == []


def test_scorecard_unknown_candidate_is_404():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result([]))

    res = _client(session).get(f"/admin/candidates/{uuid4()}/scorecard")

    assert res.status_code == 404
    assert session.execute.await_count == 1


def test_scorecard_rejects_non_ops_user():
    session = AsyncMock()

    res = _client(session, ops=False).get(f"/admin/candidates/{uuid4()}/scorecard")

    assert res.status_code == 403
    session.execute.assert_not_called()
