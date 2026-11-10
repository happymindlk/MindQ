"""Unit tests for the MindQReport-parity WeasyPrint view model."""
from __future__ import annotations

from app.services.report_view import build_report_view, visible_subscales


def test_visible_subscales_hides_duplicate_single_metric():
    assert visible_subscales(
        "Personal Initiative",
        [{"name": "Personal Initiative", "position_pct": 70}],
    ) == []


def test_build_report_view_groups_and_bars():
    view = build_report_view(
        {
            "candidate_full_name": "Pat Doe",
            "candidate_email": "pat@example.com",
            "target_role": "Engineer",
            "company_name": "Acme",
            "synthesis_status": "ok",
            "total_assessments_completed": 2,
            "executive_summary": "Solid.",
            "strengths": ["Fast math."],
            "areas_to_explore": ["Pace."],
            "competency_breakdown": [
                {
                    "category": "Personality",
                    "assessment_name": "Work Style",
                    "score": 64,
                    "performance_summary": "Steady.",
                },
                {
                    "category": "Cognitive",
                    "assessment_name": "Math",
                    "score": 80,
                    "performance_summary": "Strong.",
                    "subscales": [
                        {"name": "Numeracy", "position_pct": 82, "band_label": "High"}
                    ],
                },
            ],
            "category_summaries": [
                {"category": "Cognitive", "summary": "Strong pillar."},
                {"category": "Technical", "summary": "Must not appear."},
            ],
            "custom_questions": [
                {
                    "id": "q1",
                    "prompt": "Explain retries",
                    "score": 90,
                    "ai_evaluation": "Good.",
                    "ai_eval_status": "ok",
                    "scorecard": ["Mentions backoff"],
                }
            ],
        }
    )

    assert view["total_completed"] == 2
    assert [g["category"] for g in view["groups"]] == ["Cognitive", "Personality"]
    assert view["groups"][0]["summary"] == "Strong pillar."
    cognitive_row = view["groups"][0]["rows"][0]
    assert cognitive_row["bar_width"] == 80.0
    assert cognitive_row["value_label"] == "80%"
    assert cognitive_row["subscales"][0]["value_label"] == "82% · High"
    # Prose summary is suppressed when facet bars are present.
    assert cognitive_row["summary"] == ""
    assert view["groups"][1]["rows"][0]["summary"] == "Steady."
    assert view["customs"][0]["score_label"] == "90%"
    assert view["customs"][0]["show_fallback"] is False


def test_build_report_view_maps_likert_mean_to_subscale_bars():
    view = build_report_view(
        {
            "candidate_full_name": "Pat Doe",
            "candidate_email": "pat@example.com",
            "target_role": "Engineer",
            "company_name": "Happy Mind",
            "synthesis_status": "ok",
            "total_assessments_completed": 1,
            "executive_summary": "Solid.",
            "strengths": [],
            "areas_to_explore": [],
            "competency_breakdown": [
                {
                    "category": "Personality",
                    "assessment_name": "Mini-IPIP",
                    "score": 70,
                    "performance_summary": "Pat completed Mini-IPIP (Extraversion Average).",
                    "subscales": [
                        {"name": "Extraversion", "mean": 3.0, "band_label": "Average"},
                        {"name": "Agreeableness", "mean": 5.0, "band_label": "High"},
                    ],
                }
            ],
            "category_summaries": [],
            "custom_questions": [],
        }
    )
    facets = view["groups"][0]["rows"][0]["subscales"]
    assert facets[0]["bar_width"] == 50.0
    assert facets[0]["value_label"] == "50% · Average"
    assert facets[1]["bar_width"] == 100.0
    assert view["groups"][0]["rows"][0]["summary"] == ""
