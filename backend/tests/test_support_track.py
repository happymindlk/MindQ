"""Support ticket + public track API smoke tests (mocked DB not required for schemas)."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_support_submit_requires_details(async_client: AsyncClient):
    res = await async_client.post(
        "/api/v1/support/submit",
        json={
            "email": "you@example.com",
            "contact_number": "+94 77 123 4567",
            "details": "",
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_support_submit_requires_email_and_contact(async_client: AsyncClient):
    res = await async_client.post(
        "/api/v1/support/submit",
        json={"details": "Timer froze"},
    )
    assert res.status_code == 422


def _capturing_db(captured: list, *, candidates: list | None = None, packages: list | None = None):
    """Fake DB session factory capturing SupportTicket rows instead of inserting."""

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def first(self):
            return self._rows[0] if self._rows else None

    def _table_name(stmt) -> str:
        try:
            froms = list(stmt.get_final_froms())
            if froms:
                return getattr(froms[0], "name", "") or str(froms[0]).lower()
        except Exception:  # noqa: BLE001 — best-effort for unit fakes
            pass
        return str(stmt).lower()

    class FakeSession:
        def add(self, ticket):
            captured.append(ticket)

        async def commit(self):
            return None

        async def refresh(self, ticket):
            if ticket.id is None:
                ticket.id = uuid4()
            if ticket.created_at is None:
                ticket.created_at = datetime.now(timezone.utc)

        async def execute(self, stmt):
            name = _table_name(stmt)
            if "package" in name:
                return FakeResult(packages or [])
            if "candidate" in name:
                return FakeResult(candidates or [])
            return FakeResult([])

    async def fake_db():
        yield FakeSession()

    return fake_db


@pytest.mark.asyncio
async def test_support_submit_folds_package_code_into_details(async_client: AsyncClient, monkeypatch):
    from app.database import get_db
    from app.main import app

    captured: list = []
    app.dependency_overrides[get_db] = _capturing_db(captured)
    monkeypatch.setattr(
        "app.api.v1.support.send_transactional_email",
        lambda *a, **k: {"id": "msg-1"},
    )
    try:
        res = await async_client.post(
            "/api/v1/support/submit",
            json={
                "email": "you@example.com",
                "contact_number": "+94 77 123 4567",
                "details": "  Timer froze  ",
                "package_code": " HM-ABCDEF-1 ",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert len(captured) == 1
    assert captured[0].details == "[Package: HM-ABCDEF-1] Timer froze"
    assert captured[0].description == "Timer froze"
    assert captured[0].submitter_email == "you@example.com"
    assert captured[0].contact_number == "+94 77 123 4567"
    assert captured[0].access_code_entered == "HM-ABCDEF-1"
    assert captured[0].status == "OPEN"


@pytest.mark.asyncio
async def test_support_submit_without_package_code_leaves_details_unchanged(
    async_client: AsyncClient, monkeypatch
):
    from app.database import get_db
    from app.main import app

    captured: list = []
    app.dependency_overrides[get_db] = _capturing_db(captured)
    monkeypatch.setattr(
        "app.api.v1.support.send_transactional_email",
        lambda *a, **k: {"id": "msg-1"},
    )
    try:
        res = await async_client.post(
            "/api/v1/support/submit",
            json={
                "email": "you@example.com",
                "contact_number": "+94771234567",
                "details": "Timer froze",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert len(captured) == 1
    assert captured[0].details == "Timer froze"
    assert captured[0].description == "Timer froze"


@pytest.mark.asyncio
async def test_support_submit_autolinks_candidate_by_access_code_and_email(
    async_client: AsyncClient, monkeypatch
):
    from app.database import get_db
    from app.main import app

    corp_id = uuid4()
    cand_id = uuid4()
    pkg_id = uuid4()
    package = SimpleNamespace(id=pkg_id, corporate_id=corp_id, access_code="HM-ABCDEF-1")
    candidate = SimpleNamespace(
        id=cand_id,
        corporate_id=corp_id,
        package_id=pkg_id,
        email="you@example.com",
        access_code="HM-CAND-1",
        deleted_at=None,
        logged_in_at=None,
    )
    captured: list = []
    app.dependency_overrides[get_db] = _capturing_db(
        captured, candidates=[candidate], packages=[package]
    )
    monkeypatch.setattr(
        "app.api.v1.support.send_transactional_email",
        lambda *a, **k: {"id": "msg-1"},
    )
    try:
        res = await async_client.post(
            "/api/v1/support/submit",
            json={
                "email": "you@example.com",
                "contact_number": "+94 77 123 4567",
                "description": "Cannot start",
                "access_code": "HM-ABCDEF-1",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert captured[0].candidate_id == cand_id
    assert captured[0].corporate_id == corp_id


@pytest.mark.asyncio
async def test_support_submit_queues_ses_with_reply_to(
    async_client: AsyncClient, monkeypatch
):
    from app.database import get_db
    from app.main import app

    captured: list = []
    sent: dict = {}

    def fake_send(to_email, subject, html_content, *, reply_to=None, raise_on_error=False):
        sent["to"] = to_email
        sent["subject"] = subject
        sent["reply_to"] = reply_to
        sent["html"] = html_content
        return {"id": "ses-1"}

    app.dependency_overrides[get_db] = _capturing_db(captured)
    monkeypatch.setattr("app.api.v1.support.send_transactional_email", fake_send)
    monkeypatch.setattr("app.api.v1.support.settings.SUPPORT_EMAIL", "support@mindqtalent.com")
    try:
        res = await async_client.post(
            "/api/v1/support/submit",
            json={
                "email": "candidate@example.com",
                "contact_number": "+94 77 123 4567",
                "details": "Blank screen",
                "device_id": "dev-1",
                "browser": "Mozilla/5.0",
                "page_url": "https://mindq.pages.dev/portal",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    # BackgroundTasks run eagerly in TestClient / httpx ASGITransport for this app.
    assert sent.get("to") == "support@mindqtalent.com"
    assert sent.get("reply_to") == "candidate@example.com"
    assert "Blank screen" in sent.get("html", "")
    assert captured[0].device_id == "dev-1"


@pytest.mark.asyncio
async def test_public_track_rejects_short_secret(async_client: AsyncClient):
    res = await async_client.get("/api/v1/track/short")
    assert res.status_code == 404
    assert res.json()["detail"] == "Tracker not found"


@pytest.mark.asyncio
async def test_public_track_unknown_secret(async_client: AsyncClient, monkeypatch):
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
