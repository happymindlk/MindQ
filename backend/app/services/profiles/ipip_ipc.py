"""IPIP-IPC interpersonal circumplex resolver.

Projects the eight octant means onto Dominance (y) and Warmth (x) axes, then
classifies the resulting vector into an interpersonal style.
"""
from __future__ import annotations

import math
from typing import Any

from app.services.profiles.base import DerivedProfile, ProfileInputs

OCTANTS: tuple[str, ...] = ("PA", "BC", "DE", "FG", "HI", "JK", "LM", "NO")
MIN_ITEMS = 3
DIAGONAL = 0.707
DIFFERENTIATION_THRESHOLD = 0.3
UNDIFFERENTIATED = "undifferentiated"
PRECISION = 3

# (lower_inclusive, upper_exclusive, code, label); LM wraps 0 deg and is the fallback.
_BANDS: tuple[tuple[float, float, str, str], ...] = (
    (22.5, 67.5, "NO", "Gregarious-Extraverted"),
    (67.5, 112.5, "PA", "Assured-Dominant"),
    (112.5, 157.5, "BC", "Arrogant-Calculating"),
    (157.5, 202.5, "DE", "Cold-Hearted"),
    (202.5, 247.5, "FG", "Aloof-Introverted"),
    (247.5, 292.5, "HI", "Unassured-Submissive"),
    (292.5, 337.5, "JK", "Unassuming-Ingenuous"),
)
_LM = ("LM", "Warm-Agreeable")


def classify_angle(angle_deg: float) -> tuple[str, str]:
    """Map a circumplex angle to its octant style.

    Args:
        angle_deg: Angle in degrees, normalized to [0, 360).

    Returns:
        Tuple of (octant code, style label).
    """
    for lower, upper, code, label in _BANDS:
        if lower <= angle_deg < upper:
            return code, label
    return _LM


def _facet_count(entry: dict[str, Any] | None) -> int:
    if not isinstance(entry, dict):
        return 0
    try:
        return int(entry.get("n") or 0)
    except (TypeError, ValueError):
        return 0


def _facet_mean(entry: dict[str, Any] | None) -> float | None:
    if not isinstance(entry, dict):
        return None
    raw = entry.get("mean")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    mean = float(raw)
    return mean if math.isfinite(mean) else None


class IpipIpcResolver:
    """Resolver for the 32-item IPIP-IPC (8 octants x 4 items)."""

    key = "ipip_ipc_v1"
    version = "1.0.0"

    def resolve(self, inputs: ProfileInputs) -> DerivedProfile:
        """Compute circumplex coordinates and interpersonal style.

        Args:
            inputs: Facet scores keyed by octant code (``{"mean", "n"}``).

        Returns:
            ``complete`` profile with coordinates, style, and octant means, or
            ``insufficient_data`` listing octants with fewer than 3 answers.
        """
        means: dict[str, float] = {}
        missing: list[str] = []
        for octant in OCTANTS:
            entry = inputs.facet_scores.get(octant)
            mean = _facet_mean(entry)
            if mean is None or _facet_count(entry) < MIN_ITEMS:
                missing.append(octant)
                continue
            means[octant] = mean

        if missing:
            return DerivedProfile(
                resolver=self.key,
                version=self.version,
                status="insufficient_data",
                data={"missing_octants": missing, "min_items": MIN_ITEMS},
            )

        dominance = means["PA"] - means["HI"] + DIAGONAL * (
            means["BC"] + means["NO"] - means["FG"] - means["JK"]
        )
        warmth = means["LM"] - means["DE"] + DIAGONAL * (
            means["NO"] + means["JK"] - means["BC"] - means["FG"]
        )
        vector_length = math.hypot(warmth, dominance)

        # Classify on unrounded values so rounding can never cross a band edge.
        angle_deg: float | None
        style_code: str | None
        if vector_length < DIFFERENTIATION_THRESHOLD:
            angle_deg = None
            style_code = None
            style_label = UNDIFFERENTIATED
        else:
            angle_deg = math.degrees(math.atan2(dominance, warmth)) % 360.0
            style_code, style_label = classify_angle(angle_deg)

        return DerivedProfile(
            resolver=self.key,
            version=self.version,
            status="complete",
            data={
                "dominance": round(dominance, PRECISION),
                "warmth": round(warmth, PRECISION),
                "vector_length": round(vector_length, PRECISION),
                "angle_deg": round(angle_deg, PRECISION) if angle_deg is not None else None,
                "style_code": style_code,
                "style_label": style_label,
                "octant_means": {k: round(v, PRECISION) for k, v in means.items()},
            },
        )
