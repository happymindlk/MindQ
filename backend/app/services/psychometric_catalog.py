"""Load ``assessments.json`` and map items into portal storage shape.

Catalog item ids (``ipc_01``, ``hex_08``, …) are preserved so scoring and
autosave never depend on presentation order.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.services.scoring import score_assessment_detailed

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "assessments.json"
TARGET_SLUGS: tuple[str, ...] = (
    "ipip_ipc",
    "personal_initiative",
    "sjt",
    "cognicheck",
    "crt",
    "mini_ipip",
    "hexaco_hh",
)

# duration_seconds is authoritative. Only CRT is a strict cutoff.
TIMER_CONFIG: dict[str, tuple[int, str, bool]] = {
    "ipip_ipc": (270, "flexible", False),
    "personal_initiative": (120, "flexible", False),
    "sjt": (300, "flexible", False),
    "cognicheck": (1200, "flexible", False),
    "crt": (180, "strict", False),
    "mini_ipip": (240, "flexible", True),
    "hexaco_hh": (330, "flexible", True),
}

SCORING_PROFILES: dict[str, str | None] = {
    "ipip_ipc": "ipip_ipc_v1",
}

CATEGORY_BY_SLUG: dict[str, str] = {
    "ipip_ipc": "behavioral",
    "personal_initiative": "behavioral",
    "sjt": "behavioral",
    "cognicheck": "cognitive",
    "crt": "cognitive",
    "mini_ipip": "personality",
    "hexaco_hh": "personality",
}


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    """Read the psychometric catalog JSON.

    Args:
        path: Override path (tests).

    Returns:
        Parsed catalog object.
    """
    raw = (path or CATALOG_PATH).read_text(encoding="utf-8")
    return json.loads(raw)


def catalog_assessments(catalog: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Index catalog modules by id.

    Args:
        catalog: Loaded JSON, or None to read from disk.

    Returns:
        ``{slug: module}``.
    """
    data = catalog if catalog is not None else load_catalog()
    return {str(row["id"]): row for row in data.get("assessments") or [] if isinstance(row, dict)}


def assert_catalog_shape(catalog: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Fail fast when the seven target modules or item counts disagree.

    Args:
        catalog: Loaded JSON, or None to read from disk.

    Returns:
        Indexed modules.

    Raises:
        ValueError: Missing slug, itemCount mismatch, or empty bank.
    """
    by_id = catalog_assessments(catalog)
    missing = [slug for slug in TARGET_SLUGS if slug not in by_id]
    if missing:
        raise ValueError(f"assessments.json missing modules: {missing}")
    total = 0
    for slug in TARGET_SLUGS:
        module = by_id[slug]
        items = module.get("items") or []
        declared = int(module.get("itemCount") or 0)
        if len(items) != declared:
            raise ValueError(f"{slug}: itemCount={declared} but {len(items)} items")
        total += len(items)
    if total == 0:
        raise ValueError("catalog has no items")
    return by_id


def _scale_labels(module: dict[str, Any]) -> list[str]:
    scale = module.get("responseScale") or []
    labels = [str(row.get("label") or "").strip() for row in scale if isinstance(row, dict)]
    return [label for label in labels if label]


def _option_text(option: dict[str, Any]) -> str:
    label = str(option.get("label") or "").strip()
    text = str(option.get("text") or "").strip()
    if label and text:
        return f"{label}. {text}"
    return label or text


def item_to_storage(module: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Convert one catalog item into ``assessments.questions`` JSONB shape.

    Args:
        module: Parent catalog module.
        item: Catalog item.

    Returns:
        Portal storage dict keyed by catalog ``item.id``.
    """
    instrument = str(module.get("instrumentType") or "")
    item_id = str(item["id"])
    text = str(item.get("text") or item.get("stem") or "").strip()
    if instrument == "likert":
        labels = _scale_labels(module)
        facet = str(item.get("scale") or "").strip()
        if not facet:
            facet = str((module.get("scales") or [{}])[0].get("name") or "Personal Initiative")
        return {
            "id": item_id,
            "text": text,
            "type": "likert",
            "builder_type": "likert",
            "facet": facet,
            "evaluated_competency": facet,
            "reverse_scored": item.get("keying") == "-",
            "scale_labels": labels,
            "scale_points": len(labels) or 5,
            "options": [],
            "likert_label_1": labels[0] if labels else None,
            "likert_label_5": labels[min(4, len(labels) - 1)] if labels else None,
        }
    if instrument == "sjt" or item.get("options") and item.get("options")[0].get("tier"):
        options = [_option_text(o) for o in item.get("options") or []]
        weights = [int(o.get("points") or 0) for o in item.get("options") or []]
        return {
            "id": item_id,
            "text": text,
            "type": "sjt",
            "builder_type": "sjt",
            "facet": str(item.get("tag") or "Judgment"),
            "options": options,
            "option_weights": weights,
        }
    if instrument == "free_text_numeric" or str(item.get("type") or "") == "crt":
        accepted = list(item.get("correctAnswerAsWritten") or [])
        if item.get("correct") and str(item["correct"]) not in accepted:
            accepted.insert(0, str(item["correct"]))
        # TODO(owner): typed-variant matching lives in scoring.crt_credit.
        return {
            "id": item_id,
            "text": text,
            "type": "crt",
            "builder_type": "crt",
            "accepted_answers": accepted,
            "match": "numeric",
        }
    options_raw = [o for o in (item.get("options") or []) if isinstance(o, dict)]
    options = [_option_text(o) for o in options_raw]
    correct_letter = str(item.get("correct") or "").strip()
    correct_answer = next(
        (opt for opt, raw in zip(options, options_raw) if str(raw.get("label")) == correct_letter),
        correct_letter,
    )
    stored: dict[str, Any] = {
        "id": item_id,
        "text": text,
        "type": "mcq",
        "builder_type": "mcq",
        "facet": str(item.get("area") or "Cognitive"),
        "options": options,
        "allow_multiple": False,
        "correct_answer": correct_answer,
        "correct_keys": [
            i for i, raw in enumerate(options_raw) if str(raw.get("label")) == correct_letter
        ],
    }
    image = str(item.get("image") or "").strip()
    if image:
        stored["media_url"] = image
    return stored


def questions_for(module: dict[str, Any]) -> list[dict[str, Any]]:
    """Portal question bank for one catalog module.

    Args:
        module: Catalog module.

    Returns:
        Storage-shaped questions in authored order.
    """
    return [item_to_storage(module, item) for item in module.get("items") or []]


def _wrong_mcq(item: dict[str, Any]) -> str:
    correct = str(item.get("correct") or "")
    for option in item.get("options") or []:
        label = str(option.get("label") or "")
        if label and label != correct:
            return _option_text(option) if option.get("text") else label
    return "Z"


def vector_answers(module: dict[str, Any], vector: dict[str, Any]) -> dict[str, Any]:
    """Map a catalog test vector onto catalog item ids.

    Args:
        module: Catalog module.
        vector: ``testVectors`` entry.

    Returns:
        ``{item.id: answer}``.
    """
    items = list(module.get("items") or [])
    by_n = {int(item["n"]): item for item in items if "n" in item}
    by_id = {str(item["id"]): item for item in items}
    raw = vector.get("responses")
    if not raw:
        name = str(vector.get("name") or "")
        if name == "all_correct":
            answers: dict[str, Any] = {}
            for item in items:
                if item.get("correct"):
                    answers[str(item["id"])] = str(item["correct"])
                elif item.get("correctAnswerAsWritten"):
                    answers[str(item["id"])] = item["correctAnswerAsWritten"][0]
            return answers
        if name == "none_correct":
            answers = {}
            for item in items:
                if item.get("options"):
                    answers[str(item["id"])] = _wrong_mcq(item)
                else:
                    answers[str(item["id"])] = "0"
            return answers
        return {}
    mapped: dict[str, Any] = {}
    for key, value in raw.items():
        key_s = str(key)
        if key_s in by_id:
            mapped[key_s] = value
        elif key_s.isdigit() and int(key_s) in by_n:
            mapped[str(by_n[int(key_s)]["id"])] = value
    return mapped


def score_catalog_vector(module: dict[str, Any], vector: dict[str, Any]):
    """Score one catalog vector through the production engine.

    Args:
        module: Catalog module.
        vector: ``testVectors`` entry.

    Returns:
        ``ScoreResult`` plus ``{item.id: answer}``.
    """
    questions = questions_for(module)
    answers = vector_answers(module, vector)
    rows = [SimpleNamespace(question_id=qid, response={"answer": ans}) for qid, ans in answers.items()]
    return score_assessment_detailed(questions, rows), answers
