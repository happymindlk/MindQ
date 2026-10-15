"""HR client portal: token isolation, OTP session exchange, tenant-scoped dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.client import router as client_router
from app.auth import (
    CLIENT_AUDIENCE,
    CLIENT_ROLE,
    ClientUserContext,
    SupabaseUserContext,
    get_current_client_user,
    get_current_hr_user,
    get_current_ops_user,
    get_current_supabase_user,
    issue_client_token,
)
from app.config import settings
from app.database import get_db
from app.schemas.client_package import ClientCorporate, ClientDashboardResponse
from app.services.client_package import ClientPackageService, client_status


def _bearer(token: str) -> str:
    return f"Bearer {token}"


def _client_payload(**overrides: object) -> dict:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": str(uuid4()),
        "corporate_id": str(uuid4()),
        "email": "hr@acme.test",
        "role": CLIENT_ROLE,
        "typ": "client",
        "aud": CLIENT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    payload.update(overrides)
    return payload


def _supabase_token(corporate_id: UUID, role: str = "hr") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "email": "hr@acme.test",
            "app_metadata": {"corporate_id": str(corporate_id), "corporate_role": role},
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )


def _result(scalar: object = None, rows: list | None = None, scalars: list | None = None):
    res = MagicMock()
    res.scalar_one_or_none.return_value = scalar
    res.all.return_value = rows or []
    res.scalars.return_value.all.return_value = scalars or []
    return res


# ---------------------------------------------------------------------------
# Token issue / verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_token_round_trip():
    user_id, corp_id = uuid4(), uuid4()
    token, expires_in = issue_client_token(user_id, corp_id, "hr@acme.test")

    ctx = await get_current_client_user(authorization=_bearer(token))

    assert ctx.user_id == user_id
    assert ctx.corporate_id == corp_id
    assert ctx.role == CLIENT_ROLE
    assert expires_in == settings.CLIENT_TOKEN_TTL_MINUTES * 60


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        {"aud": "happy-mind-candidate"},
        {"role": "admin"},
        {"typ": "candidate"},
        {"corporate_id": "not-a-uuid"},
    ],
    ids=["expired", "wrong-audience", "wrong-role", "wrong-typ", "bad-corporate"],
)
@pytest.mark.asyncio
async def test_client_token_rejections(overrides: dict):
    token = jwt.encode(_client_payload(**overrides), settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        await get_current_client_user(authorization=_bearer(token))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_client_token_signed_with_other_secret_rejected():
    token = jwt.encode(_client_payload(), "attacker-secret-key-32-bytes-long!!", algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        await get_current_client_user(authorization=_bearer(token))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_bearer_rejected():
    with pytest.raises(HTTPException) as exc:
        await get_current_client_user(authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_supabase_ops_token_rejected_by_client_dependency():
    token = _supabase_token(uuid4(), role="admin")
    with pytest.raises(HTTPException) as exc:
        await get_current_client_user(authorization=_bearer(token))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_client_token_rejected_by_ops_and_hr_dependencies():
    token, _ = issue_client_token(uuid4(), uuid4(), "hr@acme.test")
    for dependency in (get_current_hr_user, get_current_ops_user):
        with pytest.raises(HTTPException) as exc:
            await dependency(authorization=_bearer(token))
        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Session exchange
# ---------------------------------------------------------------------------


def _session_app(db_session: AsyncMock) -> TestClient:
    application = FastAPI()
    application.include_router(client_router, prefix="/client")

    async def _db():
        yield db_session

    async def _supabase_user():
        return SupabaseUserContext(user_id=uuid4(), email="hr@acme.test")

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_supabase_user] = _supabase_user
    return TestClient(application)


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.api.v1.client.enforce_rate_limit"):
        yield


def test_session_exchange_without_membership_is_403():
    db = AsyncMock()
    db.execute.return_value = _result(scalar=None)

    res = _session_app(db).post("/client/auth/session")

    assert res.status_code == 403
    assert "not registered" in res.json()["detail"]


def test_session_exchange_rejects_ops_role():
    db = AsyncMock()
    db.execute.return_value = _result(
        scalar=SimpleNamespace(corporate_id=uuid4(), role="admin")
    )

    res = _session_app(db).post("/client/auth/session")

    assert res.status_code == 403
    assert "admin portal" in res.json()["detail"]


@pytest.mark.asyncio
async def test_session_exchange_issues_tenant_locked_client_token():
    corp_id = uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        _result(scalar=SimpleNamespace(corporate_id=corp_id, role="hr")),
        _result(
            scalar=SimpleNamespace(id=corp_id, name="Acme", logo_url="https://cdn/logo.png")
        ),
    ]

    res = _session_app(db).post("/client/auth/session")

    assert res.status_code == 200
    body = res.json()
    assert body["corporate"] == {
        "id": str(corp_id),
        "name": "Acme",
        "logo_url": "https://cdn/logo.png",
    }
    ctx = await get_current_client_user(authorization=_bearer(body["access_token"]))
    assert ctx.corporate_id == corp_id


# ---------------------------------------------------------------------------
# Dashboard + report routes
# ---------------------------------------------------------------------------


def _client_app(corporate_id: UUID, db_session: AsyncMock | None = None) -> TestClient:
    application = FastAPI()
    application.include_router(client_router, prefix="/client")

    async def _db():
        yield db_session or AsyncMock()

    async def _client_user():
        return ClientUserContext(user_id=uuid4(), corporate_id=corporate_id)

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_client_user] = _client_user
    return TestClient(application)


def test_dashboard_uses_token_corporate_id():
    corp_id = uuid4()
    seen: dict = {}

    async def _dashboard(_session, corporate_id):
        seen["corporate_id"] = corporate_id
        return ClientDashboardResponse(
            corporate=ClientCorporate(id=corporate_id, name="Acme"), packages=[]
        )

    with patch(
        "app.api.v1.client.ClientPackageService.get_client_dashboard", new=_dashboard
    ):
        res = _client_app(corp_id).get("/client/dashboard")

    assert res.status_code == 200
    assert seen["corporate_id"] == corp_id
    assert res.json()["packages"] == []


def test_dashboard_requires_client_token():
    application = FastAPI()
    application.include_router(client_router, prefix="/client")
    res = TestClient(application).get(
        "/client/dashboard",
        headers={"Authorization": _bearer(_supabase_token(uuid4()))},
    )
    assert res.status_code == 401


def test_cross_tenant_report_data_is_404():
    db = AsyncMock()
    db.execute.return_value = _result(scalar=None)
    build = AsyncMock()

    with patch("app.api.v1.client.build_technical_report_data", new=build):
        res = _client_app(uuid4(), db).get(f"/client/candidates/{uuid4()}/report-data")

    assert res.status_code == 404
    build.assert_not_awaited()
    stmt = str(db.execute.await_args.args[0])
    assert "candidates.corporate_id" in stmt


# ---------------------------------------------------------------------------
# Status mapping + service aggregation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("completed", "total", "logged_in", "expected"),
    [
        (0, 3, False, "invited"),
        (0, 3, True, "in_progress"),
        (1, 3, False, "in_progress"),
        (3, 3, False, "completed"),
        (4, 3, True, "completed"),
        (0, 0, False, "invited"),
        (0, 0, True, "in_progress"),
    ],
)
def test_client_status_mapping(completed, total, logged_in, expected):
    assert client_status(completed=completed, total=total, logged_in=logged_in) == expected


@pytest.mark.asyncio
async def test_get_client_dashboard_groups_and_scopes_by_tenant():
    corp_id = uuid4()
    pkg_full, pkg_empty = uuid4(), uuid4()
    cand_done, cand_new = uuid4(), uuid4()

    corporate = SimpleNamespace(id=corp_id, name="Acme", logo_url=None)
    packages = [
        SimpleNamespace(
            id=pkg_full, title="Backend", access_code="ABC123", target_role="Engineer"
        ),
        SimpleNamespace(id=pkg_empty, title="Design", access_code="XYZ789", target_role=None),
    ]
    candidates = [
        SimpleNamespace(
            id=cand_done, package_id=pkg_full, full_name="Ada", email="ada@x.test",
            logged_in_at=datetime.now(timezone.utc),
        ),
        SimpleNamespace(
            id=cand_new, package_id=pkg_full, full_name="Bob", email="bob@x.test",
            logged_in_at=None,
        ),
    ]

    db = AsyncMock()
    db.execute.side_effect = [
        _result(scalar=corporate),
        _result(scalars=packages),
        _result(scalars=candidates),
        _result(rows=[(pkg_full, 2)]),
        _result(rows=[(cand_done, 2)]),
        _result(rows=[(cand_done, 82.5)]),
        _result(rows=[(cand_done, datetime.now(timezone.utc))]),
        _result(scalars=[]),
    ]

    out = await ClientPackageService.get_client_dashboard(db, corp_id)

    statements = [str(call.args[0]) for call in db.execute.await_args_list]
    assert "packages.corporate_id" in statements[1]
    assert "packages.status" in statements[1]
    assert "candidates.corporate_id" in statements[2]

    by_id = {p.id: p for p in out.packages}
    full = by_id[pkg_full]
    assert full.total_invited == 2
    assert full.total_completed == 1
    assert full.candidate_path == "/portal?code=ABC123"
    rows = {c.candidate_id: c for c in full.candidates}
    assert rows[cand_done].status == "completed"
    assert rows[cand_done].raw_score == 82.5
    assert rows[cand_done].report_path == f"/client/candidates/{cand_done}"
    assert rows[cand_new].status == "invited"
    assert rows[cand_new].report_available is False

    empty = by_id[pkg_empty]
    assert empty.total_invited == 0
    assert empty.candidates == []


@pytest.mark.asyncio
async def test_get_client_dashboard_without_packages_skips_candidate_queries():
    corp_id = uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        _result(scalar=SimpleNamespace(id=corp_id, name="Acme", logo_url=None)),
        _result(scalars=[]),
    ]

    out = await ClientPackageService.get_client_dashboard(db, corp_id)

    assert out.packages == []
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_get_client_dashboard_missing_corporate_raises():
    db = AsyncMock()
    db.execute.return_value = _result(scalar=None)
    with pytest.raises(LookupError):
        await ClientPackageService.get_client_dashboard(db, uuid4())
