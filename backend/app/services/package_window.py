"""Package availability window (open_time / close_time) shared by ops and candidates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from app.exceptions import PackageClosedError, PackageNotOpenError

# Sri Lanka observes no DST, so a fixed offset is exact and avoids a tzdata dependency.
SRI_LANKA_TZ = timezone(timedelta(hours=5, minutes=30), name="IST")

WindowState = Literal["not_open", "open", "closed"]


def window_state(
    open_time: datetime | None, close_time: datetime | None, now: datetime
) -> WindowState:
    """Classify ``now`` against a package's availability window.

    Args:
        open_time: Earliest access instant; None = open immediately.
        close_time: Deadline instant; None = no deadline.
        now: Current UTC instant.

    Returns:
        ``not_open`` before ``open_time``, ``closed`` at or after ``close_time``,
        otherwise ``open``.
    """
    if open_time is not None and now < open_time:
        return "not_open"
    if close_time is not None and now >= close_time:
        return "closed"
    return "open"


def format_sri_lanka(value: datetime) -> str:
    """Render an instant as Sri Lanka wall-clock time for candidate-facing copy.

    Args:
        value: Timezone-aware instant.

    Returns:
        e.g. ``"15 Oct 2026, 5:00 PM (Sri Lanka Time - GMT+5:30)"``.
    """
    local = value.astimezone(SRI_LANKA_TZ)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local.day} {local.strftime('%b %Y')}, {hour}:{local.strftime('%M %p')} (Sri Lanka Time - GMT+5:30)"


def ensure_package_open(open_time: datetime | None, close_time: datetime | None, now: datetime) -> None:
    """Reject any candidate activity outside the window.

    Args:
        open_time: Package open instant.
        close_time: Package deadline.
        now: Current UTC instant.

    Raises:
        PackageNotOpenError: Before ``open_time``.
        PackageClosedError: At or after ``close_time``.
    """
    state = window_state(open_time, close_time, now)
    if state == "not_open" and open_time is not None:
        raise PackageNotOpenError(format_sri_lanka(open_time))
    if state == "closed" and close_time is not None:
        raise PackageClosedError(format_sri_lanka(close_time))


def ensure_module_launchable(
    open_time: datetime | None,
    close_time: datetime | None,
    started_at: datetime | None,
    now: datetime,
) -> None:
    """Gate module access: nothing before open; only already-started work after close.

    A candidate mid-module when the deadline passes may finish and submit it
    (its own timer still applies); unstarted modules can no longer be launched.

    Args:
        open_time: Package open instant.
        close_time: Package deadline.
        started_at: When this candidate first opened the module, if ever.
        now: Current UTC instant.

    Raises:
        PackageNotOpenError: Before ``open_time``.
        PackageClosedError: After ``close_time`` for a module never started.
    """
    state = window_state(open_time, close_time, now)
    if state == "not_open" and open_time is not None:
        raise PackageNotOpenError(format_sri_lanka(open_time))
    if state == "closed" and close_time is not None and started_at is None:
        raise PackageClosedError(format_sri_lanka(close_time))
