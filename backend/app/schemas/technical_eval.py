"""Structured Gemini output for a single custom technical question."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class TechnicalItemEvaluation(BaseModel):
    """Score, narrative feedback, and rubric bullets for one written answer."""

    score: int = Field(ge=0, le=100)
    feedback: str
    scorecard: list[str] = Field(default_factory=list)

    @field_validator("feedback", mode="before")
    @classmethod
    def _strip_feedback(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("scorecard", mode="before")
    @classmethod
    def _coerce_scorecard(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, dict):
            out: list[str] = []
            for key, item in value.items():
                text = str(item).strip()
                if text:
                    out.append(f"{key}: {text}")
            return out
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []


TECHNICAL_ITEM_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "feedback": {"type": "string"},
        "scorecard": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "feedback", "scorecard"],
}
