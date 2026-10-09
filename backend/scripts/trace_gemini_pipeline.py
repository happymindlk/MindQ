"""End-to-end Gemini pipeline trace for local ops (read-only against the DB).

Usage (from backend/ with venv active):
  python -m scripts.trace_gemini_pipeline [candidate_id]

Steps:
  1. Print resolved Gemini settings (key length only, never the key) incl. fallback.
  2. Trivial ping with token usage metadata.
  3. DB snapshot: today's candidate_evaluations / technical eval statuses.
  4. Real ``build_evidence`` + ``score_against_jd`` against a candidate, capturing
     the exact prompt size, raw response, and usage metadata. Nothing is persisted.

Exits 0 when both Gemini calls succeed, 1 otherwise.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_evaluation import CandidateEvaluation
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.package import Package
from app.prompts.jd_scoring import SYSTEM_INSTRUCTION, build_user_prompt
from app.schemas.jd_evaluation import JD_FIT_JSON_SCHEMA
from app.services.gemini_client import (
    fallback_models,
    generate_content_sync,
    overall_deadline_seconds,
)
from app.services.jd_scoring import (
    build_evidence,
    evaluation_is_ok,
    hash_job_description,
    parse_evaluation_json,
    resolve_job_description,
)

DEFAULT_CANDIDATE = "99a13504-be3c-41ff-9b5a-55e3c09610b0"


def _usage(response: Any) -> dict[str, Any]:
    """Extract token usage + model version from a GenAI response.

    Args:
        response: ``GenerateContentResponse``.

    Returns:
        Flat dict of usage counters (None when absent).
    """
    meta = getattr(response, "usage_metadata", None)
    return {
        "model_version": getattr(response, "model_version", None),
        "response_id": getattr(response, "response_id", None),
        "prompt_tokens": getattr(meta, "prompt_token_count", None),
        "candidates_tokens": getattr(meta, "candidates_token_count", None),
        "thoughts_tokens": getattr(meta, "thoughts_token_count", None),
        "total_tokens": getattr(meta, "total_token_count", None),
    }


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def step_settings() -> None:
    section("1. Settings")
    key = (settings.GEMINI_API_KEY or "").strip()
    print(f"GEMINI_API_KEY length={len(key)} prefix={key[:4]}…" if key else "GEMINI_API_KEY EMPTY")
    print(f"GEMINI_MODEL={settings.GEMINI_MODEL!r} fallback_chain={fallback_models()}")
    print(
        f"timeout_s={settings.GEMINI_TIMEOUT_SECONDS} max_retries={settings.GEMINI_MAX_RETRIES} "
        f"retry_base_s={settings.GEMINI_RETRY_BASE_SECONDS} "
        f"overall_deadline_s={overall_deadline_seconds():.1f}"
    )


def step_ping() -> bool:
    section("2. Trivial ping")
    from google.genai import types

    started = time.perf_counter()
    try:
        response = generate_content_sync(
            contents='Reply with JSON only: {"ok": true}',
            config=types.GenerateContentConfig(
                temperature=0, response_mime_type="application/json"
            ),
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic surface
        print(f"FAIL after {time.perf_counter() - started:.1f}s: {type(exc).__name__}: {exc}")
        return False
    print(f"OK in {time.perf_counter() - started:.1f}s text={(response.text or '').strip()!r}")
    print(f"usage={_usage(response)}")
    return True


async def step_db_snapshot(session: Any) -> None:
    section("3. DB snapshot (UTC today)")
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    evals_today = (
        await session.execute(
            select(func.count(CandidateEvaluation.id)).where(
                CandidateEvaluation.generated_at >= today
            )
        )
    ).scalar_one()
    evals_total = (await session.execute(select(func.count(CandidateEvaluation.id)))).scalar_one()
    print(f"candidate_evaluations generated today={evals_today} total={evals_total}")
    by_status = (
        await session.execute(
            select(CandidateEvaluation.status, func.count()).group_by(CandidateEvaluation.status)
        )
    ).all()
    print("candidate_evaluations by status:", {s: c for s, c in by_status})

    status_expr = CandidateResponse.response["ai_eval_status"].astext
    rows = (
        await session.execute(
            select(status_expr, func.count()).group_by(status_expr)
        )
    ).all()
    print("candidate_responses ai_eval_status counts:", {str(s): c for s, c in rows})

    completed_today = (
        await session.execute(
            select(func.count(CandidateProgress.id)).where(
                CandidateProgress.status == "COMPLETED",
                CandidateProgress.completed_at >= today,
            )
        )
    ).scalar_one()
    print(f"assessments submitted today={completed_today}")


async def step_jd_pipeline(session: Any, candidate_id: UUID) -> bool:
    section(f"4. JD synthesis for candidate {candidate_id}")
    candidate = (
        await session.execute(select(Candidate).where(Candidate.id == candidate_id))
    ).scalar_one_or_none()
    if candidate is None:
        print("FAIL: candidate not found")
        return False
    package = (
        await session.execute(select(Package).where(Package.id == candidate.package_id))
    ).scalar_one_or_none()
    assessments = (
        await session.execute(
            select(Assessment)
            .where(Assessment.package_id == candidate.package_id)
            .order_by(Assessment.position)
        )
    ).scalars().all()
    progresses = (
        await session.execute(
            select(CandidateProgress).where(CandidateProgress.candidate_id == candidate.id)
        )
    ).scalars().all()
    responses = (
        await session.execute(
            select(CandidateResponse).where(CandidateResponse.candidate_id == candidate.id)
        )
    ).scalars().all()

    print(
        f"package={package.title if package else None!r} assessments={len(assessments)} "
        f"progress={[(p.status, float(p.score) if p.score is not None else None) for p in progresses]} "
        f"responses={len(responses)}"
    )
    for row in responses:
        if isinstance(row.response, dict) and "ai_eval_status" in row.response:
            print(
                f"  response {row.question_id}: ai_eval_status={row.response.get('ai_eval_status')} "
                f"ai_score={row.response.get('ai_score')} "
                f"error={str(row.response.get('ai_eval_error') or '')[:120]!r}"
            )

    jd = resolve_job_description(package)
    if not jd:
        print("SKIP: no JD / role -> get_or_evaluate returns 'skipped' without calling Gemini")
        return False
    digest = hash_job_description(jd)
    cached = (
        await session.execute(
            select(CandidateEvaluation).where(CandidateEvaluation.candidate_id == candidate.id)
        )
    ).scalar_one_or_none()
    cache_hit = cached is not None and cached.jd_hash == digest and evaluation_is_ok(cached)
    print(
        f"jd_chars={len(jd)} jd_hash={digest[:12]} "
        f"cached_row={(cached.status if cached else 'none')} "
        f"cache_hit={'yes (Gemini would be bypassed)' if cache_hit else 'no'}"
    )
    if cached is not None and cached.last_error:
        print(f"last_error={cached.last_error[:200]!r}")

    evidence = build_evidence(assessments, progresses, responses)
    evidence_json = json.dumps(evidence, ensure_ascii=False, default=str)
    prompt = build_user_prompt(
        job_description=jd,
        candidate_name=candidate.full_name,
        package_title=package.title if package else "",
        evidence_json=evidence_json,
    )
    print(f"evidence_modules={len(evidence)} evidence_chars={len(evidence_json)} prompt_chars={len(prompt)}")
    for module in evidence:
        counts = {
            key: len(module.get(key) or [])
            for key in ("mcq", "sjt", "crt", "open_ended", "likert")
        }
        print(f"  {module['title']!r}: mcq_score={module['mcq_score']} items={counts}")
        for item in module.get("sjt") or []:
            print(
                f"    sjt competency={item['competency']!r} credit={item['credit']} "
                f"chosen={str(item['chosen_option'])[:60]!r}"
            )
        for item in module.get("crt") or []:
            print(f"    crt answer={item['answer']!r} reasoning={item['reasoning']}")

    from google.genai import types

    started = time.perf_counter()
    try:
        response = await asyncio.to_thread(
            generate_content_sync,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
                response_mime_type="application/json",
                response_json_schema=JD_FIT_JSON_SCHEMA,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic surface
        print(f"FAIL after {time.perf_counter() - started:.1f}s: {type(exc).__name__}: {exc}")
        return False
    raw = (response.text or "").strip()
    print(f"OK in {time.perf_counter() - started:.1f}s usage={_usage(response)}")
    print("raw response preview:", raw[:800])
    try:
        evaluation = parse_evaluation_json(raw)
    except Exception as exc:  # noqa: BLE001 - diagnostic surface
        print(f"FAIL: schema validation: {exc}")
        return False
    print(f"parsed overall_fit={evaluation.overall_fit} (not persisted)")
    return True


async def main() -> int:
    candidate_id = UUID(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CANDIDATE)
    step_settings()
    ping_ok = await asyncio.to_thread(step_ping)
    async with SessionLocal() as session:
        await step_db_snapshot(session)
        jd_ok = await step_jd_pipeline(session, candidate_id)
        await session.rollback()
    section("Result")
    print(f"ping={'PASS' if ping_ok else 'FAIL'} jd_synthesis={'PASS' if jd_ok else 'FAIL'}")
    return 0 if ping_ok and jd_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
