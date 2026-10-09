"""Validation and storage round-trips for polymorphic builder payloads."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import settings
from app.schemas.library import TemplateQuestionCreate
from app.schemas.question_payload import (
    LIKERT_DEFAULT_LABELS,
    payload_from_storage,
    question_payload_adapter,
)

MEDIA_PATH = "/storage/v1/object/public/assessment-media/modules/m1/a.png"


@pytest.fixture(autouse=True)
def _supabase_host(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://proj.supabase.co")


def _sjt(weights=(3, 2, 1, 0), texts=("A", "B", "C", "D")):
    return {
        "type": "sjt",
        "prompt": "Scenario",
        "options": [{"text": t, "weight": w} for t, w in zip(texts, weights)],
    }


def test_sjt_round_trip_keeps_weights_aligned():
    payload = question_payload_adapter.validate_python(_sjt(weights=(1, 3, 0, 2)))
    stored = payload.to_storage()
    assert stored["options"] == ["A", "B", "C", "D"]
    assert stored["option_weights"] == [1, 3, 0, 2]
    rebuilt = payload_from_storage(stored)
    assert rebuilt is not None
    assert [o["weight"] for o in rebuilt["options"]] == [1, 3, 0, 2]


@pytest.mark.parametrize(
    "body, message",
    [
        (_sjt(weights=(0, 0, 0, 0)), "weight above 0"),
        (_sjt(weights=(3, 2, 1, 4)), "less than or equal to 3"),
        (_sjt(texts=("A", "a", "C", "D")), "unique"),
        ({**_sjt(), "options": _sjt()["options"][:3]}, "at least 4"),
    ],
)
def test_sjt_rejects_bad_weights_and_options(body, message):
    with pytest.raises(ValidationError, match=message):
        question_payload_adapter.validate_python(body)


def test_single_mcq_with_two_keys_is_rejected():
    with pytest.raises(ValidationError, match="exactly one correct key"):
        question_payload_adapter.validate_python(
            {"type": "mcq", "prompt": "Q", "mode": "single", "options": ["a", "b"], "correct_keys": [0, 1]}
        )


def test_mcq_key_out_of_range_is_rejected():
    with pytest.raises(ValidationError, match="existing options"):
        question_payload_adapter.validate_python(
            {"type": "mcq", "prompt": "Q", "options": ["a", "b"], "correct_keys": [5]}
        )


def test_multi_mcq_stores_sorted_keys_and_text_answers():
    payload = question_payload_adapter.validate_python(
        {"type": "mcq", "prompt": "Q", "mode": "multiple", "options": ["a", "b", "c"], "correct_keys": [2, 0, 2]}
    )
    stored = payload.to_storage()
    assert stored["correct_keys"] == [0, 2]
    assert stored["correct_answer"] == ["a", "c"]
    assert stored["allow_multiple"] is True


@pytest.mark.parametrize("answers", [[], ["", "   "]])
def test_crt_requires_a_non_blank_answer(answers):
    with pytest.raises(ValidationError, match="at least one accepted answer|at least 1"):
        question_payload_adapter.validate_python({"type": "crt", "prompt": "Q", "accepted_answers": answers})


def test_crt_splits_answers_pasted_as_one_quoted_list():
    payload = question_payload_adapter.validate_python(
        {"type": "crt", "prompt": "Q", "accepted_answers": ['"5",  "5 cents", ".05"', " 0.05 "]}
    )
    assert payload.to_storage()["accepted_answers"] == ["5", "5 cents", ".05", "0.05"]


@pytest.mark.parametrize("answer", ["five", "inf", "nan"])
def test_crt_numeric_rejects_non_finite(answer):
    with pytest.raises(ValidationError):
        question_payload_adapter.validate_python(
            {"type": "crt", "prompt": "Q", "accepted_answers": [answer], "match": "numeric"}
        )


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://evil.example.com" + MEDIA_PATH,
        "https://proj.supabase.co/storage/v1/object/public/other-bucket/a.png",
    ],
)
def test_media_url_must_be_project_assessment_media(url):
    with pytest.raises(ValidationError, match="media_url"):
        question_payload_adapter.validate_python(
            {"type": "likert", "prompt": "I like teams", "media_url": url}
        )


def test_media_url_accepts_project_bucket():
    payload = question_payload_adapter.validate_python(
        {"type": "likert", "prompt": "I like teams", "media_url": "https://proj.supabase.co" + MEDIA_PATH}
    )
    assert payload.to_storage()["media_url"].endswith("/a.png")


def test_unknown_fields_are_forbidden():
    with pytest.raises(ValidationError):
        question_payload_adapter.validate_python(
            {"type": "likert", "prompt": "Q", "is_correct": True}
        )


def test_template_question_create_requires_text_or_payload():
    with pytest.raises(ValidationError):
        TemplateQuestionCreate()
    assert TemplateQuestionCreate(payload={"type": "likert", "prompt": "Q"}).payload is not None


def test_legacy_rows_without_builder_type_return_none():
    assert payload_from_storage({"type": "ranking", "text": "Legacy"}) is None


def test_likert_defaults_to_ipip_accuracy_labels():
    stored = question_payload_adapter.validate_python({"type": "likert", "prompt": "Q"}).to_storage()
    assert stored["scale_labels"] == list(LIKERT_DEFAULT_LABELS)
    assert stored["likert_label_1"] == "Very Inaccurate"
    assert stored["likert_label_5"] == "Very Accurate"


def test_likert_custom_labels_round_trip_and_mirror_endpoints():
    labels = [" Never ", "Rarely", "Sometimes", "Often", "Always"]
    payload = question_payload_adapter.validate_python(
        {"type": "likert", "prompt": "Q", "scale_labels": labels, "reverse_scored": True}
    )
    stored = payload.to_storage()
    assert stored["scale_labels"] == ["Never", "Rarely", "Sometimes", "Often", "Always"]
    assert (stored["likert_label_1"], stored["likert_label_5"]) == ("Never", "Always")
    rebuilt = payload_from_storage(stored)
    assert rebuilt is not None
    assert rebuilt["scale_labels"] == stored["scale_labels"]
    assert rebuilt["reverse_scored"] is True
    assert question_payload_adapter.validate_python(rebuilt).to_storage() == stored


@pytest.mark.parametrize(
    "labels, message",
    [
        (["a", "b", "c", "d"], "at least 5"),
        (["a", "b", "c", "d", "e", "f"], "at most 5"),
        (["a", "b", " ", "d", "e"], "filled in"),
        (["a", "B", "b", "d", "e"], "unique"),
        (["a", "b", "c", "d", "x" * 65], "64 characters"),
    ],
)
def test_likert_rejects_invalid_label_sets(labels, message):
    with pytest.raises(ValidationError, match=message):
        question_payload_adapter.validate_python({"type": "likert", "prompt": "Q", "scale_labels": labels})


def test_likert_legacy_endpoint_input_is_folded_into_scale_labels():
    payload = question_payload_adapter.validate_python(
        {"type": "likert", "prompt": "Q", "likert_label_1": "Strongly Disagree", "likert_label_5": "Strongly Agree"}
    )
    assert payload.to_storage()["scale_labels"] == [
        "Strongly Disagree", "Disagree", "Neutral", "Agree", "Strongly Agree",
    ]


def test_likert_legacy_storage_without_scale_labels_rebuilds_full_set():
    rebuilt = payload_from_storage(
        {"builder_type": "likert", "type": "likert", "text": "Q", "likert_label_1": "Low", "likert_label_5": "High"}
    )
    assert rebuilt is not None
    assert rebuilt["scale_labels"] == ["Low", *LIKERT_DEFAULT_LABELS[1:4], "High"]


def test_open_ended_round_trip_maps_rubric():
    payload = question_payload_adapter.validate_python(
        {"type": "open_ended", "prompt": "Explain joins", "rubric": "Mentions inner/outer"}
    )
    stored = payload.to_storage()
    assert stored["type"] == "open"
    assert stored["benchmark_rubric"] == "Mentions inner/outer"
    rebuilt = payload_from_storage(stored)
    assert rebuilt is not None and rebuilt["rubric"] == "Mentions inner/outer"
