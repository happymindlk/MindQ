"""Soft single-device lock for candidate portal sessions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.models.candidate import Candidate

ACTIVE_SESSION_WINDOW = timedelta(minutes=3)
DEVICE_SESSION_CONFLICT_DETAIL = (
    "You’re already logged in from one device, please close the other "
    "device’s session and try again from this device"
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """Normalize a DB timestamp to timezone-aware UTC for comparisons."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_active_session(candidate: Candidate, *, now: datetime | None = None) -> bool:
    """True when the candidate has a device lock still within the soft window.

    Args:
        candidate: Candidate row with optional active_device_id / session_last_seen_at.
        now: Comparison instant (defaults to UTC now).

    Returns:
        Whether another device should be blocked from claiming the session.
    """
    if not (candidate.active_device_id or "").strip():
        return False
    last_seen = _aware(candidate.session_last_seen_at)
    if last_seen is None:
        return False
    current = _aware(now) or _utcnow()
    return current - last_seen <= ACTIVE_SESSION_WINDOW


def enforce_device_login(candidate: Candidate, device_id: str | None) -> None:
    """Reject login when another device holds an active soft session.

    Args:
        candidate: Candidate about to receive a portal JWT.
        device_id: Incoming ``X-Device-Id`` (may be empty/None).

    Raises:
        HTTPException: 409 Conflict with the fixed candidate-facing detail.
    """
    incoming = (device_id or "").strip()
    active = (candidate.active_device_id or "").strip()
    if not active or not is_active_session(candidate):
        return
    if incoming and incoming == active:
        return
    raise HTTPException(status_code=409, detail=DEVICE_SESSION_CONFLICT_DETAIL)


def claim_device_session(
    candidate: Candidate, device_id: str | None, *, now: datetime | None = None
) -> None:
    """Bind the candidate portal session to ``device_id`` and stamp last-seen.

    Args:
        candidate: Candidate row to mutate (caller owns the transaction).
        device_id: Incoming ``X-Device-Id``; empty clears nothing and leaves prior lock.
        now: Stamp instant (defaults to UTC now).
    """
    stamp = _aware(now) or _utcnow()
    incoming = (device_id or "").strip() or None
    if incoming:
        candidate.active_device_id = incoming[:64]
    candidate.session_last_seen_at = stamp


def touch_session_last_seen(
    candidate: Candidate, *, now: datetime | None = None
) -> None:
    """Refresh ``session_last_seen_at`` for an authenticated portal request.

    Args:
        candidate: Authenticated candidate row (caller owns the transaction).
        now: Stamp instant (defaults to UTC now).
    """
    candidate.session_last_seen_at = _aware(now) or _utcnow()


def clear_device_session(candidate: Candidate) -> None:
    """Release the single-device lock on logout.

    Args:
        candidate: Authenticated candidate row (caller owns the transaction).
    """
    candidate.active_device_id = None
