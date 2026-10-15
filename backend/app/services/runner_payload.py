"""Candidate-runner payload assembly: sanitization, deterministic shuffling, timers."""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.schemas.candidate import CandidateTestResponse, strip_answer_keys

# Network latency + auto-submit round-trip allowance after a strict deadline.
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


def strict_deadline(
    started_at: datetime | None,
    duration_seconds: int | None,
    *,
    grace_seconds: int = STRICT_GRACE_SECONDS,
) -> datetime | None:
    """Compute the server-side cutoff for a strict-timer attempt.

    Args:
        started_at: When the attempt started (progress.started_at).
        duration_seconds: Effective module duration.
        grace_seconds: Allowance for latency and the client auto-submit.

    Returns:
        Deadline timestamp, or None when the attempt is not time-bound yet.
    """
    if started_at is None or not duration_seconds:
        return None
    return started_at + timedelta(seconds=int(duration_seconds) + grace_seconds)


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

    Returns:
        Typed payload; ``CandidateQuestion`` drops every non-allowlisted key.
    """
    safe = strip_answer_keys(questions)
    if shuffle:
        safe = shuffle_questions(safe, seed)
    duration = effective_duration_seconds(duration_seconds, time_limit_minutes)
    return CandidateTestResponse.model_validate(
        {
            "id": assessment_id,
            "title": title,
            "description": description,
            "time_limit_minutes": time_limit_minutes,
            "duration_seconds": duration,
            "timer_mode": timer_mode if timer_mode in ("strict", "flexible") else "flexible",
            "shuffle_questions": bool(shuffle),
            "started_at": started_at,
            "questions": safe,
            "answers": answers or {},
        }
    )
