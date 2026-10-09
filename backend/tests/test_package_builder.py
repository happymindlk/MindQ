"""Unit tests for package builder mapping (no live Gemini calls)."""
from __future__ import annotations

from app.schemas.package_builder import (
    AssessmentPackageBlueprint,
    DifficultyLevel,
    QuestionItem,
    QuestionType,
)
from app.services.package_generator import blueprint_question_to_storage


def test_mcq_maps_to_portal_shape():
    item = QuestionItem(
        prompt="Which HTTP status means created?",
        question_type=QuestionType.mcq,
        options=["200", "201", "204", "400"],
        correct_answer_or_rubric="201",
        evaluated_competency="HTTP fundamentals",
        weight=4,
    )
    stored = blueprint_question_to_storage(item, 0)
    assert stored["type"] == "mcq"
    assert stored["text"] == item.prompt
    assert stored["correct_answer"] == "201"
    assert stored["options"] == item.options
    assert stored["builder_type"] == "mcq"
    assert stored["id"].startswith("q-0-")


def test_open_ended_maps_to_open_with_rubric():
    item = QuestionItem(
        prompt="Describe how you would debug a production outage.",
        question_type=QuestionType.open_ended,
        options=[],
        correct_answer_or_rubric="Mentions triage, rollback, communication, RCA.",
        evaluated_competency="Incident response",
        weight=5,
    )
    stored = blueprint_question_to_storage(item, 2)
    assert stored["type"] == "open"
    assert stored["benchmark_rubric"].startswith("Mentions triage")
    assert "correct_answer" not in stored
    assert stored["builder_type"] == "open_ended"


def test_likert_maps_with_scale_labels():
    item = QuestionItem(
        prompt="I enjoy mentoring junior engineers.",
        question_type=QuestionType.likert,
        evaluated_competency="Mentorship",
        weight=2,
        likert_label_1="Never",
        likert_label_5="Always",
    )
    stored = blueprint_question_to_storage(item, 1)
    assert stored["type"] == "likert"
    assert stored["likert_label_1"] == "Never"
    assert stored["likert_label_5"] == "Always"
    assert stored["builder_type"] == "likert"


def test_blueprint_schema_roundtrip():
    blueprint = AssessmentPackageBlueprint(
        title="Backend Hire Pack",
        role="Backend Engineer",
        target_seniority=DifficultyLevel.senior,
        estimated_duration_minutes=45,
        competencies_targeted=["APIs", "SQL", "Ownership"],
        questions=[
            QuestionItem(
                prompt="Explain CAP trade-offs for your last system.",
                question_type=QuestionType.open_ended,
                correct_answer_or_rubric="Mentions consistency, availability, partition tolerance.",
                evaluated_competency="Distributed systems",
                weight=5,
            )
        ],
    )
    restored = AssessmentPackageBlueprint.model_validate_json(blueprint.model_dump_json())
    assert restored.target_seniority == DifficultyLevel.senior
    assert restored.questions[0].question_type == QuestionType.open_ended
