"""Instrument-specific display scores, bands, and completeness (MindQ Scoring v2).

Gemini never computes these values. Personality and interpersonal style are
descriptive, not evaluative. Timing is ignored.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from app.services.scoring import LIKERT_MAX, LIKERT_MIN, ScoreResult

SCORING_VERSION = "mindq-scoring-2.0.0"

ScoreKind = Literal["percentage", "count", "traits", "circumplex", "domain"]

POSITION_BAND_LABELS: dict[str, str] = {
    "very_high": "Very high",
    "high": "High",
    "moderate": "Moderate",
    "low": "Low",
    "very_low": "Very low",
}

CRT_BAND_LABELS: dict[str, str] = {
    "consistently_reflective": "Consistently reflective",
    "mostly_reflective": "Mostly reflective",
    "mostly_intuitive": "Mostly intuitive",
    "intuitive": "Intuitive",
}

SJT_BAND_LABELS: dict[str, str] = {
    "consistently_strong": "Consistently strong",
    "generally_sound": "Generally sound",
    "mixed": "Mixed",
    "frequently_weaker": "Frequently weaker",
}

IPC_DISPLAY_NAMES: dict[str, str] = {
    "PA": "Assured and takes charge",
    "BC": "Competitive and calculating",
    "DE": "Tough-minded and detached",
    "FG": "Reserved and private",
    "HI": "Quiet and deferential",
    "JK": "Easygoing and trusting",
    "LM": "Warm and cooperative",
    "NO": "Outgoing and sociable",
}

_BIG_FIVE_KEYS: dict[str, str] = {
    "extraversion": "extraversion",
    "surgency": "extraversion",
    "e": "extraversion",
    "agreeableness": "agreeableness",
    "a": "agreeableness",
    "conscientiousness": "conscientiousness",
    "c": "conscientiousness",
    "neuroticism": "neuroticism",
    "n": "neuroticism",
    "intellect": "intellect",
    "imagination": "intellect",
    "openness": "intellect",
    "o": "intellect",
    "intellect or imagination": "intellect",
    "intellect/openness": "intellect",
    "intellect/imagination": "intellect",
}

_BIG_FIVE_LABELS: dict[str, str] = {
    "extraversion": "Extraversion",
    "agreeableness": "Agreeableness",
    "conscientiousness": "Conscientiousness",
    "emotional_stability": "Emotional stability",
    "intellect": "Intellect or Imagination",
}

_HEXACO_KEYS: dict[str, str] = {
    "h:sinc": "sincerity",
    "sincerity": "sincerity",
    "h:fair": "fairness",
    "fairness": "fairness",
    "h:gree": "greed_avoidance",
    "greed": "greed_avoidance",
    "greed avoidance": "greed_avoidance",
    "h:mode": "modesty",
    "modesty": "modesty",
}

_HEXACO_LABELS: dict[str, str] = {
    "sincerity": "Sincerity",
    "fairness": "Fairness",
    "greed_avoidance": "Greed Avoidance",
    "modesty": "Modesty",
}

_INITIATIVE_KEYS = frozenset(
    {"proactive personality", "personal initiative", "initiative", "pi"}
)
_IPC_OCTANTS = frozenset({"pa", "bc", "de", "fg", "hi", "jk", "lm", "no"})


def likert_position_pct(mean: float) -> float:
    """Map a 1–5 Likert mean onto 0–100.

    Args:
        mean: Facet mean on the original 1–5 scale.

    Returns:
        Percentage rounded to one decimal.
    """
    clamped = min(LIKERT_MAX, max(LIKERT_MIN, float(mean)))
    return round((clamped - LIKERT_MIN) / (LIKERT_MAX - LIKERT_MIN) * 100, 1)


def position_band(pct: float) -> str:
    """Inclusive-lower position band used across the platform.

    Args:
        pct: 0–100 position score.

    Returns:
        ``very_low`` / ``low`` / ``moderate`` / ``high`` / ``very_high``.
    """
    if pct >= 80:
        return "very_high"
    if pct >= 60:
        return "high"
    if pct >= 40:
        return "moderate"
    if pct >= 20:
        return "low"
    return "very_low"


def position_band_label(pct: float) -> str:
    """Human-readable position band.

    Args:
        pct: 0–100 position score.

    Returns:
        Display label.
    """
    return POSITION_BAND_LABELS[position_band(pct)]


def crt_band(correct: int, total: int) -> str:
    """CRT display band from reflective-item count.

    Args:
        correct: Number of accepted answers.
        total: CRT item count.

    Returns:
        CRT band key.
    """
    if total <= 0:
        return "intuitive"
    if correct >= total:
        return "consistently_reflective"
    if total == 3:
        if correct >= 2:
            return "mostly_reflective"
        if correct >= 1:
            return "mostly_intuitive"
        return "intuitive"
    ratio = correct / total
    if ratio >= 2 / 3:
        return "mostly_reflective"
    if ratio > 0:
        return "mostly_intuitive"
    return "intuitive"


def sjt_band(points: float, maximum: float) -> str:
    """SJT display band from raw points (canonical max 24).

    Args:
        points: Sum of chosen option weights.
        maximum: Sum of best-option weights.

    Returns:
        SJT band key.
    """
    scale = (maximum / 24.0) if maximum and maximum != 24 else 1.0
    if points >= 20 * scale:
        return "consistently_strong"
    if points >= 15 * scale:
        return "generally_sound"
    if points >= 10 * scale:
        return "mixed"
    return "frequently_weaker"


def sjt_item_tier(credit: float) -> str:
    """Per-item SJT credit tier from 0–1 credit.

    Args:
        credit: Chosen weight / best weight.

    Returns:
        Same keys as the module SJT bands.
    """
    if credit >= 1.0:
        return "consistently_strong"
    if credit >= 2 / 3:
        return "generally_sound"
    if credit >= 1 / 3:
        return "mixed"
    return "frequently_weaker"


def ipc_intensity(vector_length: float) -> str:
    """Circumplex intensity from vector length R.

    Args:
        vector_length: Hypotenuse of dominance/warmth.

    Returns:
        Intensity key.
    """
    if vector_length < 0.3:
        return "undifferentiated"
    if vector_length < 1.5:
        return "mild"
    if vector_length < 3.0:
        return "moderate"
    return "pronounced"


def _norm_key(name: str) -> str:
    return " ".join(str(name or "").strip().lower().replace("_", " ").split())


def _facet_mean(entry: Any) -> float | None:
    if isinstance(entry, Mapping):
        raw = entry.get("mean")
    else:
        raw = entry
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def classify_instrument(
    facet_scores: Mapping[str, Any] | None,
    questions: Sequence[Any] | None,
    derived_profile: Mapping[str, Any] | None = None,
) -> str:
    """Identify the scoring family for display rules.

    Args:
        facet_scores: Stored Likert facet map.
        questions: Assessment question bank.
        derived_profile: Resolver payload, if any.

    Returns:
        Instrument family key.
    """
    resolver = ""
    if isinstance(derived_profile, Mapping):
        resolver = str(derived_profile.get("resolver") or "")
        data = derived_profile.get("data")
        if isinstance(data, Mapping) and data.get("style_code") is not None:
            resolver = resolver or "ipip_ipc_v1"
    if resolver.startswith("ipip_ipc"):
        return "ipc"

    types = {
        str(q.get("type") or q.get("question_type") or "").lower()
        for q in questions or []
        if isinstance(q, dict)
    }
    types.discard("")
    if "crt" in types and not types.intersection({"mcq", "sjt", "likert"}):
        return "crt"
    if "sjt" in types:
        return "sjt"
    scored = types - {"open", "open_ended"}
    if scored == {"mcq"}:
        return "mcq"

    keys = {_norm_key(k) for k in (facet_scores or {})}
    if keys & _IPC_OCTANTS:
        return "ipc"
    if any(k in _BIG_FIVE_KEYS for k in keys):
        return "big_five"
    if any(k in _HEXACO_KEYS for k in keys):
        return "hexaco"
    if keys & _INITIATIVE_KEYS:
        return "initiative"
    if "likert" in types and not types.intersection({"mcq", "sjt", "crt"}):
        if len(keys) <= 1:
            return "initiative" if keys & _INITIATIVE_KEYS else "likert"
        return "likert"
    if types.intersection({"mcq", "sjt", "crt"}):
        return "ability"
    return "generic"


def big_five_subscales(facet_scores: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Five IPIP-NEO-20 traits with Emotional stability flipped from Neuroticism.

    Args:
        facet_scores: Facet means keyed by trait name.

    Returns:
        Ordered subscale dicts.
    """
    mapped: dict[str, float] = {}
    for raw_key, entry in facet_scores.items():
        canonical = _BIG_FIVE_KEYS.get(_norm_key(raw_key))
        mean = _facet_mean(entry)
        if canonical is None or mean is None:
            continue
        mapped[canonical] = mean
    traits: list[dict[str, Any]] = []
    order = (
        "extraversion",
        "agreeableness",
        "conscientiousness",
        "emotional_stability",
        "intellect",
    )
    for trait in order:
        if trait == "emotional_stability":
            n_mean = mapped.get("neuroticism")
            if n_mean is None:
                continue
            mean = (LIKERT_MIN + LIKERT_MAX) - n_mean
        else:
            mean = mapped.get(trait)
            if mean is None:
                continue
        pct = likert_position_pct(mean)
        traits.append(
            {
                "name": _BIG_FIVE_LABELS[trait],
                "mean": round(mean, 3),
                "position_pct": pct,
                "band": position_band(pct),
                "band_label": position_band_label(pct),
            }
        )
    return traits


def hexaco_subscales(facet_scores: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Honesty-Humility facet rows.

    Args:
        facet_scores: Facet means.

    Returns:
        Ordered subscale dicts.
    """
    mapped: dict[str, float] = {}
    for raw_key, entry in facet_scores.items():
        canonical = _HEXACO_KEYS.get(_norm_key(raw_key))
        mean = _facet_mean(entry)
        if canonical is None or mean is None:
            continue
        mapped[canonical] = mean
    rows: list[dict[str, Any]] = []
    for key in ("sincerity", "fairness", "greed_avoidance", "modesty"):
        mean = mapped.get(key)
        if mean is None:
            continue
        pct = likert_position_pct(mean)
        rows.append(
            {
                "name": _HEXACO_LABELS[key],
                "mean": round(mean, 3),
                "position_pct": pct,
                "band": position_band(pct),
                "band_label": position_band_label(pct),
            }
        )
    return rows


def single_facet_subscales(facet_scores: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generic Likert facets mapped independently (never averaged together).

    Args:
        facet_scores: Facet means.

    Returns:
        Subscale dicts in insertion order.
    """
    rows: list[dict[str, Any]] = []
    for raw_key, entry in facet_scores.items():
        mean = _facet_mean(entry)
        if mean is None:
            continue
        pct = likert_position_pct(mean)
        label = str(raw_key)
        if _norm_key(raw_key) in _INITIATIVE_KEYS:
            label = "Personal Initiative"
        rows.append(
            {
                "name": label,
                "mean": round(mean, 3),
                "position_pct": pct,
                "band": position_band(pct),
                "band_label": position_band_label(pct),
            }
        )
    return rows


def completeness_payload(result: ScoreResult, instrument: str) -> dict[str, Any]:
    """Completeness flags persisted on ``score_details``.

    Args:
        result: Scoring output.
        instrument: Family key from ``classify_instrument``.

    Returns:
        Completeness dict.
    """
    total = result.items_total
    unanswered = result.unanswered_count
    insufficient = False
    if instrument == "cognicheck":
        insufficient = unanswered >= 5
    elif total > 5 and total > 0 and unanswered / total > 0.25:
        insufficient = True
    return {
        "items_answered": result.items_answered,
        "items_total": total,
        "unanswered_count": unanswered,
        "insufficient_data": insufficient,
        "uniform_responding": result.uniform_responding,
    }


def build_score_details(
    *,
    questions: Sequence[Any] | None,
    result: ScoreResult,
    derived_profile: Mapping[str, Any] | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Canonical per-assessment scoring payload (Phase 1).

    Args:
        questions: Stored question bank.
        result: ``score_assessment_detailed`` output.
        derived_profile: Resolver JSON, if any.
        category: Internal category key.

    Returns:
        JSON-ready score details including version, band, and subscales.
    """
    facets = result.facet_scores or {}
    instrument = classify_instrument(facets, questions, derived_profile)
    if instrument == "mcq":
        instrument = "cognicheck" if category == "cognitive" else "ability"

    subscales: list[dict[str, Any]] = []
    score_kind: ScoreKind = "percentage"
    display_score: str | None = None
    band: str | None = None
    module_pct: float | None = None

    if instrument == "big_five":
        score_kind = "traits"
        subscales = big_five_subscales(facets)
    elif instrument == "ipc":
        score_kind = "circumplex"
        data = {}
        if isinstance(derived_profile, Mapping):
            data = derived_profile.get("data") or derived_profile
            if not isinstance(data, Mapping):
                data = {}
        intensity = data.get("intensity")
        if intensity is None and data.get("vector_length") is not None:
            intensity = ipc_intensity(float(data["vector_length"]))
        display_score = str(
            data.get("display_name") or data.get("style_label") or "Undifferentiated"
        )
        band = str(intensity or "undifferentiated")
    elif instrument == "hexaco":
        score_kind = "domain"
        subscales = hexaco_subscales(facets)
        if subscales:
            module_pct = round(sum(s["position_pct"] for s in subscales) / len(subscales), 1)
            band = position_band(module_pct)
            display_score = f"{module_pct:g}"
    elif instrument in {"initiative", "likert"}:
        subscales = single_facet_subscales(facets)
        if len(subscales) == 1:
            score_kind = "domain"
            module_pct = subscales[0]["position_pct"]
            band = subscales[0]["band"]
            display_score = f"{module_pct:g}"
        elif subscales:
            score_kind = "traits"
    elif instrument == "crt" and result.crt_total:
        score_kind = "count"
        correct = result.crt_correct or 0
        display_score = f"{correct} of {result.crt_total}"
        band = crt_band(correct, result.crt_total)
    elif instrument == "sjt" and result.sjt_max:
        score_kind = "percentage"
        module_pct = result.score
        display_score = f"{_fmt_points(result.sjt_points)} / {_fmt_points(result.sjt_max)}"
        band = sjt_band(result.sjt_points or 0.0, result.sjt_max)
    else:
        module_pct = result.score
        if module_pct is not None:
            band = position_band(float(module_pct))
            display_score = f"{round(float(module_pct), 1):g}"

    details: dict[str, Any] = {
        "scoring_version": SCORING_VERSION,
        "instrument": instrument,
        "score_kind": score_kind,
        "module_pct": module_pct,
        "display_score": display_score,
        "band": band,
        "band_label": _band_label(instrument, band),
        "subscales": subscales,
        "completeness": completeness_payload(result, instrument),
        "norm_referenced": False,
    }
    if result.crt_total:
        details["crt"] = {"correct": result.crt_correct, "total": result.crt_total}
    if result.sjt_max:
        details["sjt"] = {"points": result.sjt_points, "maximum": result.sjt_max}
    return details


def _fmt_points(value: float | None) -> str:
    if value is None:
        return "0"
    if float(value).is_integer():
        return str(int(value))
    return f"{round(float(value), 2):g}"


def _band_label(instrument: str, band: str | None) -> str | None:
    if not band:
        return None
    if instrument == "crt":
        return CRT_BAND_LABELS.get(band, band)
    if instrument == "sjt":
        return SJT_BAND_LABELS.get(band, band)
    if instrument == "ipc":
        return band.replace("_", " ").capitalize() if band != "undifferentiated" else "Undifferentiated"
    return POSITION_BAND_LABELS.get(band, band)


def module_bar_percentage(details: Mapping[str, Any] | None, stored_score: float | None) -> float | None:
    """Percentage shown as a module bar, or None when the spec forbids blending.

    Args:
        details: Output of ``build_score_details``.
        stored_score: ``candidate_progress.score``.

    Returns:
        Bar percentage or None.
    """
    if not isinstance(details, Mapping):
        return None if stored_score is None else round(float(stored_score), 1)
    kind = details.get("score_kind")
    if kind in {"traits", "circumplex", "count"}:
        return None
    module_pct = details.get("module_pct")
    if isinstance(module_pct, (int, float)) and not isinstance(module_pct, bool):
        return round(float(module_pct), 1)
    if stored_score is not None and kind == "percentage":
        return round(float(stored_score), 1)
    return None
