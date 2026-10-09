"""Job-description fit scoring (Gemini).

Triggered after the last test is submitted (background) and again on HR report
download (cache hit when possible). Answer keys are stripped from evidence.

Outcomes are persisted on ``candidate_evaluations.status``: ``ok`` rows carry the
payload; ``failed`` rows carry ``last_error`` and are retried on the next call.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.gemini_client import (
    GeminiUnavailable,
    generate_content_sync,
    overall_deadline_seconds,
    served_model,
)
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_evaluation import CandidateEvaluation
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.package import Package
from app.prompts.jd_scoring import SYSTEM_INSTRUCTION, build_user_prompt
from app.schemas.candidate import CandidateQuestion
from app.schemas.jd_evaluation import JD_FIT_JSON_SCHEMA, JdFitEvaluation
from app.services.profiles import DerivedProfile
from app.services.scoring import _extract_answer, crt_credit, sjt_credit
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

CompleteFn = Callable[[str], str]

EVAL_STATUS_OK = "ok"
EVAL_STATUS_FAILED = "failed"
_ERROR_MAX_CHARS = 1000


class JdScoringUnavailable(GeminiUnavailable):
    """Gemini is not configured or returned unusable JD-fit output."""


class ModelText(str):
    """Completion text tagged with the model that served it (fallback-aware)."""

    model: str | None = None

    @classmethod
    def tagged(cls, text: str, model: str | None) -> ModelText:
        out = cls(text)
        out.model = model
        return out


def evaluation_is_ok(row: CandidateEvaluation | None) -> bool:
    """True when a stored evaluation row holds a usable payload.

    Args:
        row: ``candidate_evaluations`` row (may be None).

    Returns:
        Whether readers should render ``row.payload``.
    """
    return bool(
        row is not None
        and (getattr(row, "status", None) or EVAL_STATUS_OK) == EVAL_STATUS_OK
        and isinstance(row.payload, dict)
        and row.payload
    )


def hash_job_description(job_description: str) -> str:
    return hashlib.sha256(job_description.strip().encode("utf-8")).hexdigest()


def resolve_job_description(package: Package | None) -> str:
    """Return the JD text used for fit scoring.

    Many packages ship without a pasted JD; scoring against the role/title still
    yields a useful executive summary instead of silently skipping.

    Args:
        package: Candidate's package (may be None).

    Returns:
        Description when present, else a synthesized role brief, else "".
    """
    if package is None:
        return ""
    description = (package.description or "").strip()
    if description:
        return description
    role = (getattr(package, "target_role", None) or package.title or "").strip()
    if not role:
        return ""
    return (
        f"Role: {role}\n"
        "No detailed job description was provided. Evaluate fit for this role "
        "based on the technical assessment evidence and typical expectations "
        "for the position."
    )


def _complete_profile(progress: CandidateProgress | None) -> dict[str, Any] | None:
    """Return the LLM-facing interpersonal profile when the resolver completed.

    Args:
        progress: Candidate progress row (may be None).

    Returns:
        ``{"resolver", "version", **data}`` for complete profiles, else None.
    """
    raw = getattr(progress, "derived_profile", None) if progress is not None else None
    if not raw:
        return None
    try:
        profile = DerivedProfile.model_validate(raw)
    except ValidationError:
        logger.warning(
            "jd_evidence_invalid_derived_profile assessment_id=%s",
            getattr(progress, "assessment_id", None),
        )
        return None
    if profile.status != "complete":
        return None
    return {"resolver": profile.resolver, "version": profile.version, **profile.data}


def _competency(question: dict[str, Any]) -> str | None:
    text = str(question.get("facet") or question.get("evaluated_competency") or "").strip()
    return text or None


def _is_blank(answer: Any) -> bool:
    if answer is None:
        return True
    if isinstance(answer, (list, tuple)):
        return not any(str(a).strip() for a in answer)
    return not str(answer).strip()


def _sjt_entry(question: dict[str, Any], text: str, given: Any) -> dict[str, Any]:
    """SJT evidence: the choice and its credit, never the option weights.

    Args:
        question: Stored SJT question (with ``option_weights``).
        text: Public scenario text.
        given: Candidate's extracted answer.

    Returns:
        ``{scenario, competency, chosen_option, credit}``.
    """
    if isinstance(given, (list, tuple)):
        given = given[0] if given else None
    credit = None if _is_blank(given) else sjt_credit(question, given)
    return {
        "scenario": text,
        "competency": _competency(question),
        "chosen_option": None if _is_blank(given) else str(given),
        "credit": None if credit is None else round(credit, 2),
    }


def crt_reasoning(question: dict[str, Any], given: Any) -> str:
    """Classify a CRT answer as reflective / intuitive / unanswered / ungraded.

    The question bank stores accepted answers but not the trap answer, so any
    unaccepted answer is reported as intuitive.

    Args:
        question: Stored CRT question (``accepted_answers``, ``match``).
        given: Candidate's extracted answer.

    Returns:
        One of ``reflective``, ``intuitive``, ``unanswered``, ``ungraded``.
    """
    if _is_blank(given):
        return "unanswered"
    credit = crt_credit(question, given)
    if credit is None:
        return "ungraded"
    return "reflective" if credit >= 1.0 else "intuitive"


def build_evidence(
    assessments: Iterable[Assessment],
    progresses: Iterable[CandidateProgress],
    responses: Iterable[CandidateResponse],
) -> list[dict[str, Any]]:
    """Public evidence blob: no correct_answer / is_correct keys."""
    progress_by_assessment = {p.assessment_id: p for p in progresses}
    responses_by_assessment: dict[UUID, list[CandidateResponse]] = {}
    for response in responses:
        responses_by_assessment.setdefault(response.assessment_id, []).append(response)

    evidence: list[dict[str, Any]] = []
    for assessment in assessments:
        progress = progress_by_assessment.get(assessment.id)
        resp_map = {
            str(r.question_id): _extract_answer(r.response)
            for r in responses_by_assessment.get(assessment.id, [])
        }
        open_ended: list[dict[str, Any]] = []
        likert: list[dict[str, Any]] = []
        mcq_selected: list[dict[str, Any]] = []
        sjt_choices: list[dict[str, Any]] = []
        crt_answers: list[dict[str, Any]] = []
        for raw in assessment.questions or []:
            if not isinstance(raw, dict):
                continue
            try:
                public = CandidateQuestion.model_validate(raw)
            except Exception:
                logger.warning(
                    "jd_evidence_skip_invalid_question assessment_id=%s", assessment.id
                )
                continue
            raw_given = resp_map.get(public.id)
            qtype = public.type.lower()
            if qtype == "sjt":
                sjt_choices.append(_sjt_entry(raw, public.text, raw_given))
                continue
            given = raw_given
            # Flatten leftover JSON objects so nested key names cannot trip integrity checks.
            if isinstance(given, (dict, list)):
                given = json.dumps(given, ensure_ascii=False, default=str)
            if qtype == "crt":
                crt_answers.append(
                    {
                        "question": public.text,
                        "answer": given,
                        "reasoning": crt_reasoning(raw, raw_given),
                    }
                )
            elif qtype == "open":
                entry: dict[str, Any] = {"question": public.text, "answer": given}
                rubric = raw.get("benchmark_rubric")
                if isinstance(rubric, str) and rubric.strip():
                    entry["benchmark_rubric"] = rubric.strip()
                open_ended.append(entry)
            elif qtype == "likert":
                likert.append({"question": public.text, "rating": given})
            elif qtype == "mcq":
                mcq_selected.append({"question": public.text, "selected": given})

        score = None
        if progress is not None and progress.score is not None:
            score = float(progress.score)
        entry_out: dict[str, Any] = {
            "title": assessment.title,
            "status": progress.status if progress else "NOT_STARTED",
            "mcq_score": score,
            "mcq": mcq_selected,
            "open_ended": open_ended,
        }
        if sjt_choices:
            entry_out["sjt"] = sjt_choices
        if crt_answers:
            entry_out["crt"] = crt_answers
        profile = _complete_profile(progress)
        # Withhold raw Likert ratings when a resolver already did the math, so
        # the model interprets the computed profile instead of re-deriving it.
        if profile is not None:
            entry_out["interpersonal_profile"] = profile
        else:
            entry_out["likert"] = likert
        evidence.append(entry_out)
    return evidence


def complete_with_gemini(user_prompt: str) -> str:
    from google.genai import types

    try:
        response = generate_content_sync(
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
                response_mime_type="application/json",
                response_json_schema=JD_FIT_JSON_SCHEMA,
            ),
        )
    except GeminiUnavailable as exc:
        raise JdScoringUnavailable(str(exc)) from exc
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise JdScoringUnavailable("Gemini returned an empty response")
    return ModelText.tagged(text, served_model(response, settings.GEMINI_MODEL))


def parse_evaluation_json(raw: str) -> JdFitEvaluation:
    """Accept raw JSON, including accidental markdown fences from the model."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    return JdFitEvaluation.model_validate_json(text)


_ANSWER_KEY_FIELDS = frozenset({"correct_answer", "is_correct"})
# benchmark_rubric is intentional JD context for Gemini, not a leaked MCQ key.


def assert_no_answer_key_fields(obj: Any) -> None:
    """Reject leaked key *fields*, not the substrings in candidate prose or code."""
    if isinstance(obj, dict):
        leaked = _ANSWER_KEY_FIELDS.intersection(obj)
        if leaked:
            raise RuntimeError(f"JD evidence leaked answer keys: {sorted(leaked)}")
        for value in obj.values():
            assert_no_answer_key_fields(value)
    elif isinstance(obj, list):
        for item in obj:
            assert_no_answer_key_fields(item)


def score_against_jd_with_model(
    *,
    job_description: str,
    candidate_name: str,
    package_title: str,
    evidence: list[dict[str, Any]],
    complete: CompleteFn | None = None,
) -> tuple[JdFitEvaluation, str]:
    """Score evidence against the JD and report which model produced the result.

    Args:
        job_description: JD text (or synthesized role brief).
        candidate_name: Candidate display name.
        package_title: Package title for context.
        evidence: Output of ``build_evidence``.
        complete: Optional completion stub (tests).

    Returns:
        Parsed evaluation and the serving model name.
    """
    assert_no_answer_key_fields(evidence)
    dumped = json.dumps(evidence, ensure_ascii=False, default=str)
    prompt = build_user_prompt(
        job_description=job_description,
        candidate_name=candidate_name,
        package_title=package_title,
        evidence_json=dumped,
    )
    raw = (complete or complete_with_gemini)(prompt)
    model = getattr(raw, "model", None) or settings.GEMINI_MODEL
    return parse_evaluation_json(raw), model


def score_against_jd(
    *,
    job_description: str,
    candidate_name: str,
    package_title: str,
    evidence: list[dict[str, Any]],
    complete: CompleteFn | None = None,
) -> JdFitEvaluation:
    """Score evidence against the JD.

    Args:
        job_description: JD text (or synthesized role brief).
        candidate_name: Candidate display name.
        package_title: Package title for context.
        evidence: Output of ``build_evidence``.
        complete: Optional completion stub (tests).

    Returns:
        Parsed evaluation.
    """
    evaluation, _model = score_against_jd_with_model(
        job_description=job_description,
        candidate_name=candidate_name,
        package_title=package_title,
        evidence=evidence,
        complete=complete,
    )
    return evaluation


class JdScoringService:
    @staticmethod
    async def get_or_evaluate(
        session: AsyncSession,
        *,
        candidate: Candidate,
        package: Package | None,
        assessments: list[Assessment],
        progresses: list[CandidateProgress],
        responses: list[CandidateResponse],
        complete: CompleteFn | None = None,
    ) -> tuple[JdFitEvaluation | None, str]:
        """Return cached or freshly generated JD fit.

        Status is one of: cached, generated, skipped, failed. Failures never raise
        to the report download path; they are persisted as ``status='failed'``
        rows (with ``last_error``) so HR and ops can see them, and retried on
        the next call.

        Args:
            session: Async SQLAlchemy session.
            candidate: Candidate being scored.
            package: Candidate's package (JD source).
            assessments: Package assessments.
            progresses: Candidate progress rows.
            responses: Candidate response rows.
            complete: Optional completion stub (tests).

        Returns:
            ``(evaluation | None, status)``.
        """
        jd = resolve_job_description(package)
        if not jd:
            logger.info("jd_scoring_skipped_no_role candidate_id=%s", candidate.id)
            return None, "skipped"

        digest = hash_job_description(jd)
        existing = (
            await session.execute(
                select(CandidateEvaluation).where(
                    CandidateEvaluation.candidate_id == candidate.id
                )
            )
        ).scalars().first()
        if existing and existing.jd_hash == digest and evaluation_is_ok(existing):
            try:
                return JdFitEvaluation.model_validate(existing.payload), "cached"
            except Exception:
                logger.warning(
                    "jd_scoring_cache_invalid candidate_id=%s", candidate.id
                )

        try:
            evidence = build_evidence(assessments, progresses, responses)
            evaluation, model = await asyncio.wait_for(
                run_in_threadpool(
                    score_against_jd_with_model,
                    job_description=jd,
                    candidate_name=candidate.full_name,
                    package_title=package.title if package else "",
                    evidence=evidence,
                    complete=complete,
                ),
                timeout=overall_deadline_seconds(),
            )
        except asyncio.TimeoutError:
            deadline = overall_deadline_seconds()
            logger.error(
                "jd_scoring_timeout candidate_id=%s timeout_s=%s", candidate.id, deadline
            )
            await JdScoringService._record_failure(
                session, candidate, existing, digest, f"timeout after {deadline:.0f}s"
            )
            return None, "failed"
        except Exception as exc:
            # Fail-soft for submit/report; the provider error is logged and persisted.
            logger.exception(
                "jd_scoring_failed candidate_id=%s error=%s", candidate.id, exc
            )
            await JdScoringService._record_failure(
                session, candidate, existing, digest, f"{type(exc).__name__}: {exc}"
            )
            return None, "failed"

        payload = evaluation.model_dump()
        now = datetime.now(timezone.utc)
        if existing:
            existing.jd_hash = digest
            existing.model = model
            existing.overall_fit = evaluation.overall_fit
            existing.payload = payload
            existing.status = EVAL_STATUS_OK
            existing.last_error = None
            existing.generated_at = now
        else:
            session.add(
                CandidateEvaluation(
                    corporate_id=candidate.corporate_id,
                    candidate_id=candidate.id,
                    package_id=candidate.package_id,
                    jd_hash=digest,
                    model=model,
                    overall_fit=evaluation.overall_fit,
                    payload=payload,
                    status=EVAL_STATUS_OK,
                    last_error=None,
                    generated_at=now,
                )
            )
        await session.commit()
        logger.info(
            "jd_scoring_generated candidate_id=%s model=%s overall_fit=%s",
            candidate.id,
            model,
            evaluation.overall_fit,
        )
        return evaluation, "generated"

    @staticmethod
    async def _record_failure(
        session: AsyncSession,
        candidate: Candidate,
        existing: CandidateEvaluation | None,
        digest: str,
        error: str,
    ) -> None:
        """Persist a ``failed`` evaluation row without raising into the caller.

        A failed row clears any payload scored against a different JD so readers
        never show a stale fit next to a failure.

        Args:
            session: Async SQLAlchemy session.
            candidate: Candidate being scored.
            existing: Current evaluation row, if any.
            digest: Hash of the JD the attempt used.
            error: Human-readable failure reason.
        """
        message = error[:_ERROR_MAX_CHARS]
        now = datetime.now(timezone.utc)
        try:
            if existing:
                existing.jd_hash = digest
                existing.model = settings.GEMINI_MODEL
                existing.overall_fit = None
                existing.payload = {}
                existing.status = EVAL_STATUS_FAILED
                existing.last_error = message
                existing.generated_at = now
            else:
                session.add(
                    CandidateEvaluation(
                        corporate_id=candidate.corporate_id,
                        candidate_id=candidate.id,
                        package_id=candidate.package_id,
                        jd_hash=digest,
                        model=settings.GEMINI_MODEL,
                        overall_fit=None,
                        payload={},
                        status=EVAL_STATUS_FAILED,
                        last_error=message,
                        generated_at=now,
                    )
                )
            await session.commit()
        except Exception:
            logger.exception(
                "jd_scoring_failure_record_failed candidate_id=%s", candidate.id
            )
            await session.rollback()
