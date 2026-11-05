"""MindQ Report scoring: categories, module scores, averages, breakdown merge."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.schemas.jd_evaluation import (
    REPORT_NARRATIVE_JSON_SCHEMA,
    CategorySummary,
    CompetencyBreakdownItem,
    ReportNarrative,
    first_sentence,
)
from app.schemas.mindq_report import AssessmentBreakdownItem, MindQReport
from app.services.instrument_results import SCORING_VERSION
from app.services.report_synthesis import (
    ModuleOutcome,
    _score_details_need_refresh,
    build_category_summaries,
    build_competency_breakdown,
    build_module_outcomes,
    compute_category_averages,
    fallback_performance_summary,
    map_instrument_for_prompt,
    module_percentage,
    outcomes_fingerprint,
    performance_summaries,
    prompt_assessments,
    resolve_category,
    score_band,
)

DONE = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)

_BASE_NARRATIVE = {
    "headline": "Results align with the role's top priorities.",
    "key_takeaways": ["Takeaway one.", "Takeaway two.", "Takeaway three."],
    "executive_summary": "Summary.",
    "role_alignment": [],
    "strengths": ["Strength one.", "Strength two.", "Strength three."],
    "areas_to_explore": [
        "May prefer clearer guidance when priorities shift.",
        "May take longer to commit when information is incomplete.",
        "May benefit from confirming composure under change.",
    ],
    "work_environment_notes": [
        "May settle well with clear ownership.",
        "May prefer steady collaboration.",
    ],
    "interview_focus_areas": ["Priority handling.", "Analytical trade-offs.", "Team pace."],
    "verify_separately": [],
    "support_suggestions": [],
    "reliability_notes": [],
    "category_summaries": [],
    "competency_breakdown": [],
}


def _outcome(
    title: str,
    category: str,
    score: float | None,
    key: str = "A1",
    **kwargs,
) -> ModuleOutcome:
    return ModuleOutcome(
        key=key,
        id=uuid4(),
        title=title,
        category=category,  # type: ignore[arg-type]
        score=score,
        completed_at=DONE,
        **kwargs,
    )


def _synthesis(summaries: dict[str, str]) -> ReportNarrative:
    return ReportNarrative.model_validate(
        {
            **_BASE_NARRATIVE,
            "competency_breakdown": [
                {
                    "assessment_key": k,
                    "assessment_name": k,
                    "performance_summary": v,
                    "role_relevance": f"Relevant to the role for {k}.",
                }
                for k, v in summaries.items()
            ],
        }
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


def test_module_percentage_maps_seven_point_mean() -> None:
    questions = [{"type": "likert", "scale_points": 7}]
    assert module_percentage(None, {"PI": {"mean": 7.0, "n": 10}}, questions) == 100.0
    assert module_percentage(None, {"PI": {"mean": 4.0, "n": 10}}, questions) == 50.0


def test_module_percentage_uses_option_value_max() -> None:
    questions = [
        {
            "type": "likert",
            "options": [
                {"label": "a", "value": 0},
                {"label": "b", "value": 25},
                {"label": "c", "value": 50},
                {"label": "d", "value": 75},
                {"label": "e", "value": 100},
            ],
        }
    ]
    assert module_percentage(None, {"F": {"mean": 100.0, "n": 1}}, questions) == 100.0
    assert module_percentage(None, {"F": {"mean": 50.0, "n": 1}}, questions) == 50.0


# --- score_details refresh ----------------------------------------------------


def test_score_details_refresh_when_extraversion_missing() -> None:
    facets = {
        "Surgency or Extraversion": {"mean": 3.0, "n": 4},
        "Agreeableness": {"mean": 3.0, "n": 4},
        "Conscientiousness": {"mean": 3.0, "n": 4},
        "Neuroticism": {"mean": 3.0, "n": 4},
        "Intellect or Imagination": {"mean": 2.5, "n": 4},
    }
    stale = {
        "scoring_version": SCORING_VERSION,
        "instrument": "big_five",
        "subscales": [
            {"name": "Agreeableness", "mean": 3.0},
            {"name": "Conscientiousness", "mean": 3.0},
            {"name": "Emotional stability", "mean": 3.0},
            {"name": "Intellect or Imagination", "mean": 2.5},
        ],
    }
    assert _score_details_need_refresh(stale, facets) is True
    fresh = {
        "scoring_version": SCORING_VERSION,
        "instrument": "big_five",
        "subscales": [
            {"name": "Surgency or Extraversion", "mean": 3.0},
            {"name": "Agreeableness", "mean": 3.0},
            {"name": "Conscientiousness", "mean": 3.0},
            {"name": "Neuroticism", "mean": 3.0},
            {"name": "Intellect or Imagination", "mean": 2.5},
        ],
    }
    assert _score_details_need_refresh(fresh, facets) is False


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


def test_build_module_outcomes_masks_scores_until_package_complete() -> None:
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
    assert [(o.key, o.title, o.category, o.score, o.status) for o in outcomes] == [
        ("A1", "SQL", "technical", None, "COMPLETED"),
        ("A2", "Python", "technical", None, "IN_PROGRESS"),
        ("A3", "Big Five", "personality", None, "COMPLETED"),
    ]
    assert all(o.scores_released is False for o in outcomes)
    assert all(o.subscales == () for o in outcomes)


def test_build_module_outcomes_releases_scores_when_package_complete() -> None:
    done = _assessment("SQL")
    likert = _assessment(
        "Big Five",
        kind="psychometric",
        questions=[{"type": "likert", "facet": "O"}],
    )
    outcomes = build_module_outcomes(
        [done, likert],
        [
            _progress(done, score=62.5),
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
    assert all(o.scores_released for o in outcomes)


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


def _pillar_synthesis(summaries: dict[str, str]) -> ReportNarrative:
    return ReportNarrative.model_validate(
        {
            **_BASE_NARRATIVE,
            "category_summaries": [
                {"category": k, "summary": v} for k, v in summaries.items()
            ],
        }
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
    scored = _outcome("Logic", "cognitive", 80.0, key="A1", instrument="cognicheck")
    unscored = _outcome("Essay", "technical", None, key="A2")
    payload = prompt_assessments([scored, unscored])
    assert payload[0]["assessment_key"] == "A1"
    assert payload[0]["score"] == 80.0
    assert payload[0]["category"] == "Cognitive"
    assert payload[0]["instrument"] == "cognicheck"
    assert payload[0]["subscales"] == []
    assert "server_duration_seconds" not in payload[0]
    assert len(payload) == 1
    changed = _outcome("Logic", "cognitive", 81.0, key="A1")
    assert outcomes_fingerprint([scored]) != outcomes_fingerprint([changed])


def test_prompt_assessments_maps_instruments_and_strips_cognicheck_subscales() -> None:
    cognicheck = _outcome(
        "CogniCheck",
        "cognitive",
        72.0,
        key="A1",
        instrument="cognicheck",
        subscales=({"name": "verbal", "position_pct": 80.0},),
    )
    big_five = _outcome(
        "Big Five",
        "personality",
        None,
        key="A2",
        instrument="big_five",
        score_kind="traits",
        display_score="traits",
        subscales=({"name": "Extraversion", "position_pct": 60.0},),
        facet_means={"extraversion": {"mean": 3.5, "n": 4}},
    )
    rows = {row["assessment_key"]: row for row in prompt_assessments([cognicheck, big_five])}
    assert rows["A1"]["subscales"] == []
    assert rows["A1"]["instrument"] == "cognicheck"
    assert rows["A2"]["instrument"] == "mini_ipip"
    assert rows["A2"]["facet_means"]["extraversion"]["mean"] == 3.5
    assert map_instrument_for_prompt("hexaco", "personality") == "hexaco_hh"
    assert map_instrument_for_prompt("ipc", "personality") == "ipip_ipc"
    assert map_instrument_for_prompt("initiative", "behavioral") == "personal_initiative"


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
        CompetencyBreakdownItem(
            assessment_key="A1",
            assessment_name="X",
            performance_summary="   ",
            role_relevance="Relevant.",
        )


def test_synthesis_bullets_drop_blank_and_non_list_values() -> None:
    synthesis = ReportNarrative.model_validate(
        {
            **_BASE_NARRATIVE,
            "strengths": ["  a  b ", "", None, "c", "d"],
            "areas_to_explore": [
                "  may prefer clearer guidance  ",
                "",
                None,
                "May take longer to commit when information is incomplete.",
                "May benefit from confirming composure under change.",
            ],
        }
    )
    assert synthesis.strengths == ["a b", "c", "d"]
    assert synthesis.areas_to_explore == [
        "may prefer clearer guidance",
        "May take longer to commit when information is incomplete.",
        "May benefit from confirming composure under change.",
    ]
    with pytest.raises(ValueError):
        ReportNarrative.model_validate({**_BASE_NARRATIVE, "areas_to_explore": "x"})


def test_gemini_json_schema_matches_pydantic_model() -> None:
    schema_fields = set(REPORT_NARRATIVE_JSON_SCHEMA["properties"])
    assert schema_fields == set(ReportNarrative.model_fields)
    item_fields = set(
        REPORT_NARRATIVE_JSON_SCHEMA["properties"]["competency_breakdown"]["items"]["properties"]
    )
    assert item_fields == set(CompetencyBreakdownItem.model_fields)
    category_fields = set(
        REPORT_NARRATIVE_JSON_SCHEMA["properties"]["category_summaries"]["items"]["properties"]
    )
    assert category_fields == set(CategorySummary.model_fields)
    assert "overall_fit" not in schema_fields
    assert "hiring_recommendation" not in schema_fields
    assert "areas_to_explore" in schema_fields
    assert "risks_and_antipatterns" not in schema_fields


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
        "headline",
        "key_takeaways",
        "executive_summary",
        "role_alignment",
        "strengths",
        "areas_to_explore",
        "work_environment_notes",
        "interview_focus_areas",
        "verify_separately",
        "support_suggestions",
        "reliability_notes",
        "competency_breakdown",
        "category_summaries",
    } <= fields
    assert "risks_and_antipatterns" not in fields
    assert not any("fit" in f or "recommendation" in f for f in fields)
