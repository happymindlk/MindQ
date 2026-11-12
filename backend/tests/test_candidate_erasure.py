"""DELETE /api/v1/admin/candidates/{id} — end-to-end candidate erasure."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.sql.dml import Delete, Update

from app.api.v1.notifications import router as notifications_router
from app.auth import HRUserContext, get_current_hr_user
from app.database import get_db
from app.services.candidate_service import CandidateService
from app.services import storage as storage_service
from app.schemas.technical_eval import TechnicalItemEvaluation
from app.services.technical_eval import TechnicalEvalService


def _app(*, corporate_id, role: str = "hr", user_id=None) -> TestClient:
    application = FastAPI()
    application.include_router(notifications_router, prefix="/api/v1/admin/candidates")
    actor = user_id or uuid4()

    async def _db():
        yield AsyncMock()

    async def _hr():
        return HRUserContext(
            user_id=actor,
            corporate_id=corporate_id,
            email="user@t.com",
            role=role,
        )

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_hr_user] = _hr
    return TestClient(application)


def _candidate(*, corporate_id):
    return SimpleNamespace(
        id=uuid4(),
        corporate_id=corporate_id,
        package_id=uuid4(),
        full_name="Ada Lovelace",
        email="ada@example.com",
        access_code="ABC-123",
        logged_in_at=datetime.now(timezone.utc),
    )


def test_erase_returns_404_when_candidate_missing():
    corp = uuid4()
    with patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=None)):
        res = _app(corporate_id=corp).delete(f"/api/v1/admin/candidates/{uuid4()}")

    assert res.status_code == 404
    assert res.json() == {"detail": "Candidate not found"}


def test_erase_cross_tenant_hr_returns_404_and_skips_mutation():
    caller_corp = uuid4()
    candidate = _candidate(corporate_id=uuid4())
    erase = AsyncMock()
    purge = MagicMock()

    with (
        patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=candidate)),
        patch.object(CandidateService, "erase_candidate", new=erase),
        patch(
            "app.api.v1.notifications.storage_service.purge_candidate_report_files",
            new=purge,
        ),
    ):
        res = _app(corporate_id=caller_corp, role="hr").delete(
            f"/api/v1/admin/candidates/{candidate.id}"
        )

    assert res.status_code == 404
    assert res.json() == {"detail": "Candidate not found"}
    erase.assert_not_awaited()
    purge.assert_not_called()


def test_erase_allows_ops_cross_tenant_and_purges_storage(caplog):
    caller_corp = uuid4()
    admin_id = uuid4()
    candidate = _candidate(corporate_id=uuid4())
    erase = AsyncMock(return_value=(candidate.corporate_id, candidate.id))
    purge = MagicMock(return_value=3)

    with (
        patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=candidate)),
        patch.object(CandidateService, "erase_candidate", new=erase),
        patch(
            "app.api.v1.notifications.storage_service.purge_candidate_report_files",
            new=purge,
        ),
        caplog.at_level(logging.INFO),
    ):
        res = _app(corporate_id=caller_corp, role="admin", user_id=admin_id).delete(
            f"/api/v1/admin/candidates/{candidate.id}"
        )

    assert res.status_code == 204
    assert res.content == b""
    erase.assert_awaited_once()
    assert erase.await_args.kwargs["admin_user_id"] == admin_id
    purge.assert_called_once_with(candidate.corporate_id, candidate.id)
    assert candidate.full_name not in caplog.text
    assert candidate.email not in caplog.text


def test_erase_same_tenant_hr_succeeds():
    corp = uuid4()
    candidate = _candidate(corporate_id=corp)
    erase = AsyncMock(return_value=(corp, candidate.id))
    purge = MagicMock(return_value=1)

    with (
        patch.object(CandidateService, "get_candidate", new=AsyncMock(return_value=candidate)),
        patch.object(CandidateService, "erase_candidate", new=erase),
        patch(
            "app.api.v1.notifications.storage_service.purge_candidate_report_files",
            new=purge,
        ),
    ):
        res = _app(corporate_id=corp, role="hr").delete(
            f"/api/v1/admin/candidates/{candidate.id}"
        )

    assert res.status_code == 204
    erase.assert_awaited_once()
    purge.assert_called_once_with(corp, candidate.id)


@pytest.mark.asyncio
async def test_erase_candidate_scrubs_tickets_deletes_row_and_audits(caplog):
    admin_id = uuid4()
    candidate = _candidate(corporate_id=uuid4())
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    with caplog.at_level(logging.INFO, logger="app.audit"):
        corporate_id, candidate_id = await CandidateService.erase_candidate(
            session, candidate, admin_user_id=admin_id
        )

    assert corporate_id == candidate.corporate_id
    assert candidate_id == candidate.id
    assert session.execute.await_count == 2
    assert session.commit.await_count == 1

    ticket_stmt = session.execute.await_args_list[0].args[0]
    delete_stmt = session.execute.await_args_list[1].args[0]
    assert isinstance(ticket_stmt, Update)
    assert isinstance(delete_stmt, Delete)

    compiled_ticket = ticket_stmt.compile()
    assert compiled_ticket.params.get("details") == "[Candidate data erased]"
    assert compiled_ticket.params.get("candidate_id") is None

    assert "candidate_erased" in caplog.text
    erased = [r for r in caplog.records if r.getMessage() == "candidate_erased"]
    assert len(erased) == 1
    assert erased[0].admin_user_id == str(admin_id)
    assert erased[0].candidate_id == str(candidate.id)
    assert erased[0].corporate_id == str(candidate.corporate_id)
    assert not hasattr(erased[0], "email")
    assert candidate.full_name not in caplog.text
    assert candidate.email not in caplog.text


def test_purge_candidate_report_files_clears_cache_and_legacy(monkeypatch):
    corp = uuid4()
    cand = uuid4()
    client = MagicMock()
    client.list_objects_v2.return_value = {
        "Contents": [{"Key": f"{corp}/{cand}/abc.pdf"}]
    }
    monkeypatch.setattr(
        storage_service,
        "settings",
        SimpleNamespace(
            R2_REPORTS_BUCKET_NAME="mindq-reports-private",
            R2_BUCKET_NAME="logos",
            SUPABASE_LOGO_BUCKET="corporate-logos",
            r2_reports_configured=True,
            r2_public_base="https://cdn.example.com",
            supabase_logo_public_base="",
        ),
    )
    monkeypatch.setattr(storage_service, "_s3_client", lambda: client)
    monkeypatch.setattr(storage_service, "_reports_bucket_safe", lambda: True)

    deleted = storage_service.purge_candidate_report_files(corp, cand)

    assert deleted == 1 + 2  # one cached key + pdf/html legacy keys
    assert client.delete_objects.call_count == 2
    first_keys = {
        item["Key"] for item in client.delete_objects.call_args_list[0].kwargs["Delete"]["Objects"]
    }
    second_keys = {
        item["Key"] for item in client.delete_objects.call_args_list[1].kwargs["Delete"]["Objects"]
    }
    assert f"{corp}/{cand}/abc.pdf" in first_keys
    assert {f"{corp}/{cand}.pdf", f"{corp}/{cand}.html"} == second_keys


@pytest.mark.asyncio
async def test_technical_eval_log_omits_ai_prose(caplog, monkeypatch):
    candidate = SimpleNamespace(id=uuid4(), corporate_id=uuid4())
    assessment = SimpleNamespace(
        id=uuid4(),
        module_kind="technical",
        questions=[{"id": "q1", "type": "open", "prompt": "Explain CAP"}],
        global_module_id=None,
    )
    row = SimpleNamespace(
        question_id="q1",
        response={"answer": "Consistency, Availability, Partition tolerance"},
    )
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    evaluation = TechnicalItemEvaluation(
        score=88,
        feedback="Excellent discussion of partition trade-offs under latency.",
        scorecard=["Depth: strong"],
    )

    async def _fake_to_thread(fn, *args, **kwargs):
        return evaluation

    monkeypatch.setattr(
        "app.services.technical_eval.asyncio.to_thread", _fake_to_thread
    )
    monkeypatch.setattr(
        "app.services.technical_eval.settings.GEMINI_API_KEY", "test-key"
    )
    monkeypatch.setattr(
        "app.services.technical_eval.is_gradable_technical_assessment",
        lambda _a: True,
    )
    monkeypatch.setattr(
        "app.services.technical_eval.already_evaluated", lambda _r: False
    )
    monkeypatch.setattr(
        "app.services.technical_eval._persist_response", lambda *_a, **_k: None
    )

    with caplog.at_level(logging.INFO):
        stored = await TechnicalEvalService.evaluate_assessment(
            session, candidate=candidate, assessment=assessment
        )

    assert stored == 1
    assert "technical_eval_gemini_ok" in caplog.text
    assert "latency_ms=" in caplog.text
    assert "Excellent discussion" not in caplog.text
    assert "partition trade-offs" not in caplog.text
    assert "Consistency, Availability" not in caplog.text
    assert "Ada" not in caplog.text
