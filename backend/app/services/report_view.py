"""View-model helpers that mirror the frontend MindQReport layout for WeasyPrint."""
from __future__ import annotations

import re
from typing import Any

CATEGORY_ORDER: tuple[str, ...] = ("Cognitive", "Personality", "Behavioral", "Technical")
PSYCHOMETRIC_CATEGORIES: frozenset[str] = frozenset({"Cognitive", "Personality", "Behavioral"})
_SINGLE_METRIC_MODULES: tuple[str, ...] = ("personal initiative", "cognicheck")
_FILLER_WORDS = re.compile(r"\b(scale|test|assessment|inventory|questionnaire)\b")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def as_number(value: Any) -> float | None:
    """Parse a finite number from an API field.

    Args:
        value: Raw score or percent field.

    Returns:
        Finite float, or None when missing/invalid.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    if isinstance(value, str) and value.strip():
        try:
            number = float(value)
        except ValueError:
            return None
        return number if number == number and abs(number) != float("inf") else None
    return None


def format_score(score: float | None) -> str:
    """Format a percentage score the same way the React preview does.

    Args:
        score: Percent value, or None.

    Returns:
        Rounded percent string with a ``%`` suffix, or empty string.
    """
    if score is None:
        return ""
    rounded = round(score * 10) / 10
    # Match JS template literals: whole numbers render without a trailing ".0".
    text = f"{rounded:.1f}".rstrip("0").rstrip(".")
    return f"{text}%"


def bar_width(score: float | None) -> float:
    """Clamp a score into a 0–100 bar fill percentage.

    Args:
        score: Percent value, or None.

    Returns:
        Width percent for the score bar fill.
    """
    if score is None:
        return 0.0
    return max(0.0, min(100.0, float(score)))


def _normalize_name(value: str) -> str:
    lowered = value.lower()
    lowered = _FILLER_WORDS.sub("", lowered)
    return _NON_ALNUM.sub("", lowered)


def visible_subscales(assessment_name: str, subscales: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop a redundant single subscale that repeats the module name.

    Args:
        assessment_name: Module title from the report payload.
        subscales: Raw subscale dicts from ``competency_breakdown``.

    Returns:
        Subscales that should render under the module card.
    """
    if len(subscales) != 1:
        return subscales
    mod = _normalize_name(assessment_name)
    sub = _normalize_name(str(subscales[0].get("name") or ""))
    if not mod or not sub:
        return subscales
    known = any(mod.startswith(_normalize_name(key)) for key in _SINGLE_METRIC_MODULES)
    if mod == sub or mod in sub or sub in mod or known:
        return []
    return subscales


def _format_row_value(row: dict[str, Any]) -> str:
    display = row.get("display_score")
    band = row.get("band")
    if display:
        return f"{display} · {band}" if band else str(display)
    score = row.get("score")
    if score is not None:
        pct = format_score(score)
        return f"{pct} · {band}" if band else pct
    return str(band or "")


def _to_breakdown_rows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        assessment_name = str(item.get("assessment_name") or "").strip()
        if not assessment_name:
            continue
        parsed_subscales: list[dict[str, Any]] = []
        for sub in item.get("subscales") or []:
            if not isinstance(sub, dict):
                continue
            name = str(sub.get("name") or "").strip()
            if not name:
                continue
            parsed_subscales.append(
                {
                    "name": name,
                    "mean": as_number(sub.get("mean")),
                    "position_pct": as_number(sub.get("position_pct")),
                    "band": (
                        str(sub.get("band_label") or sub.get("band") or "").strip() or None
                    ),
                }
            )
        subscales = visible_subscales(assessment_name, parsed_subscales)
        score = as_number(item.get("score"))
        display_raw = item.get("display_score")
        display_score = (
            str(display_raw).strip()
            if display_raw is not None and str(display_raw).strip()
            else None
        )
        timed_out = item.get("timed_out") is True or str(
            item.get("status") or ""
        ).upper() == "TIMED_OUT"
        status_note_raw = item.get("status_note")
        status_note = (
            str(status_note_raw).strip()
            if status_note_raw is not None and str(status_note_raw).strip()
            else (
                "Candidate ran out of time before completing all items. "
                "Displayed score reflects attempted responses only."
                if timed_out
                else None
            )
        )
        if not timed_out and score is None and not display_score and not parsed_subscales:
            continue
        if timed_out and score is None and not display_score:
            score = 0.0
            display_score = "Incomplete"
        band = (
            "Timed Out / Incomplete"
            if timed_out
            else (
                str(item.get("band")).strip()
                if item.get("band") is not None and str(item.get("band")).strip()
                else None
            )
        )
        rows.append(
            {
                "category": str(item.get("category") or "Technical"),
                "assessment_name": assessment_name,
                "score": score,
                "display_score": display_score,
                "band": band,
                "bar_width": bar_width(score),
                "value_label": _format_row_value(
                    {
                        "display_score": display_score,
                        "band": band,
                        "score": score,
                    }
                ),
                "summary": str(item.get("performance_summary") or "").strip(),
                "subscales": [
                    {
                        **facet,
                        "bar_width": bar_width(facet.get("position_pct")),
                        "value_label": (
                            f"{format_score(facet['position_pct'])}"
                            f"{f' · {facet['band']}' if facet.get('band') else ''}"
                            if facet.get("position_pct") is not None
                            else (facet.get("band") or "")
                        ),
                    }
                    for facet in subscales
                ],
                "timed_out": timed_out,
                "status_note": status_note,
            }
        )
    return rows


def _category_summaries(raw: Any) -> dict[str, str]:
    if not isinstance(raw, list):
        return {}
    out: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if category in PSYCHOMETRIC_CATEGORIES and summary and category not in out:
            out[category] = summary
    return out


def _group_rows(rows: list[dict[str, Any]], summaries: dict[str, str]) -> list[dict[str, Any]]:
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    def rank(category: str) -> int:
        try:
            return CATEGORY_ORDER.index(category)
        except ValueError:
            return len(CATEGORY_ORDER)

    return [
        {
            "category": category,
            "summary": summaries.get(category),
            "rows": by_category[category],
        }
        for category in sorted(by_category.keys(), key=rank)
    ]


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def build_report_view(report: dict[str, Any]) -> dict[str, Any]:
    """Normalize a MindQ report payload into MindQReport-equivalent view data.

    Args:
        report: ``MindQReportResponse.model_dump(mode="json")``.

    Returns:
        Template-ready view model with grouped competency cards and custom items.
    """
    breakdown = _to_breakdown_rows(report.get("competency_breakdown"))
    summary = str(report.get("executive_summary") or "").strip() or None
    reported_completed = as_number(report.get("total_assessments_completed"))
    total_completed = (
        len(breakdown)
        if breakdown
        else max(0, int(reported_completed or 0))
    )
    customs: list[dict[str, Any]] = []
    for index, raw in enumerate(report.get("custom_questions") or []):
        if not isinstance(raw, dict):
            continue
        score = as_number(raw.get("score"))
        status = str(raw.get("ai_eval_status") or "").lower()
        evaluation = str(raw.get("ai_evaluation") or "").strip() or None
        answer = str(raw.get("response_summary") or "").strip() or None
        customs.append(
            {
                "index": index + 1,
                "prompt": str(raw.get("prompt") or "Untitled question"),
                "score": score,
                "score_label": format_score(score) if score is not None else None,
                "evaluated_competency": (
                    str(raw.get("evaluated_competency")).strip()
                    if raw.get("evaluated_competency")
                    else None
                ),
                "answer": answer,
                "evaluation": evaluation,
                "show_fallback": (not evaluation) or status == "failed",
                "scorecard": _as_list(raw.get("scorecard")),
            }
        )
    return {
        "company_name": str(report.get("company_name") or "").strip(),
        "candidate_name": str(report.get("candidate_full_name") or "Candidate"),
        "candidate_email": str(report.get("candidate_email") or "—"),
        "target_role": str(report.get("target_role") or "—") if report.get("target_role") else "—",
        "total_completed": total_completed,
        "summary": summary,
        "synthesis_status": str(report.get("synthesis_status") or "pending"),
        "strengths": _as_list(report.get("strengths")),
        "risks": _as_list(
            report.get("areas_to_explore")
            if report.get("areas_to_explore") is not None
            else report.get("risks_and_antipatterns")
        ),
        "groups": _group_rows(breakdown, _category_summaries(report.get("category_summaries"))),
        "customs": customs,
    }
