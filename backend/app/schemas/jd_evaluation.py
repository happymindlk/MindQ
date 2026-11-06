"""Gemini structured output for the MindQ Report synthesis. Isolated from HTTP schemas.

Gemini writes prose only. Scores, categories, and averages are computed
server-side and never round-trip through the model, so a hallucinated number
can never reach a report.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

_SENTENCE_END = (".", "!", "?")
# Lightweight article cleanup for Gemini slips like "a inclination".
_ARTICLE_A_BEFORE_VOWEL = re.compile(r"\ba ([aeiouAEIOU]\w+)\b")

Alignment = Literal[
    "results_strongly_align",
    "results_partly_align",
    "results_show_less_alignment",
    "not_assessed",
]
Confidence = Literal["high", "moderate", "low"]
Importance = Literal["critical", "important", "helpful"]
Category = Literal["Cognitive", "Personality", "Behavioral"]
# Alias kept for callers that still import the older name.
PsychometricCategory = Category
CapabilityKey = Literal[
    "cap_analytical",
    "cap_judgment",
    "cap_initiative",
    "cap_collaboration",
    "cap_influence",
    "cap_relationships",
    "cap_organisation",
    "cap_composure",
    "cap_curiosity",
    "cap_integrity",
]

ALIGNMENT_LABELS: dict[Alignment, str] = {
    "results_strongly_align": "Results strongly align",
    "results_partly_align": "Results partly align",
    "results_show_less_alignment": "Results show less alignment",
    "not_assessed": "Not assessed",
}

CAPABILITY_KEYS: frozenset[str] = frozenset(
    {
        "cap_analytical",
        "cap_judgment",
        "cap_initiative",
        "cap_collaboration",
        "cap_influence",
        "cap_relationships",
        "cap_organisation",
        "cap_composure",
        "cap_curiosity",
        "cap_integrity",
    }
)


def fix_indefinite_articles(text: str) -> str:
    """Correct ``a`` → ``an`` before vowel-initial words.

    Args:
        text: Prose that may contain article mismatches from the LLM.

    Returns:
        Text with lightweight article corrections applied.
    """
    return _ARTICLE_A_BEFORE_VOWEL.sub(r"an \1", text)


def first_sentence(text: str) -> str:
    """Collapse model prose to exactly one sentence.

    Args:
        text: Raw model text.

    Returns:
        The first sentence, whitespace-normalized and terminated with a period
        when the model omitted punctuation. Empty input returns "".
    """
    cleaned = fix_indefinite_articles(" ".join(str(text or "").split()))
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


def _clean_bullet_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        fix_indefinite_articles(" ".join(str(item).split()))
        for item in value
        if str(item or "").strip()
    ]


class SubscaleNote(BaseModel):
    """One Gemini note for a trait or facet under an assessment."""

    subscale_key: str
    note: str = Field(description="One sentence, plain language, tied to the job.")


class CompetencyBreakdownItem(BaseModel):
    """Gemini's narrative for one completed assessment."""

    assessment_key: str = Field(min_length=1)
    assessment_name: str
    performance_summary: str = Field(
        min_length=1, description="One sentence, no line breaks or lists."
    )
    role_relevance: str = Field(
        min_length=1, description="One sentence linking the result to this job."
    )
    subscale_notes: list[SubscaleNote] = Field(default_factory=list)

    @field_validator("performance_summary", mode="after")
    @classmethod
    def enforce_single_sentence(cls, value: str) -> str:
        sentence = first_sentence(value)
        if not sentence:
            raise ValueError("performance_summary must contain a sentence")
        return sentence

    @field_validator("role_relevance", mode="after")
    @classmethod
    def normalize_role_relevance(cls, value: str) -> str:
        cleaned = fix_indefinite_articles(" ".join(str(value or "").split()))
        if not cleaned:
            raise ValueError("role_relevance must not be blank")
        return cleaned


# Back-compat name used by older tests / imports during migration.
AssessmentNarrative = CompetencyBreakdownItem


class CategorySummary(BaseModel):
    """Gemini's holistic summary for one psychometric pillar.

    Technical is excluded: it is reported separately and never carries a
    pillar summary. Prose only — the category average shown beside it is
    computed server-side.
    """

    category: Category
    summary: str = Field(min_length=1, description="2-3 sentences.")

    @field_validator("summary", mode="after")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        cleaned = fix_indefinite_articles(" ".join(str(value or "").split()))
        if not cleaned:
            raise ValueError("summary must not be blank")
        return cleaned


CategoryNarrative = CategorySummary


class RoleAlignmentItem(BaseModel):
    """How assessment results align with one job capability priority."""

    capability_key: CapabilityKey
    capability_label: str
    importance: Importance
    alignment: Alignment
    confidence: Confidence
    evidence: str = Field(
        description="1-2 sentences naming the assessments and what they suggest."
    )


class ReportNarrative(BaseModel):
    """Narrative fields of the MindQ Report produced by Gemini (v5).

    Deliberately has no fit score or hiring recommendation: MindQ does not make
    employment decisions, and the report disclaimer says so.
    """

    headline: str = Field(min_length=1)
    key_takeaways: list[str] = Field(min_length=3, max_length=3)
    executive_summary: str = Field(min_length=1)
    role_alignment: list[RoleAlignmentItem] = Field(default_factory=list)
    competency_breakdown: list[CompetencyBreakdownItem] = Field(default_factory=list)
    category_summaries: list[CategorySummary] = Field(default_factory=list)
    strengths: list[str] = Field(min_length=3, max_length=6)
    areas_to_explore: list[str] = Field(min_length=3, max_length=6)
    work_environment_notes: list[str] = Field(min_length=2, max_length=4)
    interview_focus_areas: list[str] = Field(min_length=3, max_length=5)
    verify_separately: list[str] = Field(default_factory=list)
    support_suggestions: list[str] = Field(default_factory=list, max_length=3)
    reliability_notes: list[str] = Field(default_factory=list)

    @field_validator(
        "key_takeaways",
        "strengths",
        "areas_to_explore",
        "work_environment_notes",
        "interview_focus_areas",
        "verify_separately",
        "support_suggestions",
        "reliability_notes",
        mode="before",
    )
    @classmethod
    def clean_bullets(cls, value: Any) -> list[str]:
        return _clean_bullet_list(value)

    @field_validator("headline", "executive_summary", mode="after")
    @classmethod
    def normalize_prose(cls, value: str) -> str:
        cleaned = fix_indefinite_articles(" ".join(str(value or "").split()))
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned

    def summaries_by_key(self) -> dict[str, str]:
        """Map ``assessment_key`` → sentence (first occurrence wins).

        Returns:
            Lookup used to merge Gemini prose onto server-computed scores.
        """
        out: dict[str, str] = {}
        for item in self.competency_breakdown:
            out.setdefault(item.assessment_key.strip(), item.performance_summary)
        return out

    def narratives_by_key(self) -> dict[str, CompetencyBreakdownItem]:
        """Map ``assessment_key`` → full breakdown item (first occurrence wins).

        Returns:
            Lookup used to merge role_relevance and subscale_notes onto scores.
        """
        out: dict[str, CompetencyBreakdownItem] = {}
        for item in self.competency_breakdown:
            out.setdefault(item.assessment_key.strip(), item)
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


# Temporary alias while call sites migrate to ReportNarrative.
ReportSynthesis = ReportNarrative


# Hand-written JSON Schema for Gemini (no additionalProperties / $defs).
# Array minItems/maxItems omitted — enforced by Pydantic after parse.
REPORT_NARRATIVE_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "key_takeaways": {"type": "array", "items": {"type": "string"}},
        "executive_summary": {"type": "string"},
        "role_alignment": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "capability_key": {
                        "type": "string",
                        "enum": sorted(CAPABILITY_KEYS),
                    },
                    "capability_label": {"type": "string"},
                    "importance": {
                        "type": "string",
                        "enum": ["critical", "important", "helpful"],
                    },
                    "alignment": {
                        "type": "string",
                        "enum": [
                            "results_strongly_align",
                            "results_partly_align",
                            "results_show_less_alignment",
                            "not_assessed",
                        ],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "moderate", "low"],
                    },
                    "evidence": {"type": "string"},
                },
                "required": [
                    "capability_key",
                    "capability_label",
                    "importance",
                    "alignment",
                    "confidence",
                    "evidence",
                ],
            },
        },
        "competency_breakdown": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "assessment_key": {"type": "string"},
                    "assessment_name": {"type": "string"},
                    "performance_summary": {"type": "string"},
                    "role_relevance": {"type": "string"},
                    "subscale_notes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "subscale_key": {"type": "string"},
                                "note": {"type": "string"},
                            },
                            "required": ["subscale_key", "note"],
                        },
                    },
                },
                "required": [
                    "assessment_key",
                    "assessment_name",
                    "performance_summary",
                    "role_relevance",
                ],
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
        "strengths": {"type": "array", "items": {"type": "string"}},
        "areas_to_explore": {"type": "array", "items": {"type": "string"}},
        "work_environment_notes": {"type": "array", "items": {"type": "string"}},
        "interview_focus_areas": {"type": "array", "items": {"type": "string"}},
        "verify_separately": {"type": "array", "items": {"type": "string"}},
        "support_suggestions": {"type": "array", "items": {"type": "string"}},
        "reliability_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "headline",
        "key_takeaways",
        "executive_summary",
        "role_alignment",
        "competency_breakdown",
        "category_summaries",
        "strengths",
        "areas_to_explore",
        "work_environment_notes",
        "interview_focus_areas",
        "verify_separately",
        "support_suggestions",
        "reliability_notes",
    ],
}

# Back-compat alias for scripts still importing the old name.
REPORT_SYNTHESIS_JSON_SCHEMA = REPORT_NARRATIVE_JSON_SCHEMA
