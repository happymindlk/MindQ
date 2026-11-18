"""CandidateSessionLog recording + admin session-logs API."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_record_session_event_hashes_ip_and_reads_headers():
    from app.services.session_log import LOGIN, hash_client_ip, record_session_event

    class FakeRequest:
        def __init__(self):
            self.headers = {
                "X-Device-Id": "device-abc",
                "X-Browser-Info": "TestBrowser/1.0",
            }
            self.client = SimpleNamespace(host="203.0.113.9")
            self.state = SimpleNamespace()

    class FakeSession:
        def __init__(self):
            self.added = []

        def add(self, row):
            self.added.append(row)

        async def commit(self):
            return None

        async def refresh(self, row):
            if row.id is None:
                row.id = uuid4()
            if row.occurred_at is None:
                row.occurred_at = datetime.now(timezone.utc)

    request = FakeRequest()
    db = FakeSession()
    corp = uuid4()
    cand = uuid4()
    row = await record_session_event(
        db,
        corporate_id=corp,
        candidate_id=cand,
        event_type=LOGIN,
        request=request,
        commit=True,
    )
    assert row.event_type == LOGIN
    assert row.device_id == "device-abc"
    assert row.browser == "TestBrowser/1.0"
    assert row.ip_hash == hash_client_ip(request)
    assert len(row.ip_hash) == 64
    assert db.added[0] is row


def test_duration_from_progress_prefers_server_duration():
    from app.services.session_log import duration_from_progress

    started = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    completed = datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc)
    progress = SimpleNamespace(
        server_duration_seconds=42.6,
        started_at=started,
        completed_at=completed,
    )
    assert duration_from_progress(progress) == 43

    progress_no_server = SimpleNamespace(
        server_duration_seconds=None,
        started_at=started,
        completed_at=completed,
    )
    assert duration_from_progress(progress_no_server) == 600


@pytest.mark.asyncio
async def test_admin_session_logs_endpoint_tenant_scoped(async_client: AsyncClient, monkeypatch):
    from app.auth import HRUserContext, get_current_hr_user
    from app.database import get_db
    from app.main import app
    from app.models.candidate_session_log import CandidateSessionLog
    from app.services.candidate_service import CandidateService

    corp = uuid4()
    other_corp = uuid4()
    cand = uuid4()
    log_row = CandidateSessionLog(
        id=uuid4(),
        corporate_id=corp,
        candidate_id=cand,
        assessment_id=None,
        assessment_name=None,
        event_type="LOGIN",
        occurred_at=datetime.now(timezone.utc),
        duration_seconds=None,
        device_id="d1",
        browser="Chrome",
        ip_hash="abc",
    )

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [log_row]

    class FakeSession:
        async def execute(self, *_a, **_k):
            return FakeResult()

    async def fake_db():
        yield FakeSession()

    async def fake_hr():
        return HRUserContext(
            user_id=uuid4(),
            corporate_id=corp,
            email="hr@example.com",
            role="hr",
        )

    async def fake_other_hr():
        return HRUserContext(
            user_id=uuid4(),
            corporate_id=other_corp,
            email="other@example.com",
            role="hr",
        )

    async def fake_get_candidate(_session, _candidate_id):
        return SimpleNamespace(id=cand, corporate_id=corp)

    monkeypatch.setattr(CandidateService, "get_candidate", staticmethod(fake_get_candidate))

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_hr_user] = fake_hr
    try:
        res = await async_client.get(f"/api/v1/admin/candidates/{cand}/session-logs")
        assert res.status_code == 200
        body = res.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["event_type"] == "LOGIN"
        assert body["items"][0]["device_id"] == "d1"
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_hr_user] = fake_other_hr
    try:
        res = await async_client.get(f"/api/v1/admin/candidates/{cand}/session-logs")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()
