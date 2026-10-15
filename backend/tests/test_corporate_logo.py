"""Tests for corporate logo upload endpoint."""
from __future__ import annotations

from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.corporates import router
from app.auth import HRUserContext, get_current_hr_user


@pytest.fixture
def corp_id():
    return uuid4()


@pytest.fixture
def app(corp_id):
    application = FastAPI()
    application.include_router(router, prefix="/corporates")

    async def _hr():
        return HRUserContext(user_id=uuid4(), corporate_id=corp_id, email="hr@test.com")

    application.dependency_overrides[get_current_hr_user] = _hr
    return application


def test_logo_upload_returns_public_url(app, corp_id):
    client = TestClient(app)
    public = f"https://cdn.example.com/logos/{corp_id}/logo-1.png"

    with (
        patch("app.api.v1.corporates.settings") as settings,
        patch("app.api.v1.corporates.upload_logo", return_value=public) as upload,
    ):
        settings.r2_configured = True
        settings.r2_public_base = "https://cdn.example.com"
        res = client.post(
            f"/corporates/{corp_id}/logo",
            files={"file": ("logo.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )

    assert res.status_code == 200
    assert res.json()["logo_url"] == public
    upload.assert_called_once()
    args = upload.call_args.args
    assert args[0] == corp_id
    assert args[1].endswith(".png")
    assert args[2].startswith(b"\x89PNG")
    assert args[3] == "image/png"


def test_logo_upload_rejects_other_tenant(app, corp_id):
    client = TestClient(app)
    other = uuid4()
    with patch("app.api.v1.corporates.settings") as settings:
        settings.r2_configured = True
        settings.r2_public_base = "https://cdn.example.com"
        res = client.post(
            f"/corporates/{other}/logo",
            files={"file": ("logo.png", b"abc", "image/png")},
        )
    assert res.status_code == 403


def test_logo_upload_rejects_bad_type(app, corp_id):
    client = TestClient(app)
    with patch("app.api.v1.corporates.settings") as settings:
        settings.r2_configured = True
        settings.r2_public_base = "https://cdn.example.com"
        res = client.post(
            f"/corporates/{corp_id}/logo",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    assert res.status_code == 400
