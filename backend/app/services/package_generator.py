"""Gemini-powered Assessment Package Builder.

Generates structured assessment blueprints from job descriptions and maps them
into the packages / assessments persistence shape used by the candidate portal.
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.gemini_client import GeminiUnavailable, generate_content_async
from app.models.assessment import Assessment
from app.models.package import Package
from app.prompts.package_builder import SYSTEM_INSTRUCTION, build_user_prompt
from app.schemas.package_builder import (
    AssessmentPackageBlueprint,
    DifficultyLevel,
    QuestionItem,
    QuestionType,
)

logger = logging.getLogger(__name__)

_ACCESS_ALPHABET = string.ascii_uppercase + string.digits


class PackageGeneratorError(Exception):
    """Raised when Gemini is unavailable or returns an unusable blueprint."""


def _slug_id(index: int, prompt: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in prompt.lower())
    slug = "-".join(part for part in slug.split("-") if part)[:18] or "item"
    return f"q-{index}-{slug}"


def blueprint_question_to_storage(item: QuestionItem, index: int) -> dict[str, Any]:
    """Map a blueprint item into the assessments.questions JSONB shape.

    Args:
        item: Generated or manually authored question item.
        index: Zero-based position used for stable ids.

    Returns:
        Dict compatible with the candidate portal and scoring pipeline.
        Portal types: ``mcq``, ``likert``, ``open`` (from builder ``open_ended``).
    """
    qid = _slug_id(index, item.prompt)
    if item.question_type == QuestionType.mcq:
        options = [str(o).strip() for o in (item.options or []) if str(o).strip()]
        answer = (item.correct_answer_or_rubric or "").strip()
        return {
            "id": qid,
            "text": item.prompt.strip(),
            "type": "mcq",
            "options": options,
            "correct_answer": answer,
            "evaluated_competency": item.evaluated_competency,
            "weight": item.weight,
            "builder_type": item.question_type.value,
        }

    if item.question_type == QuestionType.likert:
        low = (item.likert_label_1 or "Strongly Disagree").strip()
        high = (item.likert_label_5 or "Strongly Agree").strip()
        return {
            "id": qid,
            "text": item.prompt.strip(),
            "type": "likert",
            "options": [],
            "likert_label_1": low,
            "likert_label_5": high,
            "evaluated_competency": item.evaluated_competency,
            "weight": item.weight,
            "builder_type": item.question_type.value,
        }

    # open_ended → portal type "open" with benchmark rubric for JD fit.
    return {
        "id": qid,
        "text": item.prompt.strip(),
        "type": "open",
        "options": [],
        "benchmark_rubric": (item.correct_answer_or_rubric or "").strip(),
        "evaluated_competency": item.evaluated_competency,
        "weight": item.weight,
        "builder_type": item.question_type.value,
    }


def _mint_access_code() -> str:
    """Mint an HM-XXXXXX-C style access code (matches public.gen_access_code)."""
    body = "".join(secrets.choice(_ACCESS_ALPHABET) for _ in range(6))
    checksum = sum(ord(ch) for ch in body) % len(_ACCESS_ALPHABET)
    check_char = _ACCESS_ALPHABET[checksum]
    return f"HM-{body}-{check_char}"


async def generate_package_from_jd(
    role: str,
    job_description: str,
    seniority: DifficultyLevel | str,
    question_count: int = 10,
) -> AssessmentPackageBlueprint:
    """Generate an assessment blueprint from a JD via Gemini structured output.

    Args:
        role: Role title for the package.
        job_description: Full job description text.
        seniority: Target seniority band.
        question_count: Desired number of questions (default 10).

    Returns:
        Validated `AssessmentPackageBlueprint`.

    Raises:
        PackageGeneratorError: When Gemini is not configured or returns bad data.
    """
    if not settings.GEMINI_API_KEY:
        raise PackageGeneratorError("GEMINI_API_KEY is not set")

    seniority_value = (
        seniority.value if isinstance(seniority, DifficultyLevel) else str(seniority)
    )
    prompt = build_user_prompt(
        role=role.strip(),
        job_description=job_description,
        seniority=seniority_value,
        question_count=question_count,
    )

    try:
        from google.genai import types
    except ImportError as exc:
        raise PackageGeneratorError("google-genai is not installed") from exc

    try:
        response = await generate_content_async(
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.35,
                response_mime_type="application/json",
                response_schema=AssessmentPackageBlueprint,
            ),
        )
    except GeminiUnavailable as exc:
        raise PackageGeneratorError(str(exc)) from exc
    except Exception as exc:
        logger.exception("package_generator_gemini_failed")
        raise PackageGeneratorError(f"Gemini generation failed: {exc}") from exc

    # Prefer parsed structured output when the SDK populates it.
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, AssessmentPackageBlueprint):
        blueprint = parsed
    elif isinstance(parsed, dict):
        blueprint = AssessmentPackageBlueprint.model_validate(parsed)
    else:
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise PackageGeneratorError("Gemini returned an empty response")
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
        try:
            blueprint = AssessmentPackageBlueprint.model_validate_json(text)
        except Exception as exc:
            raise PackageGeneratorError(
                f"Gemini returned invalid blueprint JSON: {exc}"
            ) from exc

    if not blueprint.questions:
        raise PackageGeneratorError("Gemini returned a blueprint with no questions")

    # Prefer the HR-supplied role/seniority when the model drifts.
    if role.strip():
        blueprint.role = role.strip()
    blueprint.target_seniority = DifficultyLevel(seniority_value)
    return blueprint


async def save_blueprint_package(
    session: AsyncSession,
    *,
    corporate_id: UUID,
    blueprint: AssessmentPackageBlueprint,
    job_description: str = "",
) -> Package:
    """Persist an approved blueprint as a package + single assessment.

    Questions are stored in `assessments.questions` JSONB (there is no
    `package_questions` table). The JD is stored on `packages.description`
    for downstream Gemini JD-fit scoring.

    Args:
        session: Async SQLAlchemy session.
        corporate_id: Authenticated HR tenant id.
        blueprint: Approved assessment blueprint.
        job_description: Original JD text to store on the package.

    Returns:
        The newly created `Package` row (with access_code populated).
    """
    access_code = _mint_access_code()
    for _ in range(8):
        exists = (
            await session.execute(
                select(Package.id).where(Package.access_code == access_code)
            )
        ).scalar_one_or_none()
        if exists is None:
            break
        access_code = _mint_access_code()

    # Prefer DB function when available (same checksum alphabet / collision loop).
    try:
        db_code = (
            await session.execute(text("select public.gen_access_code()"))
        ).scalar_one()
        if isinstance(db_code, str) and db_code.strip():
            access_code = db_code.strip()
    except Exception:
        logger.debug("gen_access_code_unavailable_using_local_mint", exc_info=True)

    description = (job_description or "").strip() or None
    package = Package(
        corporate_id=corporate_id,
        title=blueprint.title.strip()[:255],
        description=description,
        access_code=access_code,
        is_active=True,
        status="published",
        published_at=datetime.now(timezone.utc),
    )
    session.add(package)
    await session.flush()

    stored_questions = [
        blueprint_question_to_storage(q, i) for i, q in enumerate(blueprint.questions)
    ]
    competencies = ", ".join(blueprint.competencies_targeted[:12])
    assessment = Assessment(
        corporate_id=corporate_id,
        package_id=package.id,
        title=f"{blueprint.role} Assessment".strip()[:255] or blueprint.title[:255],
        description=(
            f"AI-generated for {blueprint.target_seniority.value} · "
            f"~{blueprint.estimated_duration_minutes} min"
            + (f" · Competencies: {competencies}" if competencies else "")
        ),
        time_limit_minutes=blueprint.estimated_duration_minutes,
        position=0,
        questions=stored_questions,
        module_kind="technical",
    )
    session.add(assessment)
    await session.commit()
    await session.refresh(package)
    return package
