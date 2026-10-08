"""Corporate package history list and the share-package email workflow."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.packages import router as packages_router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.models.corporate import Corporate
from app.models.package import Package
from app.services.email import render_package_share_html

ORIGIN = "https://app.assesspulse.test"
SEND = "app.services.package_share.send_transactional_email_async"


@pytest.fixture(autouse=True)
def _origin():
    with patch("app.services.email.frontend_origin", return_value=ORIGIN):
        yield


def _corporate(**overrides: object) -> Corporate:
    corp = Corporate(id=uuid4(), name="Acme Corp", slug="acme", contact_email="hr@acme.test")
    for key, value in overrides.items():
        setattr(corp, key, value)
    return corp


def _package(corporate: Corporate, **overrides: object) -> Package:
    pkg = Package(
        id=uuid4(),
        corporate_id=corporate.id,
        title="Data Analyst",
        access_code="HM-ABC123-1",
        status="published",
        is_active=True,
        allow_open_enrollment=False,
    )
    pkg.created_at = datetime.now(timezone.utc)
    for key, value in overrides.items():
        setattr(pkg, key, value)
    return pkg


def _session_for_share(row: tuple | None) -> MagicMock:
    result = MagicMock()
    result.first.return_value = row
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


def _client(session: MagicMock, *, ops: bool = True) -> TestClient:
    application = FastAPI()
    application.include_router(packages_router, prefix="/packages")

    async def _db():
        yield session

    application.dependency_overrides[get_db] = _db
    if ops:

        async def _ops():
            return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")

        application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application)


# --------------------------------------------------------------------------- share


def test_share_falls_back_to_corporate_contact_email_and_opens_enrollment():
    corp = _corporate()
    pkg = _package(corp)
    session = _session_for_share((pkg, corp))

    with patch(SEND, new_callable=AsyncMock, return_value={"id": "msg_1"}) as send:
        res = _client(session).post(f"/packages/{pkg.id}/share", json={})

    assert res.status_code == 200
    assert res.json() == {
        "success": True,
        "sent_to": "hr@acme.test",
        "candidate_link": f"{ORIGIN}/portal?code=HM-ABC123-1",
        "access_code": "HM-ABC123-1",
        "hr_login_link": f"{ORIGIN}/client/login",
    }
    to_email, subject, html_content = send.await_args.args
    assert to_email == "hr@acme.test"
    assert "Data Analyst" in subject
    assert "HM-ABC123-1" in html_content
    assert send.await_args.kwargs == {"raise_on_error": True}
    assert pkg.allow_open_enrollment is True
    session.commit.assert_awaited_once()


def test_share_without_body_uses_fallback():
    corp = _corporate()
    pkg = _package(corp)
    session = _session_for_share((pkg, corp))

    with patch(SEND, new_callable=AsyncMock, return_value={"id": "m"}):
        res = _client(session).post(f"/packages/{pkg.id}/share")

    assert res.status_code == 200
    assert res.json()["sent_to"] == "hr@acme.test"


def test_share_explicit_recipient_overrides_contact_email():
    corp = _corporate()
    pkg = _package(corp)
    session = _session_for_share((pkg, corp))

    with patch(SEND, new_callable=AsyncMock, return_value={"id": "m"}) as send:
        res = _client(session).post(
            f"/packages/{pkg.id}/share", json={"recipient_email": " Talent@Acme.Test "}
        )

    assert res.status_code == 200
    assert res.json()["sent_to"] == "talent@acme.test"
    assert send.await_args.args[0] == "talent@acme.test"


def test_share_already_open_package_does_not_commit_again():
    corp = _corporate()
    pkg = _package(corp, allow_open_enrollment=True)
    session = _session_for_share((pkg, corp))

    with patch(SEND, new_callable=AsyncMock, return_value={"id": "m"}):
        res = _client(session).post(f"/packages/{pkg.id}/share", json={})

    assert res.status_code == 200
    session.commit.assert_not_called()


def test_share_unknown_package_returns_404():
    session = _session_for_share(None)
    with patch(SEND, new_callable=AsyncMock) as send:
        res = _client(session).post(f"/packages/{uuid4()}/share", json={})
    assert res.status_code == 404
    send.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [{"status": "draft"}, {"status": "published", "is_active": False}],
    ids=["draft", "archived"],
)
def test_share_unpublished_package_returns_409(overrides: dict):
    corp = _corporate()
    pkg = _package(corp, **overrides)
    session = _session_for_share((pkg, corp))

    with patch(SEND, new_callable=AsyncMock) as send:
        res = _client(session).post(f"/packages/{pkg.id}/share", json={})

    assert res.status_code == 409
    send.assert_not_called()
    assert pkg.allow_open_enrollment is False


@pytest.mark.parametrize("contact_email", [None, "", "   "])
def test_share_without_any_recipient_returns_422(contact_email: str | None):
    corp = _corporate(contact_email=contact_email)
    pkg = _package(corp)
    session = _session_for_share((pkg, corp))

    with patch(SEND, new_callable=AsyncMock) as send:
        res = _client(session).post(f"/packages/{pkg.id}/share", json={"recipient_email": ""})

    assert res.status_code == 422
    assert "HR contact email" in res.json()["detail"]
    send.assert_not_called()


def test_share_rejects_malformed_recipient():
    session = _session_for_share(None)
    res = _client(session).post(
        f"/packages/{uuid4()}/share", json={"recipient_email": "not-an-email"}
    )
    assert res.status_code == 422
    session.execute.assert_not_called()


def test_share_delivery_failure_returns_502_and_keeps_enrollment_closed():
    corp = _corporate()
    pkg = _package(corp)
    session = _session_for_share((pkg, corp))

    with patch(
        SEND,
        new_callable=AsyncMock,
        side_effect=RuntimeError("Resend rejected the email: domain not verified"),
    ):
        res = _client(session).post(f"/packages/{pkg.id}/share", json={})

    assert res.status_code == 502
    assert "domain not verified" in res.json()["detail"]
    assert pkg.allow_open_enrollment is False
    session.commit.assert_not_called()


def test_share_resend_unconfigured_returns_502():
    corp = _corporate()
    pkg = _package(corp)
    session = _session_for_share((pkg, corp))

    with patch(
        SEND,
        new_callable=AsyncMock,
        side_effect=RuntimeError("Resend is not configured (RESEND_API_KEY missing)"),
    ):
        res = _client(session).post(f"/packages/{pkg.id}/share", json={})

    assert res.status_code == 502
    session.commit.assert_not_called()


# --------------------------------------------------------------------------- email html


def test_share_html_contains_both_sections_and_escapes_values():
    html_content = render_package_share_html(
        corporate_name="<script>alert(1)</script> & Co",
        package_title="Analyst <b>II</b>",
        access_code="HM-ABC123-1",
    )
    assert "CANDIDATE ACCESS" in html_content
    assert "HR PORTAL ACCESS" in html_content
    assert f"{ORIGIN}/portal?code=HM-ABC123-1" in html_content
    assert f"{ORIGIN}/client/login" in html_content
    assert "HM-ABC123-1" in html_content
    assert "<script>" not in html_content
    assert "&lt;script&gt;" in html_content
    assert "&amp; Co" in html_content
    assert "<b>II</b>" not in html_content


# --------------------------------------------------------------------------- list


def _list_session(corporate_exists: bool, rows: list[tuple]) -> MagicMock:
    exists_result = MagicMock()
    exists_result.scalar_one_or_none.return_value = uuid4() if corporate_exists else None
    rows_result = MagicMock()
    rows_result.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[exists_result, rows_result])
    return session


def test_list_packages_maps_status_counts_and_links():
    corp = _corporate()
    published = _package(corp, title="Published")
    draft = _package(corp, title="Draft", status="draft", access_code="HM-DRAFT-1")
    archived = _package(corp, title="Old", is_active=False, access_code="HM-OLD-1")
    session = _list_session(True, [(published, 5, 2), (draft, 0, 0), (archived, 3, None)])

    res = _client(session).get("/packages", params={"corporate_id": str(corp.id)})

    assert res.status_code == 200
    by_title = {item["title"]: item for item in res.json()}
    assert by_title["Published"]["status"] == "published"
    assert by_title["Published"]["invited_count"] == 5
    assert by_title["Published"]["completed_count"] == 2
    assert by_title["Published"]["candidate_link"] == f"{ORIGIN}/portal?code=HM-ABC123-1"
    assert by_title["Published"]["hr_login_link"] == f"{ORIGIN}/client/login"
    assert by_title["Draft"]["status"] == "draft"
    assert by_title["Draft"]["candidate_link"] is None
    assert by_title["Old"]["status"] == "archived"
    assert by_title["Old"]["completed_count"] == 0
    assert by_title["Old"]["hr_login_link"] is None


def test_list_packages_unknown_corporate_returns_404():
    session = _list_session(False, [])
    res = _client(session).get("/packages", params={"corporate_id": str(uuid4())})
    assert res.status_code == 404


def test_list_packages_requires_corporate_id():
    session = _list_session(True, [])
    res = _client(session).get("/packages")
    assert res.status_code == 422


# --------------------------------------------------------------------------- auth


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/packages", {"params": {"corporate_id": str(uuid4())}}),
        ("post", f"/packages/{uuid4()}/share", {"json": {}}),
    ],
    ids=["list", "share"],
)
def test_non_ops_caller_is_forbidden(method: str, path: str, kwargs: dict):
    session = _session_for_share(None)
    hr_user = HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="hr")
    with patch("app.auth.get_current_hr_user", AsyncMock(return_value=hr_user)):
        res = getattr(_client(session, ops=False), method)(
            path, headers={"Authorization": "Bearer test"}, **kwargs
        )
    assert res.status_code == 403
    session.execute.assert_not_called()
