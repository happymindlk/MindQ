"""One-off inspection: re-score Vishali / vishalivisha1927 live responses.

Fetches ``candidate_responses`` + ``candidate_progress`` for the target email,
dumps raw Likert answers for mini_ipip / hexaco_hh / ipip_ipc, then re-runs
``score_assessment_detailed`` (the live module scorer) and
``instrument_results.build_score_details``.

Usage (from backend/ with venv active and DATABASE_URL set):
  python -m scripts.inspect_candidate_scoring

From repo root (PYTHONPATH=backend):
  python -m scripts.inspect_candidate_scoring
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select

# Allow `python -m scripts.inspect_candidate_scoring` from repo root or backend/.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import SessionLocal
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.global_module import GlobalModule
from app.services.instrument_results import (
    _BIG_FIVE_KEYS,
    _BIG_FIVE_LABELS,
    _norm_key,
    build_score_details,
)
from app.services.scoring import score_assessment_detailed

TARGET_EMAIL = "vishalivisha1927@gmail.com"
TARGET_MODULES = ("mini_ipip", "hexaco_hh", "ipip_ipc")
EXPECTED_COUNTS = {"mini_ipip": 20, "hexaco_hh": 40, "ipip_ipc": 32}


def _pretty(value: Any) -> str:
    return json.dumps(value, indent=2, default=str, sort_keys=True)


def _answer_value(response: Any) -> Any:
    if isinstance(response, dict):
        if "answer" in response:
            return response.get("answer")
        if "value" in response:
            return response.get("value")
    return response


def _module_slug_for(assessment: Assessment, globals_by_id: dict) -> str | None:
    if assessment.global_module_id and assessment.global_module_id in globals_by_id:
        return str(globals_by_id[assessment.global_module_id].slug)
    title = (assessment.title or "").lower()
    for slug in TARGET_MODULES:
        if slug.replace("_", " ") in title or slug in title:
            return slug
    # Heuristic titles used in seeded packages.
    aliases = {
        "mini-ipip": "mini_ipip",
        "mini ipip": "mini_ipip",
        "hexaco": "hexaco_hh",
        "honesty": "hexaco_hh",
        "interpersonal": "ipip_ipc",
        "ipc": "ipip_ipc",
        "circumplex": "ipip_ipc",
    }
    for needle, slug in aliases.items():
        if needle in title:
            return slug
    return None


def _verify_uniform_catalog_replay() -> None:
    """Offline check: catalog Mini-IPIP with all answers=4 yields 5 Big Five facets."""
    from types import SimpleNamespace

    from app.services.psychometric_catalog import catalog_assessments, load_catalog, questions_for

    print("\n=== offline catalog replay (all answers=4, matching Vishali Mini-IPIP) ===")
    module = catalog_assessments(load_catalog())["mini_ipip"]
    questions = questions_for(module)
    rows = [
        SimpleNamespace(question_id=q["id"], response={"answer": 4}) for q in questions
    ]
    result = score_assessment_detailed(questions, rows)
    details = build_score_details(
        questions=questions, result=result, category="personality"
    )
    print("facet_scores:", _pretty(result.facet_scores))
    print(
        "subscales:",
        [row.get("name") for row in details.get("subscales") or []],
    )
    print("uniform_responding:", result.uniform_responding)
    assert len(details.get("subscales") or []) == 5
    assert any(
        row.get("name") == "Surgency or Extraversion"
        for row in details.get("subscales") or []
    )
    assert any(row.get("name") == "Neuroticism" for row in details.get("subscales") or [])
    print("OK: current engine emits all 5 Mini-IPIP facets.")


async def inspect() -> int:
    """Load the candidate, dump raw answers, and print live re-score output.

    Returns:
        Process exit code (0 ok, 1 candidate/module missing).
    """
    _verify_uniform_catalog_replay()

    async with SessionLocal() as session:
        candidates = (
            await session.execute(
                select(Candidate).where(Candidate.email.ilike(TARGET_EMAIL))
            )
        ).scalars().all()
        if not candidates:
            print(f"FAIL: no candidate with email {TARGET_EMAIL!r}")
            return 1

        print(f"candidates matched: {len(candidates)}")
        for cand in candidates:
            print(
                f"  id={cand.id} name={cand.full_name!r} "
                f"package={cand.package_id} created={cand.created_at}"
            )

        # Prefer the Vishali Suresh row when multiple packages share the email.
        candidate = next(
            (c for c in candidates if "vishali" in (c.full_name or "").lower()),
            candidates[-1],
        )
        print(f"\ninspecting candidate_id={candidate.id} name={candidate.full_name!r}")

        progress_rows = (
            await session.execute(
                select(CandidateProgress).where(
                    CandidateProgress.candidate_id == candidate.id
                )
            )
        ).scalars().all()
        assessment_ids = [p.assessment_id for p in progress_rows]
        assessments = (
            await session.execute(
                select(Assessment).where(Assessment.id.in_(assessment_ids))
            )
        ).scalars().all() if assessment_ids else []
        assessments_by_id = {a.id: a for a in assessments}

        global_ids = [a.global_module_id for a in assessments if a.global_module_id]
        globals_by_id: dict = {}
        if global_ids:
            rows = (
                await session.execute(
                    select(GlobalModule).where(GlobalModule.id.in_(global_ids))
                )
            ).scalars().all()
            globals_by_id = {g.id: g for g in rows}

        responses = (
            await session.execute(
                select(CandidateResponse).where(
                    CandidateResponse.candidate_id == candidate.id
                )
            )
        ).scalars().all()
        by_assessment: dict = {}
        for row in responses:
            by_assessment.setdefault(row.assessment_id, []).append(row)

        print("\n=== progress overview ===")
        for prog in progress_rows:
            a = assessments_by_id.get(prog.assessment_id)
            slug = _module_slug_for(a, globals_by_id) if a else None
            stored_facets = prog.facet_scores
            print(
                f"  assessment={a.title if a else prog.assessment_id!r} "
                f"slug={slug} status={prog.status} "
                f"score={prog.score} responses={len(by_assessment.get(prog.assessment_id, []))}"
            )
            if isinstance(stored_facets, dict):
                print(f"    stored facet keys: {sorted(stored_facets.keys())}")

        matched: dict[str, tuple[Assessment, CandidateProgress, list]] = {}
        for prog in progress_rows:
            a = assessments_by_id.get(prog.assessment_id)
            if not a:
                continue
            slug = _module_slug_for(a, globals_by_id)
            if slug in TARGET_MODULES and slug not in matched:
                matched[slug] = (a, prog, by_assessment.get(a.id, []))

        missing = [s for s in TARGET_MODULES if s not in matched]
        if missing:
            print(f"\nWARN: missing modules for this candidate: {missing}")

        for slug in TARGET_MODULES:
            if slug not in matched:
                continue
            assessment, prog, rows = matched[slug]
            questions = list(assessment.questions or [])
            q_by_id = {str(q.get("id")): q for q in questions if isinstance(q, dict)}
            expected_n = EXPECTED_COUNTS[slug]

            print(f"\n{'=' * 72}")
            print(f"MODULE {slug}  title={assessment.title!r}  items_in_bank={len(questions)}")
            print(f"{'=' * 72}")

            print(f"\n--- raw responses ({len(rows)} rows; expected {expected_n}) ---")
            answers: list[Any] = []
            for row in sorted(rows, key=lambda r: str(r.question_id)):
                qid = str(row.question_id)
                q = q_by_id.get(qid) or {}
                raw = _answer_value(row.response)
                answers.append(raw)
                facet = q.get("facet") or q.get("evaluated_competency") or "?"
                rev = bool(q.get("reverse_scored"))
                print(
                    f"  {qid:12} facet={facet!r:8} reverse={str(rev):5} "
                    f"answer={raw!r}  response={row.response!r}"
                )

            counts = Counter(str(a) for a in answers)
            print(f"\nanswer value histogram: {dict(counts)}")
            if answers and len(counts) == 1:
                print(
                    "UNIFORM RAW ANSWERS: every submitted value is identical "
                    f"({next(iter(counts))}). This is candidate input, not a median fallback."
                )
            elif not answers:
                print("NO RESPONSES STORED for this module.")
            else:
                print("Raw answers are NOT uniform across items.")

            # Re-score with current engine (score_assessment_detailed == live module scorer).
            result = score_assessment_detailed(questions, rows)
            details = build_score_details(
                questions=questions,
                result=result,
                derived_profile=prog.derived_profile if isinstance(prog.derived_profile, dict) else None,
                category=assessment.module_kind,
            )

            print("\n--- live facet_scores ---")
            print(_pretty(result.facet_scores))
            print(
                f"items_answered={result.items_answered}/{result.items_total} "
                f"uniform_responding={result.uniform_responding}"
            )

            print("\n--- live build_score_details ---")
            print(_pretty(details))

            if slug == "mini_ipip":
                facet_keys = {str(k) for k in (result.facet_scores or {})}
                mapped = []
                for key in facet_keys:
                    canon = _BIG_FIVE_KEYS.get(_norm_key(key))
                    mapped.append((key, canon, _BIG_FIVE_LABELS.get(canon or "", None)))
                print("\n--- Mini-IPIP Big Five key mapping ---")
                for raw, canon, label in sorted(mapped, key=lambda t: t[0]):
                    print(f"  raw={raw!r} -> canonical={canon!r} label={label!r}")
                subscale_names = [r.get("name") for r in details.get("subscales") or []]
                print(f"subscale names emitted: {subscale_names}")
                expected_labels = list(_BIG_FIVE_LABELS.values())
                missing_labels = [n for n in expected_labels if n not in subscale_names]
                if missing_labels:
                    print(f"MISSING FACETS: {missing_labels}")
                else:
                    print(
                        "OK: _BIG_FIVE_KEYS emits all 5 facets "
                        "(incl. Surgency or Extraversion + Neuroticism)."
                    )

            print("\n--- stored progress.facet_scores / score_details (for diff) ---")
            print("stored facet_scores:", _pretty(prog.facet_scores))
            print("stored score_details subscales:", _pretty(
                (prog.score_details or {}).get("subscales")
                if isinstance(prog.score_details, dict)
                else None
            ))

        print("\nDONE")
        return 0


def main() -> None:
    try:
        raise SystemExit(asyncio.run(inspect()))
    except ConnectionRefusedError as exc:
        print(
            "\nFAIL: database connection refused. "
            "Point DATABASE_URL at the live Supabase pooler (not local :54322), "
            "then re-run. Offline catalog replay above still validates facet emission."
        )
        print(f"detail: {exc}")
        raise SystemExit(2) from exc
    except OSError as exc:
        # asyncpg wraps refused connections in OSError on some platforms.
        if "refused" in str(exc).lower() or getattr(exc, "winerror", None) == 1225:
            print(
                "\nFAIL: database connection refused. "
                "Set DATABASE_URL to the remote project, then re-run."
            )
            print(f"detail: {exc}")
            raise SystemExit(2) from exc
        raise


if __name__ == "__main__":
    main()
