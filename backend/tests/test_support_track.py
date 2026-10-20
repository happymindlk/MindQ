"""Support ticket + public track API smoke tests (mocked DB not required for schemas)."""
from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_support_submit_requires_details(async_client: AsyncClient):
    res = await async_client.post("/api/v1/support/submit", json={"details": ""})
    assert res.status_code == 422


def _capturing_db(captured: list):
    """Fake DB session factory capturing SupportTicket rows instead of inserting."""

    class FakeSession:
        def add(self, ticket):
            captured.append(ticket)

        async def commit(self):
            return None

        async def refresh(self, ticket):
            from datetime import datetime, timezone

            if ticket.id is None:
                ticket.id = uuid4()
            if ticket.created_at is None:
                ticket.created_at = datetime.now(timezone.utc)

    async def fake_db():
        yield FakeSession()

    return fake_db


@pytest.mark.asyncio
async def test_support_submit_folds_package_code_into_details(async_client: AsyncClient):
    from app.database import get_db
    from app.main import app

    captured: list = []
    app.dependency_overrides[get_db] = _capturing_db(captured)
    try:
        res = await async_client.post(
            "/api/v1/support/submit",
            json={"details": "  Timer froze  ", "package_code": " HM-ABCDEF-1 "},
        )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert len(captured) == 1
    assert captured[0].details == "[Package: HM-ABCDEF-1] Timer froze"


@pytest.mark.asyncio
async def test_support_submit_without_package_code_leaves_details_unchanged(
    async_client: AsyncClient,
):
    from app.database import get_db
    from app.main import app

    captured: list = []
    app.dependency_overrides[get_db] = _capturing_db(captured)
    try:
        res = await async_client.post(
            "/api/v1/support/submit", json={"details": "Timer froze"}
        )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert len(captured) == 1
    assert captured[0].details == "Timer froze"


@pytest.mark.asyncio
async def test_public_track_rejects_short_secret(async_client: AsyncClient):
    res = await async_client.get("/api/v1/track/short")
    assert res.status_code == 404
    assert res.json()["detail"] == "Tracker not found"


@pytest.mark.asyncio
async def test_public_track_unknown_secret(async_client: AsyncClient, monkeypatch):
    from app.api.v1 import track as track_mod
    from types import SimpleNamespace

    class FakeResult:
        def scalars(self):
            return self

        def first(self):
            return None

    class FakeSession:
        async def execute(self, *_a, **_k):
            return FakeResult()

    async def fake_db():
        yield FakeSession()

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = fake_db
    try:
        res = await async_client.get(f"/api/v1/track/{uuid4().hex}{uuid4().hex[:16]}")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()
