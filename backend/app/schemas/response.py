import uuid
from typing import Dict, Any

from pydantic import BaseModel, Field

# One question cannot plausibly take longer than a full day of wall-clock time;
# anything above is a clock bug and is rejected rather than stored.
MAX_ELAPSED_SECONDS = 86_400


class ResponseSave(BaseModel):
    """Single answer plus optional cognitive-velocity telemetry.

    ``elapsed_seconds`` is client-measured active time on the question and is
    advisory; the server keeps its own module-level duration as ground truth.
    """

    assessment_id: uuid.UUID
    question_id: str
    response: Dict[str, Any]
    elapsed_seconds: float | None = Field(default=None, ge=0, le=MAX_ELAPSED_SECONDS)


class ResponseSubmit(BaseModel):
    """Optional pending answers persisted atomically with completion."""

    responses: list[ResponseSave] = []
    total_module_duration_seconds: float | None = Field(
        default=None, ge=0, le=MAX_ELAPSED_SECONDS
    )
