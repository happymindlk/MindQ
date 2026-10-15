"""Polymorphic question payloads for the dynamic assessment builder.

Each builder type validates its own answer key and serializes into the portal
storage shape (``assessments.questions`` / ``template_questions.question_payload``).
Scoring keys (weights, correct keys, accepted answers, reverse flags, rationale)
live in storage but are stripped by ``CandidateQuestion`` before reaching candidates.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from app.config import settings

MEDIA_BUCKET = "assessment-media"
SJT_OPTION_COUNT = 4
SJT_MAX_WEIGHT = 3
LIKERT_POINTS = 5
LIKERT_LABEL_MAX = 64
LIKERT_DEFAULT_LABELS: tuple[str, ...] = (
    "Very Inaccurate",
    "Moderately Inaccurate",
    "Neither Inaccurate nor Accurate",
    "Moderately Accurate",
    "Very Accurate",
)
LIKERT_AGREEMENT_LABELS: tuple[str, ...] = (
    "Strongly Disagree",
    "Disagree",
    "Neutral",
    "Agree",
    "Strongly Agree",
)

BuilderType = Literal["sjt", "mcq", "likert", "crt", "open_ended"]

_QUOTED_ANSWER = re.compile(r'"([^"]*)"')


def split_accepted_answers(values: Iterable[Any] | None) -> list[str]:
    """Flatten CRT answers pasted as one quoted, comma-separated string.

    Authors sometimes paste ``"5", "5 cents"`` into a single answer box, which
    would otherwise be stored as one literal answer no candidate can match.

    Args:
        values: Raw ``accepted_answers`` entries.

    Returns:
        Trimmed, non-empty answers with quoted lists expanded.
    """
    answers: list[str] = []
    for value in values or []:
        text = str(value).strip()
        quoted = _QUOTED_ANSWER.findall(text)
        for part in quoted or [text]:
            part = part.strip()
            if part:
                answers.append(part)
    return answers


def _validate_media_url(value: str | None) -> str | None:
    """Accept only public URLs inside this project's ``assessment-media`` bucket.

    Args:
        value: Candidate URL from the admin editor.

    Returns:
        The trimmed URL, or None when blank.

    Raises:
        ValueError: URL is not https/http, points at a foreign host, or another bucket.
    """
    if value is None:
        return None
    url = value.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError("media_url must be an http(s) URL")
    expected_host = urlparse(settings.SUPABASE_URL).netloc
    if expected_host and parsed.netloc != expected_host:
        raise ValueError("media_url must be hosted on this project's Supabase Storage")
    if f"/storage/v1/object/public/{MEDIA_BUCKET}/" not in parsed.path:
        raise ValueError(f"media_url must point at the {MEDIA_BUCKET} bucket")
    return url


class _QuestionBase(BaseModel):
    """Fields shared by every builder question type."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    prompt: str = Field(min_length=1, max_length=8000)
    facet: str = Field(default="", max_length=64)
    sme_rationale: str = Field(default="", max_length=4000)
    media_url: str | None = Field(default=None, max_length=1024)

    @field_validator("media_url")
    @classmethod
    def _media_url(cls, value: str | None) -> str | None:
        return _validate_media_url(value)

    def _base_storage(self) -> dict[str, Any]:
        stored: dict[str, Any] = {
            "text": self.prompt,
            "facet": self.facet,
            "evaluated_competency": self.facet or "General",
            "sme_rationale": self.sme_rationale,
        }
        if self.media_url:
            stored["media_url"] = self.media_url
        return stored


class SjtOption(BaseModel):
    """One situational-judgment response option with its effectiveness weight."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=1000)
    weight: int = Field(ge=0, le=SJT_MAX_WEIGHT)


class SjtPayload(_QuestionBase):
    """Weighted SJT: four options A–D, each scored 0 (worst) to 3 (best)."""

    type: Literal["sjt"] = "sjt"
    options: list[SjtOption] = Field(min_length=SJT_OPTION_COUNT, max_length=SJT_OPTION_COUNT)

    @model_validator(mode="after")
    def _has_best_option(self) -> SjtPayload:
        if max(o.weight for o in self.options) == 0:
            raise ValueError("SJT needs at least one option with a weight above 0")
        if len({o.text.lower() for o in self.options}) != len(self.options):
            raise ValueError("SJT options must be unique")
        return self

    def to_storage(self) -> dict[str, Any]:
        """Serialize into portal storage shape.

        Returns:
            Question dict with ``option_weights`` aligned to ``options``.
        """
        return {
            **self._base_storage(),
            "type": "sjt",
            "builder_type": "sjt",
            "options": [o.text for o in self.options],
            "option_weights": [o.weight for o in self.options],
        }


class McqPayload(_QuestionBase):
    """CogniCheck MCQ with a single correct key or multiple valid keys."""

    type: Literal["mcq"] = "mcq"
    mode: Literal["single", "multiple"] = "single"
    options: list[str] = Field(min_length=2, max_length=8)
    correct_keys: list[int] = Field(min_length=1)

    @field_validator("options")
    @classmethod
    def _options_clean(cls, value: list[str]) -> list[str]:
        cleaned = [o.strip() for o in value]
        if any(not o for o in cleaned):
            raise ValueError("MCQ options cannot be blank")
        if len({o.lower() for o in cleaned}) != len(cleaned):
            raise ValueError("MCQ options must be unique")
        return cleaned

    @model_validator(mode="after")
    def _keys_valid(self) -> McqPayload:
        keys = sorted(set(self.correct_keys))
        if any(k < 0 or k >= len(self.options) for k in keys):
            raise ValueError("correct_keys must reference existing options")
        if self.mode == "single" and len(keys) != 1:
            raise ValueError("Single-correct MCQ requires exactly one correct key")
        self.correct_keys = keys
        return self

    def to_storage(self) -> dict[str, Any]:
        """Serialize into portal storage shape.

        Returns:
            Question dict; ``correct_answer`` holds option text(s) for the scorer.
        """
        answers = [self.options[k] for k in self.correct_keys]
        return {
            **self._base_storage(),
            "type": "mcq",
            "builder_type": "mcq",
            "options": list(self.options),
            "allow_multiple": self.mode == "multiple",
            "correct_keys": list(self.correct_keys),
            "correct_answer": answers if self.mode == "multiple" else answers[0],
        }


def normalize_likert_labels(
    labels: Any = None,
    low: Any = None,
    high: Any = None,
) -> list[str]:
    """Resolve a full five-point label set from new or legacy storage fields.

    Args:
        labels: ``scale_labels`` list (may be missing, short, or contain blanks).
        low: Legacy ``likert_label_1`` endpoint label.
        high: Legacy ``likert_label_5`` endpoint label.

    Returns:
        Exactly ``LIKERT_POINTS`` labels; gaps fall back to the IPIP defaults.
    """
    resolved = list(LIKERT_DEFAULT_LABELS)
    if isinstance(labels, (list, tuple)):
        for i, label in enumerate(labels[:LIKERT_POINTS]):
            if isinstance(label, str) and label.strip():
                resolved[i] = label.strip()
        return resolved
    endpoints = f"{low or ''} {high or ''}".lower()
    if "agree" in endpoints:
        resolved = list(LIKERT_AGREEMENT_LABELS)
    if isinstance(low, str) and low.strip():
        resolved[0] = low.strip()
    if isinstance(high, str) and high.strip():
        resolved[-1] = high.strip()
    return resolved


class LikertPayload(_QuestionBase):
    """Five-point Likert item with admin-editable anchors.

    Scoring uses only the selected index (1–5, recoded ``6 - x`` when reverse
    scored), so labels are presentation-only and can be customised freely.
    """

    type: Literal["likert"] = "likert"
    reverse_scored: bool = False
    scale_labels: list[str] = Field(
        default_factory=lambda: list(LIKERT_DEFAULT_LABELS),
        min_length=LIKERT_POINTS,
        max_length=LIKERT_POINTS,
    )

    @model_validator(mode="before")
    @classmethod
    def _fold_legacy_labels(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "likert_label_1" not in data and "likert_label_5" not in data:
            return data
        folded = dict(data)
        low = folded.pop("likert_label_1", None)
        high = folded.pop("likert_label_5", None)
        if "scale_labels" not in folded:
            folded["scale_labels"] = normalize_likert_labels(None, low, high)
        return folded

    @field_validator("scale_labels")
    @classmethod
    def _labels_clean(cls, value: list[str]) -> list[str]:
        cleaned = [label.strip() for label in value]
        if any(not label for label in cleaned):
            raise ValueError("Every Likert scale label must be filled in")
        if any(len(label) > LIKERT_LABEL_MAX for label in cleaned):
            raise ValueError(f"Likert scale labels must be {LIKERT_LABEL_MAX} characters or fewer")
        if len({label.lower() for label in cleaned}) != len(cleaned):
            raise ValueError("Likert scale labels must be unique")
        return cleaned

    def to_storage(self) -> dict[str, Any]:
        """Serialize into portal storage shape.

        Returns:
            Question dict with the reverse flag kept server-side. Endpoint
            labels are mirrored into ``likert_label_1``/``likert_label_5`` for
            legacy report and package consumers.
        """
        return {
            **self._base_storage(),
            "type": "likert",
            "builder_type": "likert",
            "options": [],
            "scale_points": LIKERT_POINTS,
            "reverse_scored": self.reverse_scored,
            "scale_labels": list(self.scale_labels),
            "likert_label_1": self.scale_labels[0],
            "likert_label_5": self.scale_labels[-1],
        }


class CrtPayload(_QuestionBase):
    """Cognitive Reflection item: single free-text answer matched strictly."""

    type: Literal["crt"] = "crt"
    accepted_answers: list[str] = Field(min_length=1, max_length=10)
    match: Literal["exact", "numeric"] = "exact"

    @field_validator("accepted_answers")
    @classmethod
    def _answers_clean(cls, value: list[str]) -> list[str]:
        cleaned = split_accepted_answers(value)
        if not cleaned:
            raise ValueError("CRT requires at least one accepted answer")
        return cleaned

    @model_validator(mode="after")
    def _numeric_parseable(self) -> CrtPayload:
        if self.match == "numeric":
            for answer in self.accepted_answers:
                try:
                    number = float(answer)
                except ValueError as exc:
                    raise ValueError(f'"{answer}" is not a number') from exc
                if not math.isfinite(number):
                    raise ValueError("Accepted numeric answers must be finite")
        return self

    def to_storage(self) -> dict[str, Any]:
        """Serialize into portal storage shape.

        Returns:
            Question dict rendered as a single strict input.
        """
        return {
            **self._base_storage(),
            "type": "crt",
            "builder_type": "crt",
            "options": [],
            "accepted_answers": list(self.accepted_answers),
            "match": self.match,
        }


class OpenEndedPayload(_QuestionBase):
    """Free-text technical item graded later by the rubric-based evaluator."""

    type: Literal["open_ended"] = "open_ended"
    rubric: str = Field(default="", max_length=8000)

    def to_storage(self) -> dict[str, Any]:
        """Serialize into portal storage shape.

        Returns:
            Question dict; ``benchmark_rubric`` feeds technical/JD evaluation.
        """
        return {
            **self._base_storage(),
            "type": "open",
            "builder_type": "open_ended",
            "options": [],
            "benchmark_rubric": self.rubric,
        }


QuestionPayload = Annotated[
    Union[SjtPayload, McqPayload, LikertPayload, CrtPayload, OpenEndedPayload],
    Field(discriminator="type"),
]

question_payload_adapter: TypeAdapter[QuestionPayload] = TypeAdapter(QuestionPayload)


def payload_from_storage(stored: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild an editor-shaped payload dict from portal storage.

    Args:
        stored: Question dict as persisted in JSONB.

    Returns:
        Dict matching one ``QuestionPayload`` variant, or None for legacy rows
        that cannot be expressed in the builder (caller falls back to flat fields).
    """
    builder = str(stored.get("builder_type") or stored.get("type") or "")
    base = {
        "prompt": str(stored.get("text") or stored.get("prompt") or ""),
        "facet": str(
            (stored.get("facet") if "facet" in stored else stored.get("evaluated_competency")) or ""
        ),
        "sme_rationale": str(stored.get("sme_rationale") or ""),
        "media_url": stored.get("media_url"),
    }
    options = [str(o) for o in (stored.get("options") or [])]
    if builder == "sjt":
        weights = list(stored.get("option_weights") or [])
        return {
            **base,
            "type": "sjt",
            "options": [
                {"text": text, "weight": int(weights[i]) if i < len(weights) else 0}
                for i, text in enumerate(options)
            ],
        }
    if builder == "mcq":
        keys = stored.get("correct_keys")
        if not isinstance(keys, list):
            raw = stored.get("correct_answer")
            answers = raw if isinstance(raw, list) else [raw] if raw else []
            keys = [i for i, o in enumerate(options) if o in {str(a) for a in answers}]
        multiple = bool(stored.get("allow_multiple"))
        return {
            **base,
            "type": "mcq",
            "mode": "multiple" if multiple else "single",
            "options": options,
            "correct_keys": [int(k) for k in keys],
        }
    if builder == "likert":
        return {
            **base,
            "type": "likert",
            "reverse_scored": bool(stored.get("reverse_scored")),
            "scale_labels": normalize_likert_labels(
                stored.get("scale_labels"),
                stored.get("likert_label_1"),
                stored.get("likert_label_5"),
            ),
        }
    if builder == "crt":
        return {
            **base,
            "type": "crt",
            "accepted_answers": split_accepted_answers(stored.get("accepted_answers")),
            "match": stored.get("match") if stored.get("match") in ("exact", "numeric") else "exact",
        }
    if builder in ("open", "open_ended"):
        return {
            **base,
            "type": "open_ended",
            "rubric": str(stored.get("benchmark_rubric") or stored.get("correct_answer_or_rubric") or ""),
        }
    return None
