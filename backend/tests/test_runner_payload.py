"""Deterministic shuffling, strict deadlines, and sanitized runner payloads."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.services.runner_payload import (
    STRICT_GRACE_SECONDS,
    build_runner_payload,
    effective_duration_seconds,
    shuffle_questions,
    strict_deadline,
)

QUESTIONS = [{"id": f"q{i}", "text": f"Item {i}", "type": "likert", "reverse_scored": i % 2 == 0} for i in range(12)]


def test_shuffle_is_stable_per_seed_and_differs_across_seeds():
    first = [q["id"] for q in shuffle_questions(QUESTIONS, "cand-a:assess-1")]
    again = [q["id"] for q in shuffle_questions(QUESTIONS, "cand-a:assess-1")]
    other = [q["id"] for q in shuffle_questions(QUESTIONS, "cand-b:assess-1")]
    assert first == again
    assert first != other
    assert sorted(first) == sorted(q["id"] for q in QUESTIONS)


def test_shuffle_does_not_mutate_input():
    source = list(QUESTIONS)
    shuffle_questions(source, "seed")
    assert source == QUESTIONS


def test_effective_duration_prefers_seconds():
    assert effective_duration_seconds(90, 5) == 90
    assert effective_duration_seconds(0, 5) == 300
    assert effective_duration_seconds(None, None) is None


def test_strict_deadline_adds_grace():
    started = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    assert strict_deadline(started, 180) == started + timedelta(seconds=180 + STRICT_GRACE_SECONDS)
    assert strict_deadline(None, 180) is None
    assert strict_deadline(started, None) is None


def test_build_runner_payload_strips_keys_and_shuffles():
    payload = build_runner_payload(
        assessment_id=uuid4(),
        title="Personality",
        description=None,
        questions=QUESTIONS,
        time_limit_minutes=None,
        duration_seconds=0,
        timer_mode="bogus",
        shuffle=True,
        seed="cand:assess",
    )
    dumped = payload.model_dump()
    assert dumped["duration_seconds"] is None
    assert dumped["timer_mode"] == "flexible"
    assert dumped["shuffle_questions"] is True
    assert all("reverse_scored" not in q for q in dumped["questions"])
    expected = [q["id"] for q in shuffle_questions(QUESTIONS, "cand:assess")]
    assert [q["id"] for q in dumped["questions"]] == expected


def test_runner_payload_exposes_custom_likert_labels_but_not_reverse_flag():
    labels = ["Never", "Rarely", "Sometimes", "Often", "Always"]
    payload = build_runner_payload(
        assessment_id=uuid4(),
        title="Personality",
        description=None,
        questions=[{"id": "l1", "text": "I plan ahead", "type": "likert", "reverse_scored": True, "scale_labels": labels}],
        time_limit_minutes=None,
        duration_seconds=None,
        timer_mode="flexible",
        shuffle=False,
        seed="cand:assess",
    )
    question = payload.model_dump()["questions"][0]
    assert question["scale_labels"] == labels
    assert "reverse_scored" not in question
