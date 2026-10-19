"""Published packages must reject admin PUT with a clean 409 (not 400/502)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.admin_ops import router as admin_router
from app.auth import HRUserContext, get_current_ops_user
from app.database import get_db
from app.services.client_package import PackageLockedError

PUBLISHED_LOCK_DETAIL = "Package is published and locked"


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


def test_update_admin_package_published_returns_409():
    """Rogue draft PUTs against a published package must not mutate or 5xx."""
    package_id = uuid4()
    session = AsyncMock()

    with patch(
        "app.api.v1.admin_ops.ClientPackageService.update_admin_package",
        new_callable=AsyncMock,
        side_effect=PackageLockedError(PUBLISHED_LOCK_DETAIL),
    ) as update:
        res = _client(session).put(
            f"/admin/packages/{package_id}",
            json={"title": "Should not apply"},
        )

    assert res.status_code == 409
    assert res.json() == {"detail": PUBLISHED_LOCK_DETAIL}
    update.assert_awaited_once()


def test_update_admin_package_locked_error_never_becomes_500():
    """Any PackageLockedError maps to 409 with a stable client-facing detail."""
    package_id = uuid4()
    session = AsyncMock()

    with patch(
        "app.api.v1.admin_ops.ClientPackageService.update_admin_package",
        new_callable=AsyncMock,
        side_effect=PackageLockedError("Published packages are locked"),
    ):
        res = _client(session).put(
            f"/admin/packages/{package_id}",
            json={"title": "Rogue edit"},
        )

    assert res.status_code == 409
    assert res.json()["detail"] == PUBLISHED_LOCK_DETAIL
