"""Invite HR must never demote an existing ops (admin/owner) account."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin_ops import router as admin_router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db


def _scalar(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _client(session: AsyncMock) -> TestClient:
    application = FastAPI()
    application.include_router(admin_router, prefix="/admin")

    async def _db():
        yield session

    async def _ops():
        return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")

    application.dependency_overrides[get_db] = _db
    application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application)


@pytest.mark.parametrize("ops_role", ["admin", "owner"])
def test_invite_rejects_existing_ops_email_without_sending(ops_role: str):
    corporate = MagicMock()
    session = AsyncMock()
    session.execute.side_effect = [_scalar(corporate), _scalar(ops_role)]

    with patch("app.api.v1.admin_ops.invite_hr_user_by_email") as invite:
        res = _client(session).post(
            f"/admin/companies/{uuid4()}/invite-hr",
            json={"email": "ops@happymind.test"},
        )

    assert res.status_code == 409
    invite.assert_not_called()
    session.commit.assert_not_called()


def test_invite_proceeds_for_new_or_hr_email():
    corporate = MagicMock()
    session = AsyncMock()
    session.execute.side_effect = [_scalar(corporate), _scalar(None), MagicMock()]

    with patch(
        "app.api.v1.admin_ops.invite_hr_user_by_email", return_value=str(uuid4())
    ) as invite:
        res = _client(session).post(
            f"/admin/companies/{uuid4()}/invite-hr",
            json={"email": "hr@acme.test"},
        )

    assert res.status_code == 200
    invite.assert_called_once()
    session.commit.assert_awaited_once()
