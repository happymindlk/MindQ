"""Content-addressed cache keys for rendered MindQ Report PDFs.

A cached PDF is reused only while every input it was rendered from is
unchanged. The key combines:

* ``narrative_hash``: the Gemini synthesis fields as they appear in the report.
* ``scores_hash``: every other report field (scores, bands, breakdown, item
  grades, candidate and company details, logo URL).
* ``template_hash``: the WeasyPrint template, so a layout change never serves
  a PDF rendered from the old template.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas.mindq_report import MindQReportResponse

# Bump to invalidate every cached PDF when rendering changes outside the template
# (WeasyPrint upgrade, fonts, ReportService context).
RENDER_VERSION = "3"

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "report.html"

NARRATIVE_FIELDS: frozenset[str] = frozenset(
    {
        "synthesis_status",
        "headline",
        "key_takeaways",
        "executive_summary",
        "role_alignment",
        "strengths",
        "areas_to_explore",
        "work_environment_notes",
        "interview_focus_areas",
        "verify_separately",
        "support_suggestions",
        "reliability_notes",
        "category_summaries",
    }
)


@dataclass(frozen=True)
class ReportCacheKey:
    """Composite cache key for one rendered report.

    Attributes:
        narrative_hash: SHA-256 over the synthesis fields.
        scores_hash: SHA-256 over every non-narrative field.
        key: SHA-256 over render version, template, narrative, and scores hashes.
    """

    narrative_hash: str
    scores_hash: str
    key: str


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def template_hash() -> str:
    """SHA-256 of the report template, read once per process.

    Returns:
        Hex digest of ``templates/report.html``.
    """
    return hashlib.sha256(_TEMPLATE_PATH.read_bytes()).hexdigest()


def report_cache_key(report: MindQReportResponse) -> ReportCacheKey:
    """Derive the cache key for a report payload.

    Args:
        report: Fully assembled report, exactly as it will be rendered.

    Returns:
        Narrative, scores, and combined hashes.
    """
    payload = report.model_dump(mode="json")
    narrative = {k: v for k, v in payload.items() if k in NARRATIVE_FIELDS}
    scores = {k: v for k, v in payload.items() if k not in NARRATIVE_FIELDS}
    narrative_hash = _digest(narrative)
    scores_hash = _digest(scores)
    key = hashlib.sha256(
        "\n".join((RENDER_VERSION, template_hash(), narrative_hash, scores_hash)).encode("utf-8")
    ).hexdigest()
    return ReportCacheKey(narrative_hash=narrative_hash, scores_hash=scores_hash, key=key)
