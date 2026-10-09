"""Profile resolver contract.

Resolvers turn generic scoring output (facet means) into instrument-specific
composite profiles. This package is pure domain logic: no DB or network I/O.
"""
from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

ProfileStatus = Literal["complete", "insufficient_data"]


class ItemResult(BaseModel):
    """One saved candidate response, as seen by a resolver."""

    question_id: str
    response: Any = None
    elapsed_seconds: float | None = None


class ProfileInputs(BaseModel):
    """Everything a resolver may read; built by the service layer.

    Strict so corrupt facet data ("4.0", True) fails at the boundary instead of
    being coerced into a plausible-looking number.
    """

    model_config = ConfigDict(strict=True)

    facet_scores: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    item_results: list[ItemResult] = Field(default_factory=list)
    elapsed_seconds: float | None = None


class DerivedProfile(BaseModel):
    """Versioned resolver output persisted to ``candidate_progress.derived_profile``."""

    resolver: str
    version: str
    status: ProfileStatus
    data: dict[str, Any] = Field(default_factory=dict)


class ProfileResolver(Protocol):
    """Structural contract every registered resolver implements."""

    key: str
    version: str

    def resolve(self, inputs: ProfileInputs) -> DerivedProfile:
        """Derive a profile from scoring inputs.

        Args:
            inputs: Facet scores, item results, and module timing.

        Returns:
            DerivedProfile with ``complete`` or ``insufficient_data`` status.
        """
        ...
