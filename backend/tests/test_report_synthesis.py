"""MindQ Report scoring: categories, module scores, averages, breakdown merge."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.jd_evaluation import (
    REPORT_SYNTHESIS_JSON_SCHEMA,
    AssessmentNarrative,
    CategoryNarrative,
    ReportSynthesis,
    first_sentence,
)
from app.schemas.mindq_report import AssessmentBreakdownItem, MindQReport
from app.services.report_synthesis import (
    ModuleOutcome,
    build_category_summaries,
    build_competency_breakdown,
    build_module_outcomes,
    compute_category_averages,
    fallback_performance_summary,
    module_percentage,
    outcomes_fingerprint,
    performance_summaries,
    prompt_assessments,
    resolve_category,
    score_band,
)

DONE = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def _outcome(title: str, category: str, score: float | None, key: str = "A1") -> ModuleOutcome:
    return ModuleOutcome(
        key=key, id=uuid4(), title=title, category=category, score=score, completed_at=DONE  # type: ignore[arg-type]
    )


def _synthesis(summaries: dict[str, str]) -> ReportSynthesis:
    return ReportSynthesis(
        executive_summary="Summary.",
        competency_breakdown=[
            AssessmentNarrative(assessment_key=k, assessment_name=k, performance_summary=v)
            for k, v in summaries.items()
        ],
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


# --- build_module_outcomes ----------------------------------------------------


def _assessment(title: str, kind: str = "technical", questions=None, global_module_id=None):
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        module_kind=kind,
        questions=questions or [],
        global_module_id=global_module_id,
    )


def _progress(assessment, status="COMPLETED", score=None, facet_scores=None):
    return SimpleNamespace(
        assessment_id=assessment.id,
        status=status,
        score=score,
        facet_scores=facet_scores,
        completed_at=DONE,
    )


def test_build_module_outcomes_keeps_only_completed_and_keys_sequentially() -> None:
    done = _assessment("SQL")
    pending = _assessment("Python")
    likert = _assessment("Big Five", kind="psychometric", questions=[{"type": "likert"}])
    outcomes = build_module_outcomes(
        [done, pending, likert],
        [
            _progress(done, score=62.5),
            _progress(pending, status="IN_PROGRESS", score=90),
            _progress(likert, facet_scores={"O": {"mean": 3.0, "n": 2}}),
        ],
        [],
        {},
    )
    assert [(o.key, o.title, o.category, o.score) for o in outcomes] == [
        ("A1", "SQL", "technical", 62.5),
        ("A2", "Big Five", "personality", None),
    ]
    assert outcomes[1].score_kind == "traits"


def test_build_module_outcomes_uses_catalog_category() -> None:
    gm = uuid4()
    sjt = _assessment("Judgment", kind="psychometric", questions=[{"type": "likert"}], global_module_id=gm)
    outcomes = build_module_outcomes([sjt], [_progress(sjt, score=70)], [], {gm: "behavioral"})
    assert outcomes[0].category == "behavioral"


def test_build_module_outcomes_falls_back_to_graded_open_items() -> None:
    open_tech = _assessment("Design", questions=[{"id": "q1", "type": "open"}, {"id": "q2", "type": "open"}])
    responses = [
        SimpleNamespace(assessment_id=open_tech.id, question_id="q1", response={"ai_score": 80}),
        SimpleNamespace(assessment_id=open_tech.id, question_id="q2", response={"ai_score": 60}),
    ]
    outcomes = build_module_outcomes([open_tech], [_progress(open_tech)], responses, {})
    assert outcomes[0].score == 70.0


# --- compute_category_averages ------------------------------------------------


def test_category_averages_are_always_null() -> None:
    outcomes = [
        _outcome("Logic", "cognitive", 80.0),
        _outcome("Numbers", "cognitive", 70.0),
        _outcome("Big Five", "personality", 62.5),
    ]
    assert compute_category_averages(outcomes) is None
    assert compute_category_averages([]) is None


# --- bands, sentences, breakdown ---------------------------------------------


@pytest.mark.parametrize(
    ("score", "band"),
    [(100, "very_high"), (80, "very_high"), (79.9, "high"), (60, "high"),
     (59.9, "moderate"), (40, "moderate"), (39.9, "low"), (20, "low"),
     (19.9, "very_low"), (0, "very_low")],
)
def test_score_band_boundaries(score, band) -> None:
    assert score_band(score) == band


def test_fallback_summary_is_one_sentence_and_handles_blank_name() -> None:
    text = fallback_performance_summary("   ", _outcome("SQL", "technical", 40.0))
    assert text.startswith("The candidate scored 40% on SQL")
    assert first_sentence(text) == text


def test_performance_summaries_prefer_gemini_and_fallback_per_missing_key() -> None:
    a1 = _outcome("Logic", "cognitive", 85.0, key="A1")
    a2 = _outcome("SQL", "technical", 30.0, key="A2")
    summaries = performance_summaries("Ada Lovelace", [a1, a2], _synthesis({"A1": "Gemini line."}))
    assert summaries[a1.id] == "Gemini line."
    assert summaries[a2.id].startswith("Ada scored 30% on SQL")


def test_performance_summaries_without_synthesis_use_fallbacks() -> None:
    a1 = _outcome("Logic", "cognitive", 85.0)
    summaries = performance_summaries("Ada", [a1], None)
    assert "very high" in summaries[a1.id]


def test_performance_summaries_ignore_hallucinated_keys() -> None:
    a1 = _outcome("Logic", "cognitive", 85.0, key="A1")
    summaries = performance_summaries("Ada", [a1], _synthesis({"A9": "Invented."}))
    assert summaries[a1.id] != "Invented."


def test_breakdown_orders_by_category_and_skips_unscored() -> None:
    tech = _outcome("SQL", "technical", 50.0, key="A1")
    cog = _outcome("Logic", "cognitive", 80.0, key="A2")
    ungraded = _outcome("Essay", "technical", None, key="A3")
    outcomes = [tech, cog, ungraded]
    rows = build_competency_breakdown(outcomes, performance_summaries("Ada", outcomes, None))
    assert [(r.category, r.assessment_name, r.score) for r in rows] == [
        ("Cognitive", "Logic", 80.0),
        ("Technical", "SQL", 50.0),
    ]


def test_breakdown_scores_come_from_server_not_model() -> None:
    cog = _outcome("Logic", "cognitive", 42.0, key="A1")
    synthesis = _synthesis({"A1": "Scored 99% which is outstanding."})
    rows = build_competency_breakdown([cog], performance_summaries("Ada", [cog], synthesis))
    assert rows[0].score == 42.0


def test_duplicate_titles_keep_distinct_summaries() -> None:
    a1 = _outcome("Logic", "cognitive", 80.0, key="A1")
    a2 = _outcome("Logic", "cognitive", 40.0, key="A2")
    synthesis = _synthesis({"A1": "First.", "A2": "Second."})
    rows = build_competency_breakdown([a1, a2], performance_summaries("Ada", [a1, a2], synthesis))
    assert [r.performance_summary for r in rows] == ["First.", "Second."]


def _pillar_synthesis(summaries: dict[str, str]) -> ReportSynthesis:
    return ReportSynthesis(
        executive_summary="Summary.",
        category_summaries=[
            CategoryNarrative(category=k, summary=v) for k, v in summaries.items()  # type: ignore[arg-type]
        ],
    )


def test_build_category_summaries_orders_pillars_and_excludes_technical() -> None:
    outcomes = [
        _outcome("Scenarios", "behavioral", 60.0, key="A1"),
        _outcome("SQL", "technical", 90.0, key="A2"),
        _outcome("Logic", "cognitive", 80.0, key="A3"),
        _outcome("Big Five", "personality", 70.0, key="A4"),
    ]
    synthesis = _pillar_synthesis(
        {"Behavioral": "Sound judgement.", "Cognitive": "Sharp reasoning.", "Personality": "Steady style."}
    )
    result = build_category_summaries("Ada", outcomes, synthesis)
    assert [(s.category, s.summary) for s in result] == [
        ("Cognitive", "Sharp reasoning."),
        ("Personality", "Steady style."),
        ("Behavioral", "Sound judgement."),
    ]


def test_build_category_summaries_falls_back_and_omits_unscored_pillars() -> None:
    outcomes = [
        _outcome("Logic", "cognitive", 80.0, key="A1"),
        _outcome("Verbal", "cognitive", 60.0, key="A2"),
        _outcome("Big Five", "personality", None, key="A3"),
    ]
    result = build_category_summaries("Ada Lovelace", outcomes, None)
    assert len(result) == 1
    assert result[0].category == "Cognitive"
    assert "averaged 70%" not in result[0].summary
    assert "Logic, Verbal" in result[0].summary


def test_build_category_summaries_ignores_technical_prose() -> None:
    outcomes = [_outcome("SQL", "technical", 90.0, key="A1")]
    assert build_category_summaries("Ada", outcomes, _pillar_synthesis({})) == []


def test_prompt_assessments_and_fingerprint() -> None:
    scored = _outcome("Logic", "cognitive", 80.0, key="A1")
    unscored = _outcome("Essay", "technical", None, key="A2")
    payload = prompt_assessments([scored, unscored])
    assert payload[0]["assessment_key"] == "A1"
    assert payload[0]["score"] == 80.0
    assert payload[0]["category"] == "Cognitive"
    assert len(payload) == 1
    changed = _outcome("Logic", "cognitive", 81.0, key="A1")
    assert outcomes_fingerprint([scored]) != outcomes_fingerprint([changed])


# --- schemas ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Scored 80%. Great work.", "Scored 80%."),
        ("Scored 3.55 overall. Next", "Scored 3.55 overall."),
        ("Scored 80. 90 next time.", "Scored 80."),
        ("Strong result, e.g. on logic items", "Strong result, e.g. on logic items."),
        ("  Multi\nline   text!  More", "Multi line text!"),
        ("", ""),
        ("Done?", "Done?"),
    ],
)
def test_first_sentence(raw, expected) -> None:
    assert first_sentence(raw) == expected


def test_assessment_narrative_rejects_blank_summary() -> None:
    with pytest.raises(ValueError):
        AssessmentNarrative(assessment_key="A1", assessment_name="X", performance_summary="   ")


def test_synthesis_bullets_drop_blank_and_non_list_values() -> None:
    synthesis = ReportSynthesis.model_validate(
        {"executive_summary": "S.", "strengths": ["  a  b ", "", None], "risks_and_antipatterns": "x"}
    )
    assert synthesis.strengths == ["a b"]
    assert synthesis.risks_and_antipatterns == []


def test_gemini_json_schema_matches_pydantic_model() -> None:
    schema_fields = set(REPORT_SYNTHESIS_JSON_SCHEMA["properties"])
    assert schema_fields == set(ReportSynthesis.model_fields)
    item_fields = set(
        REPORT_SYNTHESIS_JSON_SCHEMA["properties"]["competency_breakdown"]["items"]["properties"]
    )
    assert item_fields == set(AssessmentNarrative.model_fields)
    category_fields = set(
        REPORT_SYNTHESIS_JSON_SCHEMA["properties"]["category_summaries"]["items"]["properties"]
    )
    assert category_fields == set(CategoryNarrative.model_fields)
    assert "overall_fit" not in schema_fields
    assert "hiring_recommendation" not in schema_fields


def test_breakdown_item_rejects_unknown_category_and_out_of_range_score() -> None:
    with pytest.raises(ValueError):
        AssessmentBreakdownItem(category="Emotional", assessment_name="X", score=50, performance_summary="S.")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AssessmentBreakdownItem(category="Technical", assessment_name="X", score=101, performance_summary="S.")


def test_mindq_report_has_no_fit_or_recommendation_fields() -> None:
    fields = set(MindQReport.model_fields)
    assert {
        "candidate_full_name",
        "candidate_email",
        "target_role",
        "total_assessments_completed",
        "category_averages",
        "executive_summary",
        "strengths",
        "risks_and_antipatterns",
        "competency_breakdown",
        "category_summaries",
    } <= fields
    assert not any("fit" in f or "recommendation" in f for f in fields)
