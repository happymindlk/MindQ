"""Per-question Gemini grading for technical open-ended items (custom and library).

Calls run sequentially with a short pause so free-tier RPM limits are not
burst. Results are merged into ``candidate_responses.response`` JSONB so
``GET /candidates/{id}/report-data`` can render ``ai_evaluation``.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_response import CandidateResponse
from app.prompts.technical_eval import SYSTEM_INSTRUCTION, build_user_prompt
from app.schemas.technical_eval import TECHNICAL_ITEM_JSON_SCHEMA, TechnicalItemEvaluation
from app.services.client_package import PSYCHOMETRIC
from app.services.gemini_client import GeminiUnavailable, generate_content_sync
from app.services.scoring import _extract_answer

logger = logging.getLogger(__name__)

CompleteItemFn = Callable[[str], str]

AI_EVAL_OK = "ok"
AI_EVAL_FAILED = "failed"
# Legacy status still treated as non-success so report backfill can retry.
AI_EVAL_UNAVAILABLE = "unavailable"
_RETRYABLE_STATUSES = frozenset({AI_EVAL_FAILED, AI_EVAL_UNAVAILABLE})
UNAVAILABLE_FEEDBACK = (
    "Evaluation pending or unavailable due to temporary upstream provider latency."
)

_OPEN_TYPES = frozenset(
    {"open", "open_ended", "short_answer", "essay", "written", "text"}
)
_SKIP_TYPES = frozenset({"mcq", "likert", "multiple_choice"})


def is_gradable_technical_assessment(assessment: Assessment) -> bool:
    """True for any technical assessment (custom bank or library module).

    Library modules (``global_module_id`` set) also carry open-ended items with
    ``benchmark_rubric``; only psychometric modules are excluded from grading.

    Args:
        assessment: Package assessment row.

    Returns:
        Whether open-ended items on this assessment should be Gemini-graded.
    """
    kind = (assessment.module_kind or "technical").strip().lower()
    return kind != PSYCHOMETRIC


def is_open_technical_question(question: dict[str, Any]) -> bool:
    """True when the item is written/open-ended (not MCQ/Likert)."""
    qtype = str(
        question.get("type")
        or question.get("question_type")
        or question.get("builder_type")
        or ""
    ).lower()
    if qtype in _SKIP_TYPES:
        return False
    if qtype in _OPEN_TYPES:
        return True
    # Custom rows sometimes omit type; treat missing as open if there is a prompt.
    return not qtype


def already_evaluated(response: Any) -> bool:
    """True when JSONB already holds a successful Gemini grade.

    Failed/unavailable fallback payloads return False so report download can retry.
    """
    if not isinstance(response, dict):
        return False
    if str(response.get("ai_eval_status") or "") in _RETRYABLE_STATUSES:
        return False
    text = response.get("ai_evaluation") or response.get("feedback")
    score = response.get("ai_score")
    return bool(isinstance(text, str) and text.strip()) and score is not None


def merge_evaluation_into_response(
    existing: Any, evaluation: TechnicalItemEvaluation
) -> dict[str, Any]:
    """Preserve the candidate answer and attach score / feedback / scorecard.

    Args:
        existing: Current ``candidate_responses.response`` JSONB (or scalar).
        evaluation: Parsed Gemini item evaluation.

    Returns:
        JSON-serializable dict safe to store as JSONB.
    """
    if isinstance(existing, dict):
        payload = dict(existing)
    elif existing is None:
        payload = {}
    else:
        payload = {"answer": existing}
    payload["ai_score"] = int(evaluation.score)
    payload["ai_evaluation"] = evaluation.feedback
    payload["feedback"] = evaluation.feedback
    payload["scorecard"] = list(evaluation.scorecard)
    payload["ai_eval_status"] = AI_EVAL_OK
    payload.pop("ai_eval_error", None)
    return payload


def merge_unavailable_into_response(existing: Any, reason: BaseException | str) -> dict[str, Any]:
    """Attach a structured fallback when Gemini times out, returns 5xx, or is unconfigured.

    Args:
        existing: Current ``candidate_responses.response`` JSONB.
        reason: Provider error (truncated onto ``ai_eval_error``).

    Returns:
        JSON-serializable dict with non-null ``ai_evaluation`` and ``ai_score: null``.
    """
    if isinstance(existing, dict):
        payload = dict(existing)
    elif existing is None:
        payload = {}
    else:
        payload = {"answer": existing}
    payload["ai_score"] = None
    payload["ai_evaluation"] = UNAVAILABLE_FEEDBACK
    payload["feedback"] = UNAVAILABLE_FEEDBACK
    payload["ai_eval_status"] = AI_EVAL_FAILED
    payload["ai_eval_error"] = str(reason)[:400]
    return payload


def _persist_response(row: Any, payload: dict[str, Any]) -> None:
    """Assign JSONB and mark the column dirty so SQLAlchemy commits the change.

    Args:
        row: ``CandidateResponse`` ORM row (or a test double with ``.response``).
        payload: Merged response JSONB to persist.
    """
    row.response = payload
    # Unit tests pass SimpleNamespace; only flag real mapped instances.
    if hasattr(row, "_sa_instance_state"):
        flag_modified(row, "response")


def parse_item_evaluation_json(raw: str) -> TechnicalItemEvaluation:
    """Parse Gemini JSON, including accidental markdown fences."""
    # Reuse fence stripping from JD scoring without importing JdFitEvaluation.
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    return TechnicalItemEvaluation.model_validate_json(text)


def complete_item_with_gemini(user_prompt: str) -> str:
    """One Gemini JSON completion for a technical item (retried internally).

    Args:
        user_prompt: Built item-grading prompt.

    Returns:
        Raw JSON text.

    Raises:
        GeminiUnavailable: Missing key or empty model response.
    """
    from google.genai import types

    response = generate_content_sync(
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.2,
            response_mime_type="application/json",
            response_json_schema=TECHNICAL_ITEM_JSON_SCHEMA,
        ),
    )
    text = (getattr(response, "text", None) or "").strip()
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, TechnicalItemEvaluation):
        return parsed.model_dump_json()
    if isinstance(parsed, dict):
        return TechnicalItemEvaluation.model_validate(parsed).model_dump_json()
    if not text:
        raise GeminiUnavailable("Gemini returned an empty technical evaluation")
    return text


def evaluate_item(
    *,
    question: dict[str, Any],
    answer: Any,
    complete: CompleteItemFn | None = None,
) -> TechnicalItemEvaluation:
    """Grade one open-ended custom technical question.

    Args:
        question: Assessment question dict (may include keys; not sent as fields).
        answer: Extracted candidate answer.
        complete: Optional stub returning JSON (unit tests).

    Returns:
        Validated ``TechnicalItemEvaluation``.
    """
    prompt_text = str(question.get("prompt") or question.get("text") or "").strip()
    competency = str(question.get("evaluated_competency") or "Technical").strip()
    rubric = str(
        question.get("benchmark_rubric")
        or question.get("correct_answer_or_rubric")
        or ""
    ).strip()
    if isinstance(answer, (dict, list)):
        import json

        answer_text = json.dumps(answer, ensure_ascii=False, default=str)
    else:
        answer_text = "" if answer is None else str(answer)
    user_prompt = build_user_prompt(
        question=prompt_text,
        answer=answer_text,
        rubric=rubric,
        competency=competency,
    )
    raw = (complete or complete_item_with_gemini)(user_prompt)
    return parse_item_evaluation_json(raw)


def _question_id(question: dict[str, Any]) -> str:
    return str(question.get("id") or "").strip()


class TechnicalEvalService:
    @staticmethod
    async def evaluate_assessment(
        session: AsyncSession,
        *,
        candidate: Candidate,
        assessment: Assessment,
        complete: CompleteItemFn | None = None,
        force: bool = False,
    ) -> int:
        """Grade open-ended technical items sequentially; persist into responses.

        Args:
            session: Async SQLAlchemy session.
            candidate: Candidate who submitted the assessment.
            assessment: Submitted assessment.
            complete: Optional Gemini stub for tests.
            force: Re-grade even when ``ai_evaluation`` is already stored.

        Returns:
            Number of items written (success or structured fallback).
        """
        if not is_gradable_technical_assessment(assessment):
            return 0

        questions = [q for q in (assessment.questions or []) if isinstance(q, dict)]
        open_items = [q for q in questions if is_open_technical_question(q) and _question_id(q)]
        if not open_items:
            return 0

        rows = (
            await session.execute(
                select(CandidateResponse).where(
                    CandidateResponse.candidate_id == candidate.id,
                    CandidateResponse.assessment_id == assessment.id,
                )
            )
        ).scalars().all()
        by_qid = {str(row.question_id): row for row in rows}

        no_key = complete is None and not (settings.GEMINI_API_KEY or "").strip()
        logger.info(
            "technical_eval_start candidate_id=%s assessment_id=%s open_items=%s no_key=%s",
            candidate.id,
            assessment.id,
            len(open_items),
            no_key,
        )

        stored = 0
        throttle = max(0.0, float(settings.GEMINI_INTER_REQUEST_SECONDS))
        for index, question in enumerate(open_items):
            qid = _question_id(question)
            row = by_qid.get(qid)
            if row is None:
                logger.info(
                    "technical_eval_skip_missing_row candidate_id=%s question_id=%s",
                    candidate.id,
                    qid,
                )
                continue
            if not force and already_evaluated(row.response):
                continue

            if no_key:
                logger.error(
                    "technical_eval_no_api_key candidate_id=%s question_id=%s",
                    candidate.id,
                    qid,
                )
                _persist_response(
                    row,
                    merge_unavailable_into_response(
                        row.response, "GEMINI_API_KEY is not set"
                    ),
                )
                stored += 1
                continue

            answer = _extract_answer(row.response)
            try:
                # The SDK call blocks for the whole retry/fallback window; keep it
                # off the event loop so other requests are served meanwhile.
                evaluation = await asyncio.to_thread(
                    evaluate_item, question=question, answer=answer, complete=complete
                )
            except Exception as exc:
                logger.exception(
                    "technical_eval_item_failed candidate_id=%s question_id=%s",
                    candidate.id,
                    qid,
                )
                _persist_response(
                    row, merge_unavailable_into_response(row.response, exc)
                )
                stored += 1
                if throttle and index < len(open_items) - 1:
                    await asyncio.sleep(throttle)
                continue

            feedback_preview = (evaluation.feedback or "")[:120]
            logger.info(
                "technical_eval_gemini_ok candidate_id=%s question_id=%s score=%s feedback=%r",
                candidate.id,
                qid,
                evaluation.score,
                feedback_preview,
            )
            _persist_response(
                row, merge_evaluation_into_response(row.response, evaluation)
            )
            stored += 1
            if throttle and index < len(open_items) - 1:
                await asyncio.sleep(throttle)

        if stored:
            try:
                await session.commit()
                logger.info(
                    "technical_eval_committed candidate_id=%s assessment_id=%s stored=%s",
                    candidate.id,
                    assessment.id,
                    stored,
                )
            except Exception:
                logger.exception(
                    "technical_eval_commit_failed candidate_id=%s assessment_id=%s stored=%s",
                    candidate.id,
                    assessment.id,
                    stored,
                )
                raise
        logger.info(
            "technical_eval_done candidate_id=%s assessment_id=%s stored=%s",
            candidate.id,
            assessment.id,
            stored,
        )
        return stored

    @staticmethod
    def has_missing_open_evals(
        assessments: list[Assessment],
        responses_by_assessment: dict[Any, dict[str, Any]],
    ) -> bool:
        """True when a technical open-ended item still needs a successful grade."""
        for assessment in assessments:
            if not is_gradable_technical_assessment(assessment):
                continue
            resp_map = responses_by_assessment.get(assessment.id) or {}
            for question in assessment.questions or []:
                if not isinstance(question, dict) or not is_open_technical_question(question):
                    continue
                qid = _question_id(question)
                if not qid:
                    continue
                if not already_evaluated(resp_map.get(qid)):
                    return True
        return False

    @staticmethod
    async def evaluate_candidate(
        session: AsyncSession,
        *,
        candidate: Candidate,
        assessments: list[Assessment],
        progress_rows: list[Any] | None = None,
        complete: CompleteItemFn | None = None,
    ) -> int:
        """Grade custom technical items for assessments the candidate has submitted.

        Args:
            session: Async SQLAlchemy session.
            candidate: Candidate whose responses should be graded.
            assessments: Package assessments (psychometric rows are skipped).
            progress_rows: When provided, only ``COMPLETED`` assessments are graded.
            complete: Optional Gemini stub for tests.

        Returns:
            Number of response rows written (success or fallback).
        """
        completed_ids: set[Any] | None = None
        if progress_rows is not None:
            completed_ids = {
                p.assessment_id
                for p in progress_rows
                if str(getattr(p, "status", "")).upper() == "COMPLETED"
            }
        total = 0
        for assessment in assessments:
            if completed_ids is not None and assessment.id not in completed_ids:
                continue
            total += await TechnicalEvalService.evaluate_assessment(
                session,
                candidate=candidate,
                assessment=assessment,
                complete=complete,
            )
        return total
