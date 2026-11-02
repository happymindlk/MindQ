"""Scoring Spec v2 golden cases: bands, Big Five flip, SJT points, CRT formats."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.instrument_results import (
    SCORING_VERSION,
    big_five_subscales,
    build_score_details,
    ipc_intensity,
    sjt_band,
)
from app.services.profiles.ipip_ipc import IpipIpcResolver
from app.services.profiles.base import ProfileInputs
from app.services.scoring import score_assessment_detailed


def _resp(qid, answer):
    return SimpleNamespace(question_id=qid, response={"answer": answer})


def test_all_threes_big_five_are_moderate_fifty():
    facets = {
        "Extraversion": {"mean": 3.0, "n": 4},
        "Agreeableness": {"mean": 3.0, "n": 4},
        "Conscientiousness": {"mean": 3.0, "n": 4},
        "Neuroticism": {"mean": 3.0, "n": 4},
        "Intellect": {"mean": 3.0, "n": 4},
    }
    rows = big_five_subscales(facets)
    assert [r["name"] for r in rows] == [
        "Surgency or Extraversion",
        "Agreeableness",
        "Conscientiousness",
        "Neuroticism",
        "Intellect or Imagination",
    ]
    assert all(r["position_pct"] == 50.0 and r["band"] == "moderate" for r in rows)


def test_letter_i_maps_to_intellect_or_imagination():
    rows = big_five_subscales({"I": {"mean": 4.0, "n": 4}, "E": {"mean": 2.0, "n": 4}})
    assert [r["name"] for r in rows] == [
        "Surgency or Extraversion",
        "Intellect or Imagination",
    ]


def test_neuroticism_four_stays_neuroticism_high():
    rows = big_five_subscales({"Neuroticism": {"mean": 4.0, "n": 4}})
    assert rows == [
        {
            "name": "Neuroticism",
            "mean": 4.0,
            "position_pct": 75.0,
            "band": "high",
            "band_label": "High",
        }
    ]


def test_sjt_twenty_and_nineteen_point_bands():
    assert sjt_band(20, 24) == "consistently_strong"
    assert sjt_band(19, 24) == "generally_sound"
    questions = [
        {
            "id": f"s{i}",
            "type": "sjt",
            "options": ["A", "B", "C", "D"],
            "option_weights": [3, 2, 1, 0],
        }
        for i in range(8)
    ]
    # 6 best (18) + 2 second-best (4) = 22; use 4 best + 4 second = 12+8=20
    answers = [_resp(f"s{i}", "A" if i < 4 else "B") for i in range(8)]
    twenty = score_assessment_detailed(questions, answers)
    assert twenty.sjt_points == 20
    assert twenty.score == 83.33
    details = build_score_details(questions=questions, result=twenty)
    assert details["band"] == "consistently_strong"
    nineteen = score_assessment_detailed(
        questions, [_resp(f"s{i}", "A" if i < 3 else "B") for i in range(8)]
    )
    # 3*3 + 5*2 = 9+10 = 19
    assert nineteen.sjt_points == 19
    assert build_score_details(questions=questions, result=nineteen)["band"] == "generally_sound"


def test_ipc_r_below_threshold_is_undifferentiated():
    assert ipc_intensity(0.25) == "undifferentiated"
    facets = {code: {"mean": 3.0, "n": 4} for code in ("PA", "BC", "DE", "FG", "HI", "JK", "LM", "NO")}
    facets["LM"] = {"mean": 3.25, "n": 4}
    profile = IpipIpcResolver().resolve(ProfileInputs(facet_scores=facets))
    assert profile.data["vector_length"] == 0.25
    assert profile.data["intensity"] == "undifferentiated"
    assert profile.data["display_name"] == "undifferentiated"


def test_crt_dollar_five_cents_is_correct():
    question = {"id": "c1", "type": "crt", "accepted_answers": ["0.05", "5"], "match": "numeric"}
    result = score_assessment_detailed([question], [_resp("c1", "$0.05")])
    assert result.score == 100.0
    assert result.crt_correct == 1


def test_score_details_carry_scoring_version():
    result = score_assessment_detailed(
        [{"id": "m1", "type": "mcq", "correct_answer": "A"}],
        [_resp("m1", "A")],
    )
    details = build_score_details(questions=[{"id": "m1", "type": "mcq"}], result=result, category="cognitive")
    assert details["scoring_version"] == SCORING_VERSION
    assert details["norm_referenced"] is False
    assert details["instrument"] == "cognicheck"
