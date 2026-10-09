"""MindQ Report synthesis: categories, module scores, groups, narratives."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services.report_synthesis import (
    ModuleOutcome,
    build_competency_groups,
    build_completed_assessments,
    build_narrative,
    module_percentage,
    resolve_category,
    score_band,
)

DONE = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def _outcome(title: str, category: str, score: float | None) -> ModuleOutcome:
    return ModuleOutcome(
        id=uuid4(), title=title, category=category, score=score, completed_at=DONE  # type: ignore[arg-type]
    )


# --- resolve_category ---------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "catalog", "questions", "expected"),
    [
        ("technical", "cognitive", [], "technical"),
        (None, None, [{"type": "likert"}], "technical"),
        ("psychometric", "behavioral", [{"type": "likert"}], "behavioral"),
        ("psychometric", "PERSONALITY", [], "personality"),
        ("psychometric", None, [{"type": "likert"}, {"type": "mcq"}], "personality"),
        ("psychometric", None, [{"type": "sjt"}], "behavioral"),
        ("psychometric", None, [{"type": "crt"}], "cognitive"),
        ("psychometric", "bogus", None, "cognitive"),
        ("psychometric", None, ["not-a-dict", {"question_type": "sjt"}], "behavioral"),
    ],
)
def test_resolve_category(kind, catalog, questions, expected) -> None:
    assert resolve_category(kind, catalog, questions) == expected


# --- module_percentage --------------------------------------------------------


def test_module_percentage_prefers_stored_score() -> None:
    assert module_percentage(72.456, {"Openness": {"mean": 5, "n": 3}}) == 72.5


def test_module_percentage_maps_likert_means_weighted_by_n() -> None:
    facets = {"A": {"mean": 5.0, "n": 3}, "B": {"mean": 1.0, "n": 1}}
    # weighted mean = 4.0 → (4-1)/4 = 75%
    assert module_percentage(None, facets) == 75.0


@pytest.mark.parametrize(
    "facets",
    [None, {}, {"A": "x"}, {"A": {"mean": True}}, {"A": {"n": 3}}],
)
def test_module_percentage_unscorable(facets) -> None:
    assert module_percentage(None, facets) is None


def test_module_percentage_clamps_out_of_range_means() -> None:
    assert module_percentage(None, {"A": {"mean": 9, "n": 1}}) == 100.0
    assert module_percentage(None, {"A": {"mean": -2, "n": 0}}) == 0.0


# --- bands & narratives -------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "band"),
    [(100, "exceptional"), (80, "exceptional"), (79.9, "strong"), (65, "strong"),
     (50, "moderate"), (35, "developing"), (34.9, "emerging"), (0, "emerging")],
)
def test_score_band_boundaries(score, band) -> None:
    assert score_band(score) == band


def test_narrative_without_scores() -> None:
    text = build_narrative("personality", "Ada Lovelace", [_outcome("P", "personality", None)], None)
    assert text.startswith("Ada completed the personality assessments")


def test_narrative_highlights_spread() -> None:
    mods = [_outcome("Numerical", "cognitive", 90.0), _outcome("Verbal", "cognitive", 60.0)]
    text = build_narrative("cognitive", "Ada Lovelace", mods, 75.0)
    assert "average of 75% across 2 cognitive assessments" in text
    assert "strongest in Numerical (90%)" in text
    assert "lower in Verbal (60%)" in text


def test_narrative_consistent_results() -> None:
    mods = [_outcome("A", "behavioral", 70.0), _outcome("B", "behavioral", 75.0)]
    text = build_narrative("behavioral", "Ada", mods, 72.5)
    assert "consistent across modules" in text


def test_narrative_handles_blank_name() -> None:
    text = build_narrative("technical", "   ", [_outcome("T", "technical", 40.0)], 40.0)
    assert text.startswith("The candidate achieved an average of 40% across 1 technical assessment.")


def test_narrative_is_deterministic() -> None:
    mods = [_outcome("A", "cognitive", 55.0)]
    assert build_narrative("cognitive", "Ada", mods, 55.0) == build_narrative(
        "cognitive", "Ada", mods, 55.0
    )


# --- grouping -----------------------------------------------------------------


def test_groups_are_ordered_and_averaged() -> None:
    outcomes = [
        _outcome("Tech", "technical", 50.0),
        _outcome("Big Five", "personality", 62.5),
        _outcome("Logic", "cognitive", 80.0),
        _outcome("Numbers", "cognitive", 70.0),
        _outcome("Ungraded", "cognitive", None),
    ]
    groups = build_competency_groups("Ada", outcomes)
    assert [g.key for g in groups] == ["cognitive", "personality", "technical"]
    cognitive = groups[0]
    assert cognitive.label == "Cognitive"
    assert cognitive.average_score == 75.0
    assert [a.score for a in cognitive.assessments] == [80.0, 70.0, None]
    assert cognitive.narrative


def test_groups_empty_input() -> None:
    assert build_competency_groups("Ada", []) == []


def test_completed_assessments_carry_labels() -> None:
    rows = build_completed_assessments([_outcome("SJT", "behavioral", 60.0)])
    assert rows[0].category == "behavioral"
    assert rows[0].category_label == "Behavioral"
    assert rows[0].completed_at == DONE
