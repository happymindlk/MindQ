"""Support ticket + public track API smoke tests (mocked DB not required for schemas)."""
from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_support_submit_requires_details(async_client: AsyncClient):
    res = await async_client.post("/api/v1/support/submit", json={"details": ""})
    assert res.status_code == 422


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
