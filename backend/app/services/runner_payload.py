"""Candidate-runner payload assembly: sanitization, deterministic shuffling, timers."""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.schemas.candidate import CandidateTestResponse, strip_answer_keys
from app.schemas.question_payload import (
    DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
    DEFAULT_TOP_DISCLAIMER_TEXT,
)

# Network latency + auto-submit round-trip allowance after a timed deadline.
STRICT_GRACE_SECONDS = 30


def shuffle_questions(questions: list[dict[str, Any]], seed: str) -> list[dict[str, Any]]:
    """Return a stable permutation of ``questions`` for a given seed.

    Seeding by candidate + assessment keeps the order identical across reloads
    (so autosave hydration and "question 7 of 20" stay consistent) while still
    jumbling IPIP/HEXACO items differently per candidate.

    Args:
        questions: Question dicts in authored order.
        seed: Stable seed string, e.g. ``f"{candidate_id}:{assessment_id}"``.

    Returns:
        New list in shuffled order; the input list is not mutated.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    shuffled = list(questions)
    rng.shuffle(shuffled)
    return shuffled


def effective_duration_seconds(
    duration_seconds: int | None, time_limit_minutes: int | None
) -> int | None:
    """Resolve the module duration, preferring second precision.

    Args:
        duration_seconds: New authoritative column (0/None = untimed).
        time_limit_minutes: Legacy column.

    Returns:
        Duration in seconds, or None when untimed.
    """
    if duration_seconds:
        return int(duration_seconds)
    if time_limit_minutes:
        return int(time_limit_minutes) * 60
    return None


def display_expires_at(
    started_at: datetime | None,
    duration_seconds: int | None,
) -> datetime | None:
    """Immutable display deadline: ``started_at + duration`` (no grace).

    Args:
        started_at: When the attempt started.
        duration_seconds: Effective module duration.

    Returns:
        Display deadline, or None when untimed / not started.
    """
    if started_at is None or not duration_seconds:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at + timedelta(seconds=int(duration_seconds))


def strict_deadline(
    started_at: datetime | None,
    duration_seconds: int | None,
    *,
    grace_seconds: int = STRICT_GRACE_SECONDS,
    expires_at: datetime | None = None,
) -> datetime | None:
    """Compute the server-side write cutoff for any timed attempt.

    Prefers a persisted ``expires_at`` (display end) + grace when present.
    Applies to every module with a positive duration, regardless of
    ``timer_mode``. The grace window covers client auto-submit latency.

    Args:
        started_at: When the attempt started (progress.started_at).
        duration_seconds: Effective module duration.
        grace_seconds: Allowance for latency and the client auto-submit.
        expires_at: Persisted display deadline when already set.

    Returns:
        Write-lock deadline timestamp, or None when the attempt is not time-bound yet.
    """
    display = expires_at
    if display is not None:
        if display.tzinfo is None:
            display = display.replace(tzinfo=timezone.utc)
        return display + timedelta(seconds=int(grace_seconds))
    if started_at is None or not duration_seconds:
        return None
    return started_at + timedelta(seconds=int(duration_seconds) + grace_seconds)


def remaining_seconds(
    started_at: datetime | None,
    duration_seconds: int | None,
    now: datetime,
    *,
    expires_at: datetime | None = None,
) -> int | None:
    """Server-authoritative display countdown for one module attempt.

    Prefers persisted ``expires_at`` when present so remounts match wall clock.
    Does not include the write-grace window — see ``write_remaining_seconds``.

    Args:
        started_at: When this module's attempt started; None if not started.
        duration_seconds: Effective module duration; None/0 when untimed.
        now: Current UTC instant.
        expires_at: Persisted display deadline when already set.

    Returns:
        Whole seconds left (clamped at 0), the full duration when not started,
        or None when the module is untimed.
    """
    if not duration_seconds and expires_at is None:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    deadline = expires_at
    if deadline is None:
        if started_at is None:
            return int(duration_seconds) if duration_seconds else None
        deadline = display_expires_at(started_at, duration_seconds)
    if deadline is None:
        return None
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return max(0, int((deadline - now).total_seconds()))


def write_remaining_seconds(
    started_at: datetime | None,
    duration_seconds: int | None,
    now: datetime,
    *,
    grace_seconds: int = STRICT_GRACE_SECONDS,
    expires_at: datetime | None = None,
) -> int | None:
    """Seconds left until the server write lock (duration + grace).

    The client seeds auto-submit / expire from this value so resume during the
    post-duration grace window does not instant-submit while autosave still
    succeeds.

    Args:
        started_at: When this module's attempt started; None if not started.
        duration_seconds: Effective module duration; None/0 when untimed.
        now: Current UTC instant.
        grace_seconds: Same allowance as ``strict_deadline``.
        expires_at: Persisted display deadline when already set.

    Returns:
        Whole seconds until write lock (clamped at 0), the full
        duration+grace when not started, or None when untimed.
    """
    if not duration_seconds and expires_at is None:
        return None
    if started_at is None and expires_at is None:
        return int(duration_seconds) + int(grace_seconds) if duration_seconds else None
    deadline = strict_deadline(
        started_at,
        duration_seconds,
        grace_seconds=grace_seconds,
        expires_at=expires_at,
    )
    if deadline is None:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, int((deadline - now).total_seconds()))


def build_runner_payload(
    *,
    assessment_id: UUID,
    title: str,
    description: str | None,
    questions: list[Any] | None,
    time_limit_minutes: int | None,
    duration_seconds: int | None,
    timer_mode: str | None,
    shuffle: bool,
    seed: str,
    answers: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    expires_at: datetime | None = None,
    module_kind: str | None = None,
    show_top_disclaimer: bool = False,
    top_disclaimer_text: str | None = None,
    show_confidentiality_notice: bool = False,
    confidentiality_notice_text: str | None = None,
    now: datetime | None = None,
) -> CandidateTestResponse:
    """Assemble the sanitized test payload served to the candidate runner.

    Args:
        assessment_id: Assessment (or module, in preview) id.
        title: Display title.
        description: Optional description.
        questions: Stored question bank including server-only keys.
        time_limit_minutes: Legacy minute limit.
        duration_seconds: Second-precision limit (0/None = untimed).
        timer_mode: ``strict`` or ``flexible``.
        shuffle: Whether to apply the seeded permutation.
        seed: Shuffle seed.
        answers: Previously saved answers for hydration.
        started_at: Attempt start, so the client can resume a strict countdown.
        expires_at: Persisted immutable display deadline when started.
        module_kind: ``psychometric`` or ``technical``; anything else
            normalizes to ``technical``.
        show_top_disclaimer: Whether the module top disclaimer renders.
        top_disclaimer_text: Module top disclaimer wording.
        show_confidentiality_notice: Whether the confidentiality notice renders.
        confidentiality_notice_text: Confidentiality notice wording.
        now: Current UTC instant for countdown fields; defaults to now.

    Returns:
        Typed payload; ``CandidateQuestion`` drops every non-allowlisted key.
    """
    safe = strip_answer_keys(questions)
    if shuffle:
        safe = shuffle_questions(safe, seed)
    duration = effective_duration_seconds(duration_seconds, time_limit_minutes)
    clock_now = now or datetime.now(timezone.utc)
    display_deadline = expires_at or display_expires_at(started_at, duration)
    write_deadline = strict_deadline(
        started_at, duration, expires_at=display_deadline
    )
    return CandidateTestResponse.model_validate(
        {
            "id": assessment_id,
            "title": title,
            "description": description,
            "module_kind": "psychometric" if module_kind == "psychometric" else "technical",
            "time_limit_minutes": time_limit_minutes,
            "duration_seconds": duration,
            "timer_mode": timer_mode if timer_mode in ("strict", "flexible") else "flexible",
            "shuffle_questions": bool(shuffle),
            "show_top_disclaimer": bool(show_top_disclaimer),
            "top_disclaimer_text": top_disclaimer_text or DEFAULT_TOP_DISCLAIMER_TEXT,
            "show_confidentiality_notice": bool(show_confidentiality_notice),
            "confidentiality_notice_text": confidentiality_notice_text
            or DEFAULT_CONFIDENTIALITY_NOTICE_TEXT,
            "started_at": started_at,
            "expires_at": display_deadline,
            "write_expires_at": write_deadline,
            "server_now": clock_now,
            "remaining_seconds": remaining_seconds(
                started_at, duration, clock_now, expires_at=display_deadline
            ),
            "write_remaining_seconds": write_remaining_seconds(
                started_at, duration, clock_now, expires_at=display_deadline
            ),
            "questions": safe,
            "answers": answers or {},
        }
    )
