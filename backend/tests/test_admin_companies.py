"""Ops company management: create, partial update, and R2 logo upload."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin_ops import router as admin_router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.models.corporate import Corporate
from app.services.storage import LOGO_MAX_BYTES

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _scalar(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _session(*execute_results: object) -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[_scalar(v) for v in execute_results])
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _corporate(**overrides: object) -> Corporate:
    corp = Corporate(
        id=uuid4(),
        name="Acme Corp",
        slug="acme-corp",
        contact_email="hr@acme.test",
        logo_url=None,
    )
    corp.created_at = datetime.now(timezone.utc)
    for key, value in overrides.items():
        setattr(corp, key, value)
    return corp


def _client(session: MagicMock, *, ops: bool = True) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router, prefix="/admin")

    async def _db():
        yield session

    application.dependency_overrides[get_db] = _db
    if ops:

        async def _ops():
            return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")

        application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application)


def _r2_settings(settings: MagicMock, *, configured: bool = True) -> None:
    settings.r2_configured = configured
    settings.r2_public_base = "https://cdn.example.com" if configured else ""


# --------------------------------------------------------------------------- create


def test_create_company_persists_normalized_contact_email():
    session = _session(None)

    async def _refresh(obj: Corporate) -> None:
        obj.id = uuid4()
        obj.created_at = datetime.now(timezone.utc)

    session.refresh.side_effect = _refresh

    res = _client(session).post(
        "/admin/companies",
        json={"name": "  Acme Corp ", "contact_email": " HR@Acme.Test "},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Acme Corp"
    assert body["slug"] == "acme-corp"
    assert body["contact_email"] == "hr@acme.test"
    assert body["logo_url"] is None
    added: Corporate = session.add.call_args.args[0]
    assert added.contact_email == "hr@acme.test"


def test_create_company_blank_email_is_stored_as_null():
    session = _session(None)

    async def _refresh(obj: Corporate) -> None:
        obj.id = uuid4()
        obj.created_at = datetime.now(timezone.utc)

    session.refresh.side_effect = _refresh

    res = _client(session).post("/admin/companies", json={"name": "Acme", "contact_email": ""})

    assert res.status_code == 200
    assert res.json()["contact_email"] is None


def test_create_company_rejects_invalid_email():
    session = _session()
    res = _client(session).post(
        "/admin/companies", json={"name": "Acme", "contact_email": "not-an-email"}
    )
    assert res.status_code == 422
    session.add.assert_not_called()


# --------------------------------------------------------------------------- update


def test_update_company_changes_name_and_email():
    corp = _corporate()
    session = _session(corp)

    res = _client(session).patch(
        f"/admin/companies/{corp.id}",
        json={"name": "Acme Global", "contact_email": "people@acme.test"},
    )

    assert res.status_code == 200
    assert res.json()["name"] == "Acme Global"
    assert res.json()["contact_email"] == "people@acme.test"
    session.commit.assert_awaited_once()


def test_update_company_partial_leaves_omitted_fields():
    corp = _corporate()
    session = _session(corp)

    res = _client(session).patch(f"/admin/companies/{corp.id}", json={"name": "Renamed"})

    assert res.status_code == 200
    assert corp.name == "Renamed"
    assert corp.contact_email == "hr@acme.test"


def test_update_company_explicit_blank_email_clears_it():
    corp = _corporate()
    session = _session(corp)

    res = _client(session).patch(f"/admin/companies/{corp.id}", json={"contact_email": ""})

    assert res.status_code == 200
    assert corp.contact_email is None


def test_update_company_missing_returns_404():
    session = _session(None)
    res = _client(session).patch(f"/admin/companies/{uuid4()}", json={"name": "X"})
    assert res.status_code == 404
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [{"contact_email": "nope"}, {"name": "   "}, {"name": None}, {"name": "x" * 256}],
)
def test_update_company_rejects_invalid_payload(payload: dict):
    session = _session()
    res = _client(session).patch(f"/admin/companies/{uuid4()}", json=payload)
    assert res.status_code == 422
    session.execute.assert_not_called()


# --------------------------------------------------------------------------- logo


def test_logo_upload_stores_on_r2_and_persists_url():
    corp = _corporate()
    session = _session(corp.id, corp)
    public = f"https://cdn.example.com/logos/{corp.id}/logo-1.png"

    with (
        patch("app.api.v1.admin_ops.settings") as settings,
        patch("app.api.v1.admin_ops.upload_logo", return_value=public) as upload,
    ):
        _r2_settings(settings)
        res = _client(session).post(
            f"/admin/companies/{corp.id}/logo",
            files={"file": ("My Logo!.png", PNG, "image/png")},
        )

    assert res.status_code == 200
    assert res.json() == {"logo_url": public}
    assert corp.logo_url == public
    session.commit.assert_awaited_once()
    company_id, filename, raw, content_type = upload.call_args.args
    assert company_id == corp.id
    assert filename.startswith("My-Logo") and filename.endswith(".png")
    assert raw == PNG
    assert content_type == "image/png"


def test_logo_upload_unknown_company_returns_404_without_uploading():
    session = _session(None)
    with (
        patch("app.api.v1.admin_ops.settings") as settings,
        patch("app.api.v1.admin_ops.upload_logo") as upload,
    ):
        _r2_settings(settings)
        res = _client(session).post(
            f"/admin/companies/{uuid4()}/logo",
            files={"file": ("logo.png", PNG, "image/png")},
        )
    assert res.status_code == 404
    upload.assert_not_called()


@pytest.mark.parametrize(
    ("filename", "size", "content_type", "detail_fragment"),
    [
        ("notes.txt", 5, "text/plain", "Unsupported image type"),
        ("logo.png", 0, "image/png", "Empty file"),
        ("logo.png", LOGO_MAX_BYTES + 1, "image/png", "2 MB"),
    ],
    ids=["bad-mime", "empty", "oversized"],
)
def test_logo_upload_rejects_invalid_files(
    filename: str, size: int, content_type: str, detail_fragment: str
):
    content = b"\x00" * size
    corp_id = uuid4()
    session = _session(corp_id)
    with (
        patch("app.api.v1.admin_ops.settings") as settings,
        patch("app.api.v1.admin_ops.upload_logo") as upload,
    ):
        _r2_settings(settings)
        res = _client(session).post(
            f"/admin/companies/{corp_id}/logo",
            files={"file": (filename, content, content_type)},
        )
    assert res.status_code == 400
    assert detail_fragment in res.json()["detail"]
    upload.assert_not_called()
    session.commit.assert_not_called()


def test_logo_upload_returns_503_when_r2_unconfigured():
    corp_id = uuid4()
    session = _session(corp_id)
    with (
        patch("app.api.v1.admin_ops.settings") as settings,
        patch("app.api.v1.admin_ops.upload_logo") as upload,
    ):
        _r2_settings(settings, configured=False)
        res = _client(session).post(
            f"/admin/companies/{corp_id}/logo",
            files={"file": ("logo.png", PNG, "image/png")},
        )
    assert res.status_code == 503
    upload.assert_not_called()


def test_logo_upload_returns_502_when_storage_fails():
    corp_id = uuid4()
    session = _session(corp_id)
    with (
        patch("app.api.v1.admin_ops.settings") as settings,
        patch("app.api.v1.admin_ops.upload_logo", return_value=None),
    ):
        _r2_settings(settings)
        res = _client(session).post(
            f"/admin/companies/{corp_id}/logo",
            files={"file": ("logo.png", PNG, "image/png")},
        )
    assert res.status_code == 502
    session.commit.assert_not_called()


# --------------------------------------------------------------------------- auth


@pytest.mark.parametrize(
    ("method", "path_suffix", "kwargs"),
    [
        ("patch", "", {"json": {"name": "X"}}),
        ("post", "/logo", {"files": {"file": ("logo.png", PNG, "image/png")}}),
    ],
    ids=["update", "logo"],
)
def test_non_ops_caller_is_forbidden(method: str, path_suffix: str, kwargs: dict):
    session = _session()
    hr_user = HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="hr")
    with patch("app.auth.get_current_hr_user", AsyncMock(return_value=hr_user)):
        client = _client(session, ops=False)
        res = getattr(client, method)(
            f"/admin/companies/{uuid4()}{path_suffix}",
            headers={"Authorization": "Bearer test"},
            **kwargs,
        )
    assert res.status_code == 403
    session.execute.assert_not_called()


def test_list_item_schema_exposes_logo_url():
    from app.schemas.client_package import CorporateListItem

    row = SimpleNamespace(id=uuid4(), name="Acme", slug="acme", logo_url="https://x/y.png")
    item = CorporateListItem(id=row.id, name=row.name, slug=row.slug, logo_url=row.logo_url)
    assert item.logo_url == "https://x/y.png"


def _list_client(rows: list[tuple[Corporate, int, int]]) -> TestClient:
    from app.api.v1.packages import router as packages_router

    result = MagicMock()
    result.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    application = FastAPI()
    application.include_router(packages_router, prefix="/packages")

    async def _db():
        yield session

    async def _ops():
        return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application)


def test_list_corporates_exposes_created_at_and_counts():
    created = datetime(2026, 3, 14, 9, 30, tzinfo=timezone.utc)
    corp = _corporate(created_at=created)

    res = _list_client([(corp, 2, 7)]).get("/packages/corporates")

    assert res.status_code == 200
    [row] = res.json()
    assert row["id"] == str(corp.id)
    assert row["package_count"] == 2
    assert row["candidate_count"] == 7
    assert datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) == created


def test_list_corporates_null_counts_and_missing_created_at_default_safely():
    corp = _corporate(created_at=None)

    res = _list_client([(corp, None, None)]).get("/packages/corporates")

    assert res.status_code == 200
    [row] = res.json()
    assert row["package_count"] == 0
    assert row["candidate_count"] == 0
    assert row["created_at"] is None
