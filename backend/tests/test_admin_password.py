"""Admin forgot-password and change-password endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin_auth import router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.services.admin_password import RESET_CONFIRMATION, AdminPasswordError


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(router, prefix="/admin/auth")

    async def _db():
        yield MagicMock()

    application.dependency_overrides[get_db] = _db
    return application


def test_forgot_password_always_returns_generic_confirmation(app):
    client = TestClient(app)
    with patch(
        "app.api.v1.admin_auth.request_admin_password_reset",
        new=AsyncMock(return_value=RESET_CONFIRMATION),
    ) as reset:
        res = client.post("/admin/auth/forgot-password", json={"email": "ops@mindq.com"})

    assert res.status_code == 200
    assert res.json()["detail"] == RESET_CONFIRMATION
    reset.assert_awaited_once()


def test_change_password_rejects_incorrect_current(app):
    ops_id = uuid4()
    corp_id = uuid4()

    async def _ops():
        return HRUserContext(
            user_id=ops_id, corporate_id=corp_id, email="ops@mindq.com", role="admin"
        )

    app.dependency_overrides[get_current_ops_user] = _ops
    client = TestClient(app)

    with patch(
        "app.api.v1.admin_auth.change_admin_password",
        new=AsyncMock(side_effect=AdminPasswordError("Incorrect current password.")),
    ):
        res = client.post(
            "/admin/auth/change-password",
            json={"current_password": "wrong-pass", "new_password": "new-secret1"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert res.status_code == 400
    assert res.json()["detail"] == "Incorrect current password."


def test_change_password_success(app):
    ops_id = uuid4()
    corp_id = uuid4()

    async def _ops():
        return HRUserContext(
            user_id=ops_id, corporate_id=corp_id, email="ops@mindq.com", role="admin"
        )

    app.dependency_overrides[get_current_ops_user] = _ops
    client = TestClient(app)

    with patch(
        "app.api.v1.admin_auth.change_admin_password",
        new=AsyncMock(return_value=None),
    ) as change:
        res = client.post(
            "/admin/auth/change-password",
            json={"current_password": "old-secret1", "new_password": "new-secret1"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert res.status_code == 200
    assert res.json()["detail"] == "Password updated."
    change.assert_awaited_once()
    kwargs = change.await_args.kwargs
    assert kwargs["current_password"] == "old-secret1"
    assert kwargs["new_password"] == "new-secret1"
    assert kwargs["access_token"] == "test-token"


def test_change_password_requires_bearer(app):
    ops_id = uuid4()
    corp_id = uuid4()

    async def _ops():
        return HRUserContext(
            user_id=ops_id, corporate_id=corp_id, email="ops@mindq.com", role="admin"
        )

    app.dependency_overrides[get_current_ops_user] = _ops
    client = TestClient(app)
    res = client.post(
        "/admin/auth/change-password",
        json={"current_password": "old-secret1", "new_password": "new-secret1"},
    )
    assert res.status_code == 401
