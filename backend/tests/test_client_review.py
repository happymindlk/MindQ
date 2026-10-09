"""HTTP tests for the public blind-review GET and approve POST."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.client import router as client_router
from app.api.v1.packages import router as packages_router
from app.database import get_db
from app.schemas.client_package import BlindReviewResponse, ReviewQuestion


def test_blind_review_omits_psychometric_and_is_public():
    application = FastAPI()
    application.include_router(packages_router, prefix="/packages")

    async def _db():
        yield AsyncMock()

    application.dependency_overrides[get_db] = _db
    client = TestClient(application)
    payload = BlindReviewResponse(
        package_id=uuid4(),
        title="Junior Data Analyst",
        corporate_name="Acme",
        status="published",
        client_approved=False,
        questions=[
            ReviewQuestion(
                id="t1",
                prompt="Write a GROUP BY query",
                question_type="open_ended",
                options=[],
            )
        ],
    )

    async def _review(_session, token: str):
        assert token == "tok_abc"
        return payload

    with patch("app.api.v1.packages.ClientPackageService.get_blind_review", new=_review):
        res = client.get("/packages/review/tok_abc")

    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Junior Data Analyst"
    assert body["client_approved"] is False
    assert len(body["questions"]) == 1
    assert "psychometric" not in body["questions"][0]["prompt"].lower()
    assert "correct_answer" not in body["questions"][0]
    assert "weight" not in body["questions"][0]


def test_blind_review_unknown_token_404():
    application = FastAPI()
    application.include_router(packages_router, prefix="/packages")

    async def _db():
        yield AsyncMock()

    application.dependency_overrides[get_db] = _db

    async def _review(_session, _token: str):
        raise LookupError("Review link is invalid or expired")

    with patch("app.api.v1.packages.ClientPackageService.get_blind_review", new=_review):
        res = TestClient(application).get("/packages/review/missing")

    assert res.status_code == 404


def test_approve_blind_review_success():
    application = FastAPI()
    application.include_router(client_router, prefix="/client")

    async def _db():
        yield AsyncMock()

    application.dependency_overrides[get_db] = _db

    async def _approve(_session, token: str):
        assert token == "tok_abc"
        return {"success": True, "message": "Assessment approved successfully"}

    with patch(
        "app.api.v1.client.ClientPackageService.approve_blind_review", new=_approve
    ):
        res = TestClient(application).post("/client/review/tok_abc/approve")

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["message"] == "Assessment approved successfully"


def test_approve_blind_review_idempotent():
    application = FastAPI()
    application.include_router(client_router, prefix="/client")

    async def _db():
        yield AsyncMock()

    application.dependency_overrides[get_db] = _db
    calls = {"n": 0}

    async def _approve(_session, _token: str):
        calls["n"] += 1
        return {"success": True, "message": "Assessment approved successfully"}

    with patch(
        "app.api.v1.client.ClientPackageService.approve_blind_review", new=_approve
    ):
        client = TestClient(application)
        first = client.post("/client/review/tok_abc/approve")
        second = client.post("/client/review/tok_abc/approve")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["success"] is True
    assert second.json()["success"] is True
    assert calls["n"] == 2


def test_approve_blind_review_unknown_or_draft_404():
    application = FastAPI()
    application.include_router(client_router, prefix="/client")

    async def _db():
        yield AsyncMock()

    application.dependency_overrides[get_db] = _db

    async def _approve(_session, _token: str):
        raise LookupError("Review link is invalid or expired")

    with patch(
        "app.api.v1.client.ClientPackageService.approve_blind_review", new=_approve
    ):
        res = TestClient(application).post("/client/review/draft_or_missing/approve")

    assert res.status_code == 404


def test_blind_review_includes_approval_flags_when_set():
    application = FastAPI()
    application.include_router(packages_router, prefix="/packages")

    async def _db():
        yield AsyncMock()

    application.dependency_overrides[get_db] = _db
    reviewed = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    payload = BlindReviewResponse(
        package_id=uuid4(),
        title="Approved Pack",
        corporate_name="Acme",
        status="published",
        client_approved=True,
        reviewed_at=reviewed,
        questions=[],
    )

    async def _review(_session, _token: str):
        return payload

    with patch("app.api.v1.packages.ClientPackageService.get_blind_review", new=_review):
        res = TestClient(application).get("/packages/review/tok_ok")

    assert res.status_code == 200
    body = res.json()
    assert body["client_approved"] is True
    assert body["reviewed_at"] is not None
