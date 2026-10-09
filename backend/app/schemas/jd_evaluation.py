"""Gemini structured output for job-description fit. Isolated from HTTP schemas."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


HiringRecommendation = Literal["strong_hire", "consider", "do_not_proceed"]


class JdAssessmentFit(BaseModel):
    title: str
    fit: int = Field(ge=0, le=100)
    notes: str


class JdCompetency(BaseModel):
    name: str
    score: int = Field(ge=0, le=100)


class JdFitEvaluation(BaseModel):
    overall_fit: int = Field(ge=0, le=100)
    summary: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    hiring_recommendation: HiringRecommendation = "consider"
    competencies: list[JdCompetency] = Field(default_factory=list)
    per_assessment: list[JdAssessmentFit] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_gaps(cls, data: Any) -> Any:
        """Map cached payloads that used `gaps` instead of `risks`."""
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if "risks" not in payload and "gaps" in payload:
            payload["risks"] = payload.get("gaps") or []
        if "hiring_recommendation" not in payload:
            overall = payload.get("overall_fit")
            try:
                score = int(overall)
            except (TypeError, ValueError):
                score = 50
            if score >= 75:
                payload["hiring_recommendation"] = "strong_hire"
            elif score >= 50:
                payload["hiring_recommendation"] = "consider"
            else:
                payload["hiring_recommendation"] = "do_not_proceed"
        if "competencies" not in payload:
            comps = []
            for item in payload.get("per_assessment") or []:
                if isinstance(item, dict) and item.get("title") is not None:
                    comps.append(
                        {
                            "name": item.get("title"),
                            "score": item.get("fit", 0),
                        }
                    )
            payload["competencies"] = comps
        # Cached Gemini payloads may still include interview_questions; drop them.
        payload.pop("interview_questions", None)
        return payload

    @field_validator("hiring_recommendation", mode="before")
    @classmethod
    def normalize_recommendation(cls, value: Any) -> str:
        if value is None:
            return "consider"
        text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        aliases = {
            "strong": "strong_hire",
            "hire": "strong_hire",
            "strong_hire": "strong_hire",
            "consider": "consider",
            "maybe": "consider",
            "do_not_proceed": "do_not_proceed",
            "do_not_hire": "do_not_proceed",
            "reject": "do_not_proceed",
            "no": "do_not_proceed",
        }
        return aliases.get(text, "consider")


# Hand-written JSON Schema for Gemini (no additionalProperties / $defs).
JD_FIT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "overall_fit": {"type": "integer", "minimum": 0, "maximum": 100},
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "hiring_recommendation": {
            "type": "string",
            "enum": ["strong_hire", "consider", "do_not_proceed"],
        },
        "competencies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["name", "score"],
            },
        },
        "per_assessment": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "fit": {"type": "integer", "minimum": 0, "maximum": 100},
                    "notes": {"type": "string"},
                },
                "required": ["title", "fit", "notes"],
            },
        },
    },
    "required": [
        "overall_fit",
        "summary",
        "strengths",
        "risks",
        "hiring_recommendation",
        "competencies",
        "per_assessment",
    ],
}

RECOMMENDATION_LABELS = {
    "strong_hire": "Strong Hire",
    "consider": "Consider",
    "do_not_proceed": "Do Not Proceed",
}
