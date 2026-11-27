"""GET /auth/me: hr_users membership resolved server-side from the verified token."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.auth_me import router as auth_me_router
from app.auth import SupabaseUserContext, get_current_supabase_user
from app.database import get_db


def _client(session: AsyncMock, user: SupabaseUserContext | None) -> TestClient:
    application = FastAPI()
    application.include_router(auth_me_router, prefix="/auth")

    async def _db():
        yield session

    async def _user():
        if user is None:
            raise HTTPException(status_code=401, detail="Missing bearer token")
        return user

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_supabase_user] = _user
    return TestClient(application)


def _session(row):
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def test_me_returns_membership_from_table_not_claims():
    user_id = uuid4()
    db_corp = uuid4()
    row = SimpleNamespace(user_id=user_id, corporate_id=db_corp, role="admin", full_name="Ops Person")
    # Token claims are stale (different corp, hr role); the table wins.
    user = SupabaseUserContext(user_id=user_id, corporate_id=uuid4(), role="hr")

    res = _client(_session(row), user).get("/auth/me")

    assert res.status_code == 200
    assert res.json() == {
        "user_id": str(user_id),
        "corporate_id": str(db_corp),
        "role": "admin",
        "full_name": "Ops Person",
    }


def test_me_returns_null_when_unprovisioned():
    # Works without tenant claims in the token (fresh sign-up).
    user = SupabaseUserContext(user_id=uuid4())

    res = _client(_session(None), user).get("/auth/me")

    assert res.status_code == 200
    assert res.json() is None


def test_me_queries_by_token_subject():
    user_id = uuid4()
    session = _session(None)

    _client(session, SupabaseUserContext(user_id=user_id)).get("/auth/me")

    stmt = session.execute.await_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": True})
    assert user_id.hex in str(compiled).replace("-", "")


def test_me_requires_token():
    session = _session(None)

    res = _client(session, None).get("/auth/me")

    assert res.status_code == 401
    session.execute.assert_not_called()
