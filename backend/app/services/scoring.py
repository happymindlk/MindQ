"""Assessment scoring.

Computes a percentage score from a candidate's saved responses against the
assessment's stored question bank (which includes server-only answer keys).

Gradable item types, each contributing a credit in [0, 1]:

* ``mcq``  — all-or-nothing set equality against ``correct_answer`` (string for
  single-correct, list for multiple-valid; order-independent).
* ``sjt``  — chosen option weight divided by the best available weight.
* ``crt``  — strict match against ``accepted_answers`` (exact text or numeric).

Likert items are not right/wrong: they feed per-facet means (reverse-scored
items recoded ``6 - x``) returned in ``facet_scores``. Assessments with no
gradable items return a None score rather than fabricating a number.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Set

from app.schemas.question_payload import split_accepted_answers

LIKERT_MIN = 1
LIKERT_MAX = 5
NUMERIC_REL_TOLERANCE = 1e-6


def _extract_answer(value: Any) -> Any:
    """Responses are stored as JSON; accept a few common shapes."""
    if isinstance(value, dict):
        for key in ("answer", "value", "selected"):
            if key in value:
                return value[key]
        return None
    return value


def _normalize_answer_set(value: Any) -> Set[str]:
    """Normalize a correct_answer or candidate response into a string set."""
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    text = str(value).strip()
    return {text} if text else set()


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _parse_number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def crt_credit(question: dict[str, Any], given: Any) -> float | None:
    """Score one CRT answer against its accepted answers.

    Args:
        question: Stored CRT question (``accepted_answers``, ``match``).
        given: Candidate's extracted answer.

    Returns:
        1.0 for a reflective (accepted) answer, 0.0 otherwise, None when ungradable.
    """
    accepted = split_accepted_answers(question.get("accepted_answers"))
    if not accepted:
        return None
    if isinstance(given, (list, tuple)):
        given = given[0] if given else ""
    if question.get("match") == "numeric":
        number = _parse_number(given)
        if number is None:
            return 0.0
        for answer in accepted:
            target = _parse_number(answer)
            if target is not None and math.isclose(
                number, target, rel_tol=NUMERIC_REL_TOLERANCE, abs_tol=1e-9
            ):
                return 1.0
        return 0.0
    normalized = _normalize_text(given)
    return 1.0 if normalized and normalized in {_normalize_text(a) for a in accepted} else 0.0


def sjt_credit(question: dict[str, Any], given: Any) -> float | None:
    """Score one SJT choice as its weight relative to the best option.

    Args:
        question: Stored SJT question (``options``, ``option_weights``).
        given: Candidate's extracted answer (option text).

    Returns:
        Credit in [0, 1], or None when the weights are unusable.
    """
    options = [str(o) for o in (question.get("options") or [])]
    weights = question.get("option_weights") or []
    if not options or len(weights) != len(options):
        return None
    try:
        numeric_weights = [float(w) for w in weights]
    except (TypeError, ValueError):
        return None
    best = max(numeric_weights)
    if best <= 0:
        return None
    if isinstance(given, (list, tuple)):
        given = given[0] if given else None
    if given is None:
        return 0.0
    choice = str(given).strip()
    if choice in options:
        return numeric_weights[options.index(choice)] / best
    return 0.0


def _mcq_credit(question: dict[str, Any], given: Any) -> float | None:
    correct_answer = question.get("correct_answer")
    if correct_answer is None:
        return None
    expected = _normalize_answer_set(correct_answer)
    if not expected:
        return None
    return 1.0 if _normalize_answer_set(given) == expected else 0.0


def _likert_value(question: dict[str, Any], given: Any) -> float | None:
    """Resolve a Likert response to its facet contribution.

    Only the selected position counts; ``scale_labels`` are presentation-only so
    admins can relabel anchors without changing historical or future scores.

    Args:
        question: Stored Likert question (``reverse_scored`` flag honoured).
        given: Candidate response — the 1-based index of the chosen point.

    Returns:
        The index (recoded ``6 - x`` when reverse scored), or None when the
        response is missing, non-integral, or outside 1–5.
    """
    if isinstance(given, (list, tuple)):
        given = given[0] if given else None
    if isinstance(given, bool):
        return None
    number = _parse_number(given)
    if number is None or not number.is_integer() or not (LIKERT_MIN <= number <= LIKERT_MAX):
        return None
    if question.get("reverse_scored"):
        number = (LIKERT_MIN + LIKERT_MAX) - number
    return float(number)


@dataclass
class ScoreResult:
    """Aggregate result of scoring one assessment.

    Attributes:
        score: Percentage over gradable items, or None when nothing is gradable.
        facet_scores: ``{facet: {"mean": float, "n": int}}`` from Likert items.
        gradable_count: Number of items that contributed to ``score``.
    """

    score: Optional[float]
    facet_scores: dict[str, dict[str, float | int]] = field(default_factory=dict)
    gradable_count: int = 0


def score_assessment_detailed(questions: Optional[list], responses: Iterable) -> ScoreResult:
    """Score every supported item type and aggregate Likert facets.

    Args:
        questions: Stored question bank (with answer keys).
        responses: Rows exposing ``question_id`` and ``response``.

    Returns:
        ScoreResult with percentage score and facet means.
    """
    resp_map: dict[str, Any] = {}
    for r in responses:
        resp_map[str(r.question_id)] = _extract_answer(r.response)

    gradable = 0
    earned = 0.0
    facet_totals: dict[str, list[float]] = {}
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type", "")).lower()
        given = resp_map.get(str(q.get("id")))

        if qtype == "likert":
            value = _likert_value(q, given)
            if value is None:
                continue
            facet = str(q.get("facet") or q.get("evaluated_competency") or "General").strip() or "General"
            facet_totals.setdefault(facet, []).append(value)
            continue

        if qtype == "mcq":
            credit = _mcq_credit(q, given)
        elif qtype == "sjt":
            credit = sjt_credit(q, given)
        elif qtype == "crt":
            credit = crt_credit(q, given)
        else:
            credit = None
        if credit is None:
            continue
        gradable += 1
        earned += credit

    facet_scores = {
        facet: {"mean": round(sum(values) / len(values), 3), "n": len(values)}
        for facet, values in facet_totals.items()
    }
    score = round(earned / gradable * 100, 2) if gradable else None
    return ScoreResult(score=score, facet_scores=facet_scores, gradable_count=gradable)


def score_assessment(questions: Optional[list], responses: Iterable) -> Optional[float]:
    """Backward-compatible percentage score.

    Args:
        questions: Stored question bank.
        responses: Saved responses.

    Returns:
        Percentage over gradable items, or None.
    """
    return score_assessment_detailed(questions, responses).score
