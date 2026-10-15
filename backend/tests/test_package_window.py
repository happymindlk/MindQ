"""Package availability window, deadline extension, and clone-version resolution."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.candidate import _raise_integrity
from app.exceptions import PackageClosedError, PackageNotOpenError
from app.schemas.candidate import CandidateLogin
from app.schemas.client_package import (
    AdminPackageUpdateRequest,
    DraftPackageRequest,
    PackageScheduleUpdate,
)
from app.services.candidate_service import CandidateService
from app.services.client_package import (
    ClientPackageError,
    ClientPackageService,
    newest_by_lineage,
    resolve_cart_row,
)
from app.services.package_window import (
    ensure_module_launchable,
    ensure_package_open,
    format_sri_lanka,
    window_state,
)

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


# --- window_state / formatting -------------------------------------------------


@pytest.mark.parametrize(
    ("open_time", "close_time", "expected"),
    [
        (None, None, "open"),
        (NOW + HOUR, None, "not_open"),
        (NOW - HOUR, NOW + HOUR, "open"),
        (None, NOW, "closed"),  # deadline instant itself is closed
        (None, NOW - HOUR, "closed"),
        (NOW, None, "open"),  # open instant itself is open
    ],
)
def test_window_state(open_time, close_time, expected):
    assert window_state(open_time, close_time, NOW) == expected


def test_format_sri_lanka_converts_utc_to_plus_0530():
    deadline = datetime(2026, 10, 15, 11, 30, tzinfo=timezone.utc)
    assert format_sri_lanka(deadline) == "15 Oct 2026, 5:00 PM (Sri Lanka Time - GMT+5:30)"


def test_format_sri_lanka_midnight_and_day_rollover():
    # 18:30 UTC is 00:00 the next day in Colombo.
    value = datetime(2026, 12, 31, 18, 30, tzinfo=timezone.utc)
    assert format_sri_lanka(value) == "1 Jan 2027, 12:00 AM (Sri Lanka Time - GMT+5:30)"


# --- launch rules ------------------------------------------------------------


def test_before_open_blocks_even_started_modules():
    with pytest.raises(PackageNotOpenError):
        ensure_module_launchable(NOW + HOUR, None, NOW - HOUR, NOW)


def test_after_close_blocks_unstarted_module():
    with pytest.raises(PackageClosedError) as exc:
        ensure_module_launchable(None, NOW - HOUR, None, NOW)
    assert "Sri Lanka Time" in exc.value.detail


def test_after_close_allows_resuming_started_module():
    ensure_module_launchable(None, NOW - HOUR, NOW - 2 * HOUR, NOW)


def test_ensure_package_open_inside_window_is_noop():
    ensure_package_open(NOW - HOUR, NOW + HOUR, NOW)


def test_window_errors_map_to_structured_403():
    for exc, code in (
        (PackageClosedError("x"), "PACKAGE_CLOSED"),
        (PackageNotOpenError("x"), "PACKAGE_NOT_OPEN"),
    ):
        with pytest.raises(HTTPException) as raised:
            _raise_integrity(exc)
        assert raised.value.status_code == 403
        assert raised.value.detail["code"] == code


# --- schemas -------------------------------------------------------------------


def _draft(**overrides):
    base = {"corporate_id": str(uuid4()), "title": "Suite"}
    base.update(overrides)
    return DraftPackageRequest(**base)


def test_draft_accepts_offset_datetimes_and_blank_strings():
    draft = _draft(open_time="2026-10-15T09:00:00+05:30", close_time="")
    assert draft.open_time == datetime(2026, 10, 15, 3, 30, tzinfo=timezone.utc)
    assert draft.close_time is None


def test_draft_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        _draft(close_time="2026-10-15T09:00:00")


def test_draft_rejects_close_before_open():
    with pytest.raises(ValidationError, match="Close time must be after open time"):
        _draft(open_time="2026-10-15T09:00:00+05:30", close_time="2026-10-15T09:00:00+05:30")


def test_update_request_rejects_close_before_open():
    with pytest.raises(ValidationError):
        AdminPackageUpdateRequest(
            title="Suite",
            open_time="2026-10-16T00:00:00Z",
            close_time="2026-10-15T00:00:00Z",
        )


def test_schedule_update_forbids_unknown_fields_and_accepts_null():
    assert PackageScheduleUpdate(close_time=None).close_time is None
    with pytest.raises(ValidationError):
        PackageScheduleUpdate(close_time=None, open_time="2026-10-15T00:00:00Z")


# --- clone-version resolution -----------------------------------------------


def _module(*, version: int, lineage=None, questions=None, duration=None):
    mid = uuid4()
    return SimpleNamespace(
        id=mid,
        lineage_id=lineage,
        version=version,
        questions=questions if questions is not None else [{"id": f"q-v{version}"}],
        duration_seconds=duration,
    )


def test_newest_by_lineage_picks_highest_version_and_handles_root_rows():
    lineage = uuid4()
    v1 = _module(version=1, lineage=lineage)
    v3 = _module(version=3, lineage=lineage)
    v2 = _module(version=2, lineage=lineage)
    solo = _module(version=1, lineage=None)
    newest = newest_by_lineage([v1, v3, v2, solo])
    assert newest[lineage] is v3
    assert newest[solo.id] is solo


def test_resolve_keeps_pinned_when_already_latest():
    pinned = _module(version=1)
    override = [{"id": "custom"}]
    module, questions = resolve_cart_row(pinned, pinned, override)
    assert module is pinned
    assert questions == override
    assert questions is not override


def test_resolve_upgrades_to_cloned_version_with_its_duration():
    lineage = uuid4()
    v1 = _module(version=1, lineage=lineage, duration=600)
    v2 = _module(version=2, lineage=lineage, duration=1500, questions=[{"id": "q-v2"}])
    module, questions = resolve_cart_row(v1, v2, list(v1.questions))
    assert module is v2
    assert module.duration_seconds == 1500
    assert questions == [{"id": "q-v2"}]


def test_resolve_upgrade_without_snapshot_uses_latest_questions():
    lineage = uuid4()
    v1 = _module(version=1, lineage=lineage)
    v2 = _module(version=2, lineage=lineage)
    module, questions = resolve_cart_row(v1, v2, None)
    assert module is v2
    assert questions == v2.questions


def test_resolve_upgrade_preserves_suite_specific_question_edits():
    lineage = uuid4()
    v1 = _module(version=1, lineage=lineage)
    v2 = _module(version=2, lineage=lineage)
    customised = [{"id": "q-v1", "text": "edited for this client"}]
    module, questions = resolve_cart_row(v1, v2, customised)
    assert module is v2
    assert questions == customised


# --- candidate login window --------------------------------------------------


class _Result:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


class _SequenceSession:
    def __init__(self, *values):
        self._values = list(values)
        self.added: list = []

    async def execute(self, _stmt):
        return _Result(self._values.pop(0) if self._values else None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()


def _package(**window):
    return SimpleNamespace(
        id=uuid4(),
        corporate_id=uuid4(),
        access_code="HM-WIN01-A",
        is_active=True,
        allow_open_enrollment=True,
        open_time=window.get("open_time"),
        close_time=window.get("close_time"),
    )


def _login():
    return CandidateLogin(
        first_name="Ada", full_name="Ada Lovelace", email="ada@example.com", access_code="HM-WIN01-A"
    )


@pytest.mark.asyncio
async def test_login_before_open_is_rejected():
    now = datetime.now(timezone.utc)
    session = _SequenceSession(_package(open_time=now + HOUR), None)
    with pytest.raises(PackageNotOpenError):
        await CandidateService.login(session, _login())
    assert session.added == []


@pytest.mark.asyncio
async def test_login_after_close_without_started_work_is_rejected():
    now = datetime.now(timezone.utc)
    existing = SimpleNamespace(id=uuid4(), full_name="Ada", first_name="Ada")
    session = _SequenceSession(_package(close_time=now - HOUR), existing, None)
    with pytest.raises(PackageClosedError):
        await CandidateService.login(session, _login())


@pytest.mark.asyncio
async def test_login_after_close_allowed_to_finish_started_module():
    now = datetime.now(timezone.utc)
    existing = SimpleNamespace(id=uuid4(), full_name="Ada", first_name="Ada")
    session = _SequenceSession(_package(close_time=now - HOUR), existing, uuid4())
    candidate, is_new = await CandidateService.login(session, _login())
    assert candidate is existing
    assert is_new is False


# --- module launch gating ------------------------------------------------------


def _window_result(open_time, close_time):
    result = MagicMock()
    result.first.return_value = SimpleNamespace(open_time=open_time, close_time=close_time)
    return result


@pytest.mark.asyncio
async def test_require_writable_blocks_unstarted_module_after_deadline():
    now = datetime.now(timezone.utc)
    candidate = SimpleNamespace(id=uuid4(), package_id=uuid4())
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_window_result(None, now - HOUR))
    with (
        patch.object(
            CandidateService, "require_assessment_in_package", AsyncMock(return_value=object())
        ),
        patch.object(CandidateService, "_get_progress", AsyncMock(return_value=None)),
        pytest.raises(PackageClosedError),
    ):
        await CandidateService.require_writable_assessment(session, candidate, uuid4())


@pytest.mark.asyncio
async def test_require_writable_allows_in_progress_module_after_deadline():
    now = datetime.now(timezone.utc)
    candidate = SimpleNamespace(id=uuid4(), package_id=uuid4())
    progress = SimpleNamespace(status="IN_PROGRESS", started_at=now - 2 * HOUR)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_window_result(None, now - HOUR))
    assessment = object()
    with (
        patch.object(
            CandidateService, "require_assessment_in_package", AsyncMock(return_value=assessment)
        ),
        patch.object(CandidateService, "_get_progress", AsyncMock(return_value=progress)),
    ):
        result = await CandidateService.require_writable_assessment(session, candidate, uuid4())
    assert result == (assessment, progress)


# --- candidate dashboard ---------------------------------------------------------


class _ListResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def first(self):
        return self._values

    def all(self):
        return self._values


@pytest.mark.asyncio
async def test_dashboard_reports_closed_window_and_launchable_flags():
    now = datetime.now(timezone.utc)
    close_time = now - HOUR
    package = SimpleNamespace(title="Suite", open_time=None, close_time=close_time)
    fresh = SimpleNamespace(id=uuid4(), title="A", description=None)
    started = SimpleNamespace(id=uuid4(), title="B", description=None)
    done = SimpleNamespace(id=uuid4(), title="C", description=None)
    progresses = [
        SimpleNamespace(assessment_id=started.id, status="IN_PROGRESS", started_at=now - 2 * HOUR),
        SimpleNamespace(assessment_id=done.id, status="COMPLETED", started_at=now - 3 * HOUR),
    ]
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_ListResult(package), _ListResult([fresh, started, done]), _ListResult(progresses)]
    )
    candidate = SimpleNamespace(id=uuid4(), package_id=uuid4(), full_name="Ada L", first_name="Ada")

    data = await CandidateService.get_dashboard(session, candidate)

    assert data["window_state"] == "closed"
    assert data["close_time"] == close_time.isoformat()
    flags = {t["title"]: (t["status"], t["launchable"]) for t in data["tests"]}
    assert flags == {
        "A": ("not_started", False),
        "B": ("in_progress", True),
        "C": ("completed", False),
    }


# --- ops schedule + update preservation ------------------------------------------


def _scalar_one(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_update_schedule_extends_published_package():
    package = SimpleNamespace(id=uuid4(), status="published", open_time=NOW, close_time=NOW + HOUR)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_one(package))
    new_close = NOW + 48 * HOUR

    result = await ClientPackageService.update_schedule(
        session, package.id, PackageScheduleUpdate(close_time=new_close)
    )

    assert package.close_time == new_close
    assert result.close_time == new_close
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_schedule_rejects_deadline_before_open():
    package = SimpleNamespace(id=uuid4(), status="published", open_time=NOW, close_time=None)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_one(package))
    with pytest.raises(ClientPackageError):
        await ClientPackageService.update_schedule(
            session, package.id, PackageScheduleUpdate(close_time=NOW - HOUR)
        )
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_schedule_missing_package_raises_lookup():
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_one(None))
    with pytest.raises(LookupError):
        await ClientPackageService.update_schedule(
            session, uuid4(), PackageScheduleUpdate(close_time=None)
        )


@pytest.mark.asyncio
async def test_update_admin_package_keeps_brief_and_window_when_omitted():
    package = SimpleNamespace(
        id=uuid4(),
        corporate_id=uuid4(),
        status="draft",
        description="Existing brief",
        open_time=NOW,
        close_time=NOW + HOUR,
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_one(package))
    captured = {}

    async def fake_save(_session, draft, package_id=None):
        captured["draft"] = draft

    body = AdminPackageUpdateRequest(title="Suite", custom_questions=[])
    with (
        patch.object(ClientPackageService, "save_draft", side_effect=fake_save),
        patch.object(ClientPackageService, "get_admin_package", AsyncMock(return_value="detail")),
    ):
        await ClientPackageService.update_admin_package(session, package.id, body)

    draft = captured["draft"]
    assert draft.description == "Existing brief"
    assert draft.open_time == NOW
    assert draft.close_time == NOW + HOUR


@pytest.mark.asyncio
async def test_update_admin_package_applies_new_brief_and_cleared_deadline():
    package = SimpleNamespace(
        id=uuid4(), corporate_id=uuid4(), status="draft", description="Old", open_time=None,
        close_time=NOW,
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_scalar_one(package))
    captured = {}

    async def fake_save(_session, draft, package_id=None):
        captured["draft"] = draft

    body = AdminPackageUpdateRequest(
        title="Suite", description="New brief", close_time=None, custom_questions=[]
    )
    with (
        patch.object(ClientPackageService, "save_draft", side_effect=fake_save),
        patch.object(ClientPackageService, "get_admin_package", AsyncMock(return_value="detail")),
    ):
        await ClientPackageService.update_admin_package(session, package.id, body)

    assert captured["draft"].description == "New brief"
    assert captured["draft"].close_time is None
