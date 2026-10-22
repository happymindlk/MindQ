"""Gemini structured output for the MindQ Report synthesis. Isolated from HTTP schemas.

Gemini writes prose only. Scores, categories, and averages are computed
server-side and never round-trip through the model, so a hallucinated number
can never reach a report.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

_SENTENCE_END = (".", "!", "?")


def first_sentence(text: str) -> str:
    """Collapse model prose to exactly one sentence.

    Args:
        text: Raw model text.

    Returns:
        The first sentence, whitespace-normalized and terminated with a period
        when the model omitted punctuation. Empty input returns "".
    """
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    for index, char in enumerate(cleaned):
        if char not in _SENTENCE_END:
            continue
        following = cleaned[index + 1 : index + 3]
        # "3.5" and "e.g. the" are not boundaries; ". The" / ". 80%" are.
        if following == "":
            return cleaned[: index + 1]
        if following[0] == " " and len(following) == 2 and (
            following[1].isupper() or following[1].isdigit()
        ):
            return cleaned[: index + 1]
    return cleaned if cleaned.endswith(_SENTENCE_END) else f"{cleaned}."


class AssessmentNarrative(BaseModel):
    """Gemini's one-sentence read of a single completed assessment."""

    assessment_key: str = Field(min_length=1)
    assessment_name: str
    performance_summary: str = Field(min_length=1)

    @field_validator("performance_summary", mode="after")
    @classmethod
    def enforce_single_sentence(cls, value: str) -> str:
        sentence = first_sentence(value)
        if not sentence:
            raise ValueError("performance_summary must contain a sentence")
        return sentence


PsychometricCategory = Literal["Cognitive", "Personality", "Behavioral"]


class CategoryNarrative(BaseModel):
    """Gemini's holistic summary for one psychometric pillar.

    Technical is excluded: it is reported separately and never carries a
    pillar summary. Prose only — the category average shown beside it is
    computed server-side.
    """

    category: PsychometricCategory
    summary: str = Field(min_length=1)

    @field_validator("summary", mode="after")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            raise ValueError("summary must not be blank")
        return cleaned


class ReportSynthesis(BaseModel):
    """Narrative fields of the MindQ Report produced by Gemini.

    Deliberately has no fit score or hiring recommendation: MindQ does not make
    employment decisions, and the report disclaimer says so.
    """

    executive_summary: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    risks_and_antipatterns: list[str] = Field(default_factory=list)
    competency_breakdown: list[AssessmentNarrative] = Field(default_factory=list)
    # Default empty so payloads cached under older prompt versions still validate.
    category_summaries: list[CategoryNarrative] = Field(default_factory=list)

    @field_validator("strengths", "risks_and_antipatterns", mode="before")
    @classmethod
    def clean_bullets(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [" ".join(str(item).split()) for item in value if str(item or "").strip()]

    def summaries_by_key(self) -> dict[str, str]:
        """Map ``assessment_key`` → sentence (first occurrence wins).

        Returns:
            Lookup used to merge Gemini prose onto server-computed scores.
        """
        out: dict[str, str] = {}
        for item in self.competency_breakdown:
            out.setdefault(item.assessment_key.strip(), item.performance_summary)
        return out

    def summaries_by_category(self) -> dict[str, str]:
        """Map psychometric category → pillar summary (first occurrence wins).

        Returns:
            Lookup used to merge Gemini prose onto server-computed pillars.
        """
        out: dict[str, str] = {}
        for item in self.category_summaries:
            out.setdefault(item.category, item.summary)
        return out


# Hand-written JSON Schema for Gemini (no additionalProperties / $defs).
REPORT_SYNTHESIS_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "risks_and_antipatterns": {"type": "array", "items": {"type": "string"}},
        "competency_breakdown": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "assessment_key": {"type": "string"},
                    "assessment_name": {"type": "string"},
                    "performance_summary": {"type": "string"},
                },
                "required": ["assessment_key", "assessment_name", "performance_summary"],
            },
        },
        "category_summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["Cognitive", "Personality", "Behavioral"],
                    },
                    "summary": {"type": "string"},
                },
                "required": ["category", "summary"],
            },
        },
    },
    "required": [
        "executive_summary",
        "strengths",
        "risks_and_antipatterns",
        "competency_breakdown",
        "category_summaries",
    ],
}
