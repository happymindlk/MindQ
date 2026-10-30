"""Assessment scoring.

Computes a percentage score from a candidate's saved responses against the
assessment's stored question bank (which includes server-only answer keys).

Gradable item types, each contributing a credit in [0, 1]:

* ``mcq``  — all-or-nothing set equality against ``correct_answer`` (string for
  single-correct, list for multiple-valid; order-independent).
* ``sjt``  — chosen option weight divided by the best available weight.
* ``crt``  — strict match against ``accepted_answers`` (exact text or numeric).

Likert items are not right/wrong: they feed per-facet means (reverse-scored
items recoded ``(min + max) - x``) returned in ``facet_scores``. Assessments
with no gradable items return a None score rather than fabricating a number.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Set

from app.schemas.question_payload import split_accepted_answers

LIKERT_MIN = 1
LIKERT_MAX = 5
LIKERT_MAX_POINTS = 7
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


_FIRST_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")
_WORD_NUMBERS = {
    "zero": 0.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "twenty": 20.0,
    "twenty four": 24.0,
    "hundred": 100.0,
}


def _parse_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        match = _FIRST_NUMBER.search(text)
        if match:
            try:
                number = float(match.group(0))
            except ValueError:
                number = None
        else:
            number = None
        if number is None:
            words = re.sub(r"\b(cents?|dollars?|minutes?|days?|hours?)\b", " ", text.casefold())
            words = re.sub(r"\s+", " ", words).strip()
            mapped = _WORD_NUMBERS.get(words)
            if mapped is None:
                return None
            number = mapped
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
    normalized = _normalize_text(given)
    accepted_text = {_normalize_text(a) for a in accepted}
    if normalized and normalized in accepted_text:
        return 1.0
    if question.get("match") != "numeric":
        return 0.0
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


def _likert_option_values(question: dict[str, Any] | None) -> list[int] | None:
    """Extract integer option values from stored Likert ``options``.

    Args:
        question: Stored question dict, or None.

    Returns:
        Values in display order, or None when the item has no value rows.
    """
    if not isinstance(question, dict):
        return None
    raw = question.get("options")
    if not isinstance(raw, list) or not raw:
        return None
    values: list[int] = []
    for row in raw:
        candidate = row.get("value") if isinstance(row, dict) else row
        if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
            continue
        if int(candidate) != candidate:
            continue
        values.append(int(candidate))
    return values or None


def likert_scale_bounds(question: dict[str, Any] | None) -> tuple[int, int]:
    """Return ``(scale_min, scale_max)`` for a Likert item.

    Args:
        question: Stored Likert question, or None.

    Returns:
        Min/max option values when present; otherwise ``1`` and the 5–7 point
        length from ``scale_points`` / labels.
    """
    values = _likert_option_values(question)
    if values:
        return min(values), max(values)
    if not isinstance(question, dict):
        return LIKERT_MIN, LIKERT_MAX
    points = question.get("scale_points")
    if isinstance(points, bool) or not isinstance(points, (int, float)):
        points = None
    elif int(points) != points:
        points = None
    else:
        points = int(points)
    if points is None:
        labels = question.get("scale_labels")
        if isinstance(labels, (list, tuple)) and labels:
            points = len(labels)
    if points is None or not (LIKERT_MAX <= points <= LIKERT_MAX_POINTS):
        return LIKERT_MIN, LIKERT_MAX
    return LIKERT_MIN, points


def likert_scale_max(question: dict[str, Any] | None) -> int:
    """Return the inclusive upper bound of a Likert item.

    Args:
        question: Stored Likert question, or None.

    Returns:
        Max option value, or ``scale_points`` / label count when in 5–7.
    """
    return likert_scale_bounds(question)[1]


def likert_scale_min(question: dict[str, Any] | None) -> int:
    """Return the inclusive lower bound of a Likert item.

    Args:
        question: Stored Likert question, or None.

    Returns:
        Min option value, or 1 when the item uses sequential 1-based scoring.
    """
    return likert_scale_bounds(question)[0]


def likert_scale_max_from_questions(questions: Iterable | None) -> int:
    """Widest Likert upper bound among a stored question bank.

    Args:
        questions: Assessment or catalog questions.

    Returns:
        5 unless a wider item (7-point, or custom values) is present.
    """
    widest = LIKERT_MAX
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        if str(question.get("type", "")).lower() != "likert":
            continue
        widest = max(widest, likert_scale_max(question))
    return widest


def likert_scale_min_from_questions(questions: Iterable | None) -> int:
    """Lowest Likert lower bound among a stored question bank.

    Args:
        questions: Assessment or catalog questions.

    Returns:
        1 unless an item defines a smaller option value.
    """
    lowest: int | None = None
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        if str(question.get("type", "")).lower() != "likert":
            continue
        lo, _hi = likert_scale_bounds(question)
        lowest = lo if lowest is None else min(lowest, lo)
    return LIKERT_MIN if lowest is None else lowest


def _option_letter(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    head = stripped[0].upper()
    if head not in "ABCDEFGH":
        return None
    if len(stripped) == 1 or stripped[1] in ".)":
        return head
    return None


def resolve_choice(given: Any, options: list[str]) -> str | None:
    """Map a candidate answer onto an option string.

    Accepts the full option text or a letter key (``B`` / ``B.``) so catalog
    vectors keyed A–D still score after options are stored as ``B. text``.

    Args:
        given: Extracted candidate answer.
        options: Stored option strings.

    Returns:
        Matching option text, or None when blank.
    """
    if given is None:
        return None
    if isinstance(given, (list, tuple)):
        given = given[0] if given else None
    if given is None:
        return None
    choice = str(given).strip()
    if not choice:
        return None
    if choice in options:
        return choice
    letter = choice.upper() if len(choice) == 1 else _option_letter(choice)
    if letter:
        for option in options:
            if option.strip().upper() == letter or _option_letter(option) == letter:
                return option
    return choice


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
    if given is None:
        return 0.0
    choice = resolve_choice(given, options)
    if choice is None:
        return 0.0
    if choice in options:
        return numeric_weights[options.index(choice)] / best
    return 0.0


def _mcq_credit(question: dict[str, Any], given: Any) -> float | None:
    correct_answer = question.get("correct_answer")
    if correct_answer is None:
        return None
    options = [str(o) for o in (question.get("options") or [])]
    expected = _normalize_answer_set(correct_answer)
    if options:
        resolved_expected: set[str] = set()
        for item in expected:
            matched = resolve_choice(item, options)
            resolved_expected.add(matched if matched is not None else item)
        expected = resolved_expected
        if isinstance(given, (list, tuple)):
            given = [resolve_choice(item, options) or item for item in given]
        else:
            given = resolve_choice(given, options)
    if not expected:
        return None
    return 1.0 if _normalize_answer_set(given) == expected else 0.0


def _likert_value(question: dict[str, Any], given: Any) -> float | None:
    """Resolve a Likert response to its scored option value.

    Prefers a stored option ``value``; a 1-based index is accepted for legacy
    responses that recorded the selected position instead of the point value.

    Args:
        question: Stored Likert question (``reverse_scored`` flag honoured).
        given: Candidate response — option value or 1-based index.

    Returns:
        The option value (recoded ``(min + max) - value`` when reverse scored),
        or None when the response is missing, non-integral, or unmatched.
    """
    if isinstance(given, (list, tuple)):
        given = given[0] if given else None
    if isinstance(given, bool):
        return None
    number = _parse_number(given)
    scale_min, scale_max = likert_scale_bounds(question)
    if number is None or not number.is_integer():
        return None
    selected = int(number)
    values = _likert_option_values(question)
    if values and selected in values:
        scored = selected
    elif values and LIKERT_MIN <= selected <= len(values):
        scored = values[selected - 1]
    elif not values and scale_min <= selected <= scale_max:
        scored = selected
    else:
        return None
    if question.get("reverse_scored"):
        scored = (scale_min + scale_max) - scored
    return float(scored)


@dataclass
class ScoreResult:
    """Aggregate result of scoring one assessment.

    Attributes:
        score: Percentage over gradable items, or None when nothing is gradable.
        facet_scores: ``{facet: {"mean": float, "n": int}}`` from Likert items.
        gradable_count: Number of items that contributed to ``score``.
        items_total: Recognized items in the bank.
        items_answered: Items with a usable response.
        unanswered_count: ``items_total - items_answered``.
        uniform_responding: True when ≥90% of ≥8 Likert answers share one value.
        sjt_points: Sum of chosen SJT weights.
        sjt_max: Sum of best SJT weights.
        crt_correct: Accepted CRT answers.
        crt_total: CRT items in the bank.
    """

    score: Optional[float]
    facet_scores: dict[str, dict[str, float | int]] = field(default_factory=dict)
    gradable_count: int = 0
    items_total: int = 0
    items_answered: int = 0
    unanswered_count: int = 0
    uniform_responding: bool = False
    sjt_points: float | None = None
    sjt_max: float | None = None
    crt_correct: int | None = None
    crt_total: int | None = None


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
    items_total = 0
    items_answered = 0
    likert_raw: list[float] = []
    sjt_points = 0.0
    sjt_max = 0.0
    sjt_items = 0
    crt_correct = 0
    crt_items = 0
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type", "")).lower()
        if qtype not in {"likert", "mcq", "sjt", "crt", "open", "open_ended"}:
            continue
        scored_type = qtype in {"likert", "mcq", "sjt", "crt"}
        if scored_type:
            items_total += 1
        given = resp_map.get(str(q.get("id")))

        if qtype == "likert":
            value = _likert_value(q, given)
            if value is None:
                continue
            items_answered += 1
            # Uniform-responding uses the selected index, not the reverse recode.
            selected = _parse_number(given if not isinstance(given, (list, tuple)) else (given[0] if given else None))
            if selected is not None:
                likert_raw.append(selected)
            facet = str(q.get("facet") or q.get("evaluated_competency") or "General").strip() or "General"
            facet_totals.setdefault(facet, []).append(value)
            continue

        blank = given is None or (
            isinstance(given, (list, tuple)) and not any(str(a).strip() for a in given)
        ) or (not isinstance(given, (list, tuple, dict)) and not str(given).strip())
        if qtype in {"mcq", "sjt", "crt"} and not blank:
            items_answered += 1

        if qtype == "mcq":
            credit = _mcq_credit(q, given)
        elif qtype == "sjt":
            credit = sjt_credit(q, given)
            weights = q.get("option_weights") or []
            options = [str(o) for o in (q.get("options") or [])]
            if options and len(weights) == len(options):
                try:
                    numeric_weights = [float(w) for w in weights]
                except (TypeError, ValueError):
                    numeric_weights = []
                if numeric_weights:
                    sjt_items += 1
                    sjt_max += max(numeric_weights)
                    if not blank and given is not None:
                        choice = resolve_choice(given, options)
                        if choice in options:
                            sjt_points += numeric_weights[options.index(choice)]
        elif qtype == "crt":
            credit = crt_credit(q, given)
            if credit is not None:
                crt_items += 1
                if credit >= 1.0:
                    crt_correct += 1
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
    uniform = False
    if len(likert_raw) >= 8:
        counts: dict[float, int] = {}
        for value in likert_raw:
            counts[value] = counts.get(value, 0) + 1
        uniform = max(counts.values()) / len(likert_raw) >= 0.9
    return ScoreResult(
        score=score,
        facet_scores=facet_scores,
        gradable_count=gradable,
        items_total=items_total,
        items_answered=items_answered,
        unanswered_count=max(0, items_total - items_answered),
        uniform_responding=uniform,
        sjt_points=sjt_points if sjt_items else None,
        sjt_max=sjt_max if sjt_items else None,
        crt_correct=crt_correct if crt_items else None,
        crt_total=crt_items if crt_items else None,
    )


def score_assessment(questions: Optional[list], responses: Iterable) -> Optional[float]:
    """Backward-compatible percentage score.

    Args:
        questions: Stored question bank.
        responses: Saved responses.

    Returns:
        Percentage over gradable items, or None.
    """
    return score_assessment_detailed(questions, responses).score
