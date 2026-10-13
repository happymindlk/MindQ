import json
import uuid
from typing import Annotated, Any, Dict

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# One question cannot plausibly take longer than a full day of wall-clock time;
# anything above is a clock bug and is rejected rather than stored.
MAX_ELAPSED_SECONDS = 86_400
# Long-form technical answers fit comfortably; larger bodies are abuse.
MAX_ANSWER_TEXT_CHARS = 20_000
MAX_ANSWER_LIST_ITEMS = 50
MAX_ANSWER_ITEM_CHARS = 1_000
MAX_RESPONSE_JSON_BYTES = 64 * 1024
MAX_PENDING_RESPONSES = 500
# Keys accepted by ``scoring._extract_answer``. Everything else (``ai_score``,
# ``ai_evaluation``, ``scorecard``, …) is server-owned grading output; accepting
# it from the candidate would let them forge their own AI grade.
CANDIDATE_ANSWER_KEYS = frozenset({"answer", "value", "selected"})

QuestionId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:\-]+$"),
]


def _validate_answer_value(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("answer must be a finite number")
        return value
    if isinstance(value, str):
        if len(value) > MAX_ANSWER_TEXT_CHARS:
            raise ValueError(f"answer exceeds {MAX_ANSWER_TEXT_CHARS} characters")
        return value
    if isinstance(value, list):
        if len(value) > MAX_ANSWER_LIST_ITEMS:
            raise ValueError(f"answer list exceeds {MAX_ANSWER_LIST_ITEMS} items")
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (str, int, float)):
                raise ValueError("answer list items must be strings or numbers")
            if isinstance(item, str) and len(item) > MAX_ANSWER_ITEM_CHARS:
                raise ValueError(f"answer list item exceeds {MAX_ANSWER_ITEM_CHARS} characters")
        return value
    raise ValueError("answer must be a string, number, list, or null")


class ResponseSave(BaseModel):
    """Single answer plus optional cognitive-velocity telemetry.

    ``elapsed_seconds`` is client-measured active time on the question and is
    advisory; the server keeps its own module-level duration as ground truth.
    """

    model_config = ConfigDict(extra="forbid")

    assessment_id: uuid.UUID
    question_id: QuestionId
    response: Dict[str, Any]
    elapsed_seconds: float | None = Field(default=None, ge=0, le=MAX_ELAPSED_SECONDS)

    @field_validator("response")
    @classmethod
    def _validate_response(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        """Allow only answer-carrying keys with bounded scalar/list values.

        Args:
            value: Raw ``response`` object from the candidate.

        Returns:
            The validated response dict.

        Raises:
            ValueError: Unknown keys, oversized payloads, or nested objects.
        """
        unknown = set(value) - CANDIDATE_ANSWER_KEYS
        if unknown:
            raise ValueError(f"response contains unsupported keys: {sorted(unknown)}")
        if not value:
            raise ValueError("response must include an answer")
        for item in value.values():
            _validate_answer_value(item)
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_JSON_BYTES:
            raise ValueError("response payload is too large")
        return value


class ResponseSubmit(BaseModel):
    """Optional pending answers persisted atomically with completion."""

    model_config = ConfigDict(extra="forbid")

    responses: list[ResponseSave] = Field(default_factory=list, max_length=MAX_PENDING_RESPONSES)
    total_module_duration_seconds: float | None = Field(
        default=None, ge=0, le=MAX_ELAPSED_SECONDS
    )
