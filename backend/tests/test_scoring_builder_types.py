"""Scoring branches for SJT, multi-key MCQ, CRT, and reverse-keyed Likert facets."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.scoring import score_assessment, score_assessment_detailed


def _resp(qid, answer):
    return SimpleNamespace(question_id=qid, response={"answer": answer})


SJT = {
    "id": "s1",
    "type": "sjt",
    "options": ["Escalate", "Help", "Ignore", "Blame"],
    "option_weights": [2, 3, 0, 1],
}


@pytest.mark.parametrize(
    "answer, expected",
    [("Help", 100.0), ("Escalate", 66.67), ("Blame", 33.33), ("Ignore", 0.0), ("Not an option", 0.0), (None, 0.0)],
)
def test_sjt_credit_is_weight_over_best(answer, expected):
    responses = [] if answer is None else [_resp("s1", answer)]
    assert score_assessment([SJT], responses) == expected


def test_sjt_with_misaligned_weights_is_not_gradable():
    broken = {**SJT, "option_weights": [3, 2]}
    assert score_assessment([broken], [_resp("s1", "Help")]) is None


MCQ_MULTI = {
    "id": "m1",
    "type": "mcq",
    "options": ["2", "4", "5"],
    "allow_multiple": True,
    "correct_answer": ["2", "5"],
}


@pytest.mark.parametrize(
    "answer, expected",
    [(["5", "2"], 100.0), (["2"], 0.0), (["2", "4", "5"], 0.0), ([], 0.0)],
)
def test_multi_key_mcq_requires_exact_set(answer, expected):
    assert score_assessment([MCQ_MULTI], [_resp("m1", answer)]) == expected


CRT_NUMERIC = {"id": "c1", "type": "crt", "accepted_answers": ["0.05", "5"], "match": "numeric"}
CRT_EXACT = {"id": "c2", "type": "crt", "accepted_answers": ["five cents"], "match": "exact"}


@pytest.mark.parametrize(
    "answer, expected",
    [
        ("5", 100.0),
        ("5.000", 100.0),
        (" .05 ", 100.0),
        ("$0.05", 100.0),
        ("5 cents", 100.0),
        ("five cents", 100.0),
        ("10", 0.0),
        ("ten", 0.0),
    ],
)
def test_crt_numeric_match(answer, expected):
    assert score_assessment([CRT_NUMERIC], [_resp("c1", answer)]) == expected


@pytest.mark.parametrize("answer, expected", [("Five  Cents", 100.0), ("five cent", 0.0), ("", 0.0)])
def test_crt_exact_match_is_case_and_whitespace_insensitive(answer, expected):
    assert score_assessment([CRT_EXACT], [_resp("c2", answer)]) == expected


CRT_PASTED_LIST = {
    "id": "c3",
    "type": "crt",
    "match": "exact",
    "accepted_answers": ['"5",   "5 cents",   "0.05",   ".05"'],
}


@pytest.mark.parametrize("answer, expected", [(".05", 100.0), ("5 cents", 100.0), ("5", 100.0), ("10 cents", 0.0)])
def test_crt_accepts_answers_pasted_as_one_quoted_list(answer, expected):
    assert score_assessment([CRT_PASTED_LIST], [_resp("c3", answer)]) == expected


def test_reverse_likert_recodes_and_aggregates_facets():
    questions = [
        {"id": "l1", "type": "likert", "facet": "Extraversion"},
        {"id": "l2", "type": "likert", "facet": "Extraversion", "reverse_scored": True},
        {"id": "l3", "type": "likert", "facet": "H:Sinc"},
        {"id": "l4", "type": "likert", "facet": "H:Sinc"},
    ]
    responses = [_resp("l1", 5), _resp("l2", 1), _resp("l3", 2), _resp("l4", "9")]
    result = score_assessment_detailed(questions, responses)
    assert result.facet_scores["Extraversion"] == {"mean": 5.0, "n": 2}
    assert result.facet_scores["H:Sinc"] == {"mean": 2.0, "n": 1}
    assert result.score is None
    assert result.gradable_count == 0


CUSTOM_LABELS = ["Never", "Rarely", "Sometimes", "Often", "Always"]


@pytest.mark.parametrize(
    "answer, reverse, expected",
    [(1, False, 1.0), (5, False, 5.0), ("3", False, 3.0), (1, True, 5.0), (2, True, 4.0), ("4", True, 2.0)],
)
def test_likert_scores_selected_index_regardless_of_labels(answer, reverse, expected):
    for labels in (None, CUSTOM_LABELS, list(reversed(CUSTOM_LABELS))):
        question = {"id": "l1", "type": "likert", "facet": "F", "reverse_scored": reverse}
        if labels is not None:
            question["scale_labels"] = labels
        result = score_assessment_detailed([question], [_resp("l1", answer)])
        assert result.facet_scores["F"] == {"mean": expected, "n": 1}


@pytest.mark.parametrize("answer", ["Always", "Very Accurate", 0, 6, 2.5, "3.5", True, None, []])
def test_likert_rejects_label_text_and_out_of_range_values(answer):
    question = {"id": "l1", "type": "likert", "facet": "F", "scale_labels": CUSTOM_LABELS}
    responses = [] if answer is None else [_resp("l1", answer)]
    assert score_assessment_detailed([question], responses).facet_scores == {}


def test_seven_point_likert_accepts_6_and_7_and_reverse_recode():
    question = {
        "id": "p1",
        "type": "likert",
        "facet": "Personal Initiative",
        "scale_points": 7,
        "scale_labels": ["1", "2", "3", "4", "5", "6", "7"],
    }
    result = score_assessment_detailed([question], [_resp("p1", 7)])
    assert result.facet_scores["Personal Initiative"] == {"mean": 7.0, "n": 1}
    reversed_item = {**question, "id": "p2", "reverse_scored": True}
    recoded = score_assessment_detailed([reversed_item], [_resp("p2", 7)])
    assert recoded.facet_scores["Personal Initiative"] == {"mean": 1.0, "n": 1}


def test_likert_scores_custom_option_values_and_dynamic_reverse():
    question = {
        "id": "l1",
        "type": "likert",
        "facet": "F",
        "scale_points": 5,
        "options": [
            {"label": "Never", "value": 0},
            {"label": "Rarely", "value": 25},
            {"label": "Sometimes", "value": 50},
            {"label": "Often", "value": 75},
            {"label": "Always", "value": 100},
        ],
    }
    result = score_assessment_detailed([question], [_resp("l1", 75)])
    assert result.facet_scores["F"] == {"mean": 75.0, "n": 1}
    indexed = score_assessment_detailed([question], [_resp("l1", 2)])
    assert indexed.facet_scores["F"] == {"mean": 25.0, "n": 1}
    reversed_item = {**question, "reverse_scored": True}
    recoded = score_assessment_detailed([reversed_item], [_resp("l1", 0)])
    assert recoded.facet_scores["F"] == {"mean": 100.0, "n": 1}


def test_mixed_bank_averages_only_gradable_items():
    questions = [SJT, MCQ_MULTI, CRT_NUMERIC, {"id": "o1", "type": "open"}]
    responses = [_resp("s1", "Help"), _resp("m1", ["2"]), _resp("c1", "5"), _resp("o1", "essay")]
    result = score_assessment_detailed(questions, responses)
    assert result.gradable_count == 3
    assert result.score == 66.67
