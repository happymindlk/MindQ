"""Corporate HR email whitelist → `/client/login` OTP access sync."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.corporate import Corporate
from app.services.corporate_hr_access import (
    normalize_hr_email_list,
    provision_hr_emails,
    revoke_hr_emails,
    sync_contact_email,
    sync_corporate_hr_access,
)
from app.services.hr_otp import HrOtpError, request_hr_otp


def test_normalize_hr_email_list_dedupes_case_insensitively():
    assert normalize_hr_email_list(
        [" HR@Acme.Test ", "hr@acme.test", "People@Acme.Test", ""]
    ) == ["hr@acme.test", "people@acme.test"]


def test_sync_contact_email_uses_first_or_null():
    corp = Corporate(id=uuid4(), name="Acme", slug="acme", contact_email="old@acme.test")
    sync_contact_email(corp, ["a@acme.test", "b@acme.test"])
    assert corp.contact_email == "a@acme.test"
    sync_contact_email(corp, [])
    assert corp.contact_email is None


@pytest.mark.asyncio
async def test_sync_provisions_added_emails_without_sending_invite():
    corporate_id = uuid4()
    corp = Corporate(
        id=corporate_id,
        name="Acme",
        slug="acme",
        contact_email="hr@acme.test",
        allowed_hr_emails=["hr@acme.test"],
    )
    session = AsyncMock()
    session.flush = AsyncMock()
    provisioned: list[str] = []
    invites_sent: list[str] = []

    async def _provision(session, *, corporate_id, emails):
        provisioned.extend(emails)

    async def _revoke(session, *, corporate_id, emails):
        raise AssertionError("should not revoke on add-only sync")

    with (
        patch(
            "app.services.corporate_hr_access.provision_hr_emails",
            new=_provision,
        ),
        patch(
            "app.services.corporate_hr_access.revoke_hr_emails",
            new=_revoke,
        ),
        patch(
            "app.services.supabase_admin.invite_hr_user_by_email",
            side_effect=lambda *a, **k: invites_sent.append(a[0] if a else k),
        ),
    ):
        await sync_corporate_hr_access(
            session,
            corp,
            ["hr@acme.test", "people@acme.test"],
        )

    assert corp.allowed_hr_emails == ["hr@acme.test", "people@acme.test"]
    assert corp.contact_email == "hr@acme.test"
    assert provisioned == ["people@acme.test"]
    assert invites_sent == []


@pytest.mark.asyncio
async def test_sync_revokes_removed_email_access():
    corporate_id = uuid4()
    corp = Corporate(
        id=corporate_id,
        name="Acme",
        slug="acme",
        contact_email="hr@acme.test",
        allowed_hr_emails=["hr@acme.test", "gone@acme.test"],
    )
    session = AsyncMock()
    revoked: list[str] = []

    async def _provision(session, *, corporate_id, emails):
        raise AssertionError("should not provision on remove-only sync")

    async def _revoke(session, *, corporate_id, emails):
        revoked.extend(emails)

    with (
        patch(
            "app.services.corporate_hr_access.provision_hr_emails",
            new=_provision,
        ),
        patch(
            "app.services.corporate_hr_access.revoke_hr_emails",
            new=_revoke,
        ),
    ):
        await sync_corporate_hr_access(session, corp, ["hr@acme.test"])

    assert corp.allowed_hr_emails == ["hr@acme.test"]
    assert corp.contact_email == "hr@acme.test"
    assert revoked == ["gone@acme.test"]


@pytest.mark.asyncio
async def test_provision_hr_emails_uses_ensure_auth_not_invite():
    session = AsyncMock()
    user_id = uuid4()
    corporate_id = uuid4()
    ensure = MagicMock(return_value=user_id)
    invite = MagicMock()
    upsert = AsyncMock()

    with (
        patch(
            "app.services.corporate_hr_access.ensure_auth_user",
            ensure,
        ),
        patch(
            "app.services.corporate_hr_access.upsert_hr_membership",
            upsert,
        ),
        patch(
            "app.api.v1.admin_ops.invite_hr_user_by_email",
            invite,
        ),
    ):
        await provision_hr_emails(
            session,
            corporate_id=corporate_id,
            emails=["hr@acme.test", "people@acme.test"],
        )

    assert ensure.call_count == 2
    assert upsert.await_count == 2
    invite.assert_not_called()


@pytest.mark.asyncio
async def test_revoke_hr_emails_deletes_membership_row():
    session = AsyncMock()
    corporate_id = uuid4()
    user_id = uuid4()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(all=MagicMock(return_value=[("gone@acme.test", user_id)])),
            MagicMock(),
        ]
    )

    await revoke_hr_emails(
        session, corporate_id=corporate_id, emails=["gone@acme.test"]
    )

    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_removed_email_cannot_request_hr_otp():
    """After whitelist removal, OTP request is rejected for that email."""
    corporate_id = uuid4()
    corp = SimpleNamespace(
        id=corporate_id,
        is_active=True,
        contact_email="hr@acme.test",
        allowed_hr_emails=["hr@acme.test"],  # gone@ removed
    )

    class _Result:
        def __init__(self, *, scalars=None, scalar=None):
            self._scalars = scalars or []
            self._scalar = scalar

        def scalars(self):
            return SimpleNamespace(all=lambda: self._scalars)

        def scalar_one_or_none(self):
            return self._scalar

    class _FakeDb:
        def __init__(self):
            self.added = []

        async def execute(self, *_a, **_k):
            return _Result(scalars=[corp])

        def add(self, row):
            self.added.append(row)

        async def flush(self):
            return None

        async def commit(self):
            return None

    db = _FakeDb()
    with patch(
        "app.services.hr_otp.find_auth_user_id_by_email",
        return_value=None,
    ):
        with pytest.raises(HrOtpError) as exc:
            await request_hr_otp(db, "gone@acme.test")
    assert exc.value.status_code == 403
    assert "not registered" in exc.value.detail
