"""MindQ Report synthesis (Gemini): narrative sections for the v5 report.

Generated only in background tasks: after the last test is submitted, and when
a report view finds the cache missing, stale, or failed past its cooldown.
Report views read the cache via ``read_cached`` and never wait on Gemini.
Answer keys are stripped from evidence.
The cache key covers the prompt version, the role brief, and the completed
scores, so a prompt change or a re-graded assessment regenerates the synthesis.

Outcomes are persisted on ``candidate_evaluations.status``: ``ok`` rows carry the
payload; ``failed`` rows carry ``last_error`` and are retried on the next call.
Banned-language matches after one retry are held for manual review (``failed``).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_evaluation import CandidateEvaluation
from app.models.candidate_progress import CandidateProgress
from app.models.candidate_response import CandidateResponse
from app.models.package import Package
from app.prompts.jd_scoring import PROMPT_VERSION, SYSTEM_INSTRUCTION, build_user_prompt
from app.schemas.candidate import CandidateQuestion
from app.schemas.jd_evaluation import (
    CAPABILITY_KEYS,
    REPORT_NARRATIVE_JSON_SCHEMA,
    ReportNarrative,
)
from app.services.gemini_client import (
    GeminiUnavailable,
    generate_content_sync,
    overall_deadline_seconds,
    served_model,
)
from app.services.instrument_results import sjt_item_tier
from app.services.profiles import DerivedProfile
from app.services.report_synthesis import (
    ModuleOutcome,
    build_module_outcomes,
    load_catalog_categories,
    outcomes_fingerprint,
    prompt_assessments,
)
from app.services.scoring import _extract_answer, _parse_number, crt_credit, sjt_credit

logger = logging.getLogger(__name__)

CompleteFn = Callable[[str], str]

EVAL_STATUS_OK = "ok"
EVAL_STATUS_FAILED = "failed"
BANNED_LANGUAGE_ERROR = "banned_language_held_for_review"
_ERROR_MAX_CHARS = 1000
# Report polling re-reads the cache every few seconds; a failed synthesis is
# only re-queued after this cooldown so a persistent provider outage cannot
# turn each poll into a paid Gemini call.
FAILED_RETRY_COOLDOWN = timedelta(minutes=5)

CacheState = Literal["ok", "skipped", "missing", "stale", "failed"]


@dataclass(frozen=True)
class CachedSynthesis:
    """Result of a read-only synthesis cache lookup.

    Attributes:
        narrative: Stored synthesis when ``state == "ok"``.
        state: ``ok`` (usable), ``skipped`` (no role brief or outcomes),
            ``missing`` (never generated), ``stale`` (scores, role, or prompt
            changed), or ``failed`` (last attempt failed for these inputs).
        needs_refresh: True when a background regeneration should be queued.
    """

    narrative: ReportNarrative | None
    state: CacheState
    needs_refresh: bool

# Longest phrases first so "mood swings" / "cold-hearted" match before singles.
_BANNED_PHRASES: tuple[str, ...] = (
    "mood swings",
    "cold-hearted",
    "cold hearted",
    "red flag",
    "high risk",
    "poor performer",
    "moody",
    "anxious",
    "anxiety",
    "nervous",
    "neurotic",
    "unstable",
    "fragile",
    "emotional",
    "dishonest",
    "deceitful",
    "untrustworthy",
    "manipulative",
    "arrogant",
    "aggressive",
    "cold",
    "lazy",
    "immature",
    "weak",
    "unfit",
    "failed",
    "fail",
    "disqualifying",
)
_BANNED_PATTERN = re.compile(
    r"(?<!\w)("
    + "|".join(re.escape(p).replace(r"\ ", r"[\s\-]+") for p in _BANNED_PHRASES)
    + r")(?!\w)",
    re.IGNORECASE,
)


class JdScoringUnavailable(GeminiUnavailable):
    """Gemini is not configured or returned unusable JD-fit output."""


class BannedLanguageError(JdScoringUnavailable):
    """Synthesis prose contained banned wording after retry."""

    def __init__(self, matches: list[str]) -> None:
        self.matches = matches
        super().__init__(f"{BANNED_LANGUAGE_ERROR}: {', '.join(matches)}")


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


def synthesis_cache_key(job_description: str, outcomes: list[ModuleOutcome]) -> str:
    """Cache key for a stored synthesis.

    Args:
        job_description: Resolved role brief.
        outcomes: Completed module outcomes the synthesis is written against.

    Returns:
        Hex SHA-256 over prompt version, role brief, and completed scores.
    """
    material = "\n".join(
        (PROMPT_VERSION, hash_job_description(job_description), outcomes_fingerprint(outcomes))
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


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
    """SJT evidence: theme and credit tier, never the chosen option text.

    Args:
        question: Stored SJT question (with ``option_weights``).
        text: Public scenario text.
        given: Candidate's extracted answer.

    Returns:
        ``{theme, competency, credit, credit_tier}``.
    """
    if isinstance(given, (list, tuple)):
        given = given[0] if given else None
    credit = None if _is_blank(given) else sjt_credit(question, given)
    theme = _competency(question) or (text.strip()[:80] if text else "scenario")
    return {
        "theme": theme,
        "competency": _competency(question),
        "credit": None if credit is None else round(credit, 2),
        "credit_tier": None if credit is None else sjt_item_tier(credit),
    }


_CRT_TRAP_NUMBERS = frozenset({10.0, 0.10, 100.0, 24.0})


def crt_reasoning(question: dict[str, Any], given: Any) -> str:
    """Classify a CRT answer as reflective / intuitive / other / unanswered / ungraded.

    Known lure answers (10 cents, 100 minutes, 24 days) are intuitive; any other
    unaccepted answer is ``other``.

    Args:
        question: Stored CRT question (``accepted_answers``, ``match``).
        given: Candidate's extracted answer.

    Returns:
        One of ``reflective``, ``intuitive``, ``other``, ``unanswered``, ``ungraded``.
    """
    if _is_blank(given):
        return "unanswered"
    credit = crt_credit(question, given)
    if credit is None:
        return "ungraded"
    if credit >= 1.0:
        return "reflective"
    number = _parse_number(given)
    text = str(given).casefold()
    if number in _CRT_TRAP_NUMBERS or "10 cent" in text or "100 minute" in text or "24 day" in text:
        return "intuitive"
    return "other"


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
                continue
            elif qtype == "mcq":
                kind = str(getattr(assessment, "module_kind", "") or "technical").lower()
                if kind != "psychometric":
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
        # Withhold raw Likert ratings; facet means (and IPC profile) are authoritative.
        if profile is not None:
            entry_out["interpersonal_profile"] = profile
        facet_scores = getattr(progress, "facet_scores", None) if progress is not None else None
        if isinstance(facet_scores, dict) and facet_scores:
            entry_out["facet_means"] = {
                str(name): (
                    {"mean": value.get("mean"), "n": value.get("n")}
                    if isinstance(value, dict)
                    else value
                )
                for name, value in facet_scores.items()
            }
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
                response_json_schema=REPORT_NARRATIVE_JSON_SCHEMA,
            ),
        )
    except GeminiUnavailable as exc:
        raise JdScoringUnavailable(str(exc)) from exc
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise JdScoringUnavailable("Gemini returned an empty response")
    return ModelText.tagged(text, served_model(response, settings.GEMINI_MODEL))


def parse_evaluation_json(raw: str) -> ReportNarrative:
    """Accept raw JSON, including accidental markdown fences from the model."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    return ReportNarrative.model_validate_json(text)


def find_banned_words(obj: Any) -> list[str]:
    """Scan every string in a nested payload for banned wording.

    Args:
        obj: Parsed synthesis (model dump or nested structure).

    Returns:
        Deduplicated list of matched banned phrases (lowercase).
    """
    found: list[str] = []
    seen: set[str] = set()

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            for match in _BANNED_PATTERN.finditer(value):
                token = match.group(1).lower()
                if token not in seen:
                    seen.add(token)
                    found.append(token)
        elif isinstance(value, dict):
            for child in value.values():
                _walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                _walk(child)

    _walk(obj)
    return found


def assert_no_banned_words(narrative: ReportNarrative) -> None:
    """Raise when any banned word appears in the narrative.

    Args:
        narrative: Validated Gemini synthesis.

    Raises:
        BannedLanguageError: When one or more banned phrases are present.
    """
    matches = find_banned_words(narrative.model_dump())
    if matches:
        raise BannedLanguageError(matches)


def validate_narrative_keys(
    narrative: ReportNarrative,
    assessment_scores: list[dict[str, Any]] | None,
) -> None:
    """Ensure assessment and capability keys match the prompt contract.

    Args:
        narrative: Validated Gemini synthesis.
        assessment_scores: Server-computed score table sent to Gemini.

    Raises:
        JdScoringUnavailable: When keys are unexpected or missing.
    """
    expected = {str(row["assessment_key"]) for row in assessment_scores or []}
    got = {item.assessment_key.strip() for item in narrative.competency_breakdown}
    if expected:
        unexpected = got - expected
        if unexpected:
            raise JdScoringUnavailable(
                f"report_synthesis_unexpected_assessment_keys: {sorted(unexpected)}"
            )
        missing = expected - got
        if missing:
            logger.warning(
                "report_synthesis_missing_summaries keys=%s", sorted(missing)
            )
    bad_caps = [
        item.capability_key
        for item in narrative.role_alignment
        if item.capability_key not in CAPABILITY_KEYS
    ]
    if bad_caps:
        raise JdScoringUnavailable(
            f"report_synthesis_invalid_capability_keys: {sorted(set(bad_caps))}"
        )
    psychometric = {"Cognitive", "Personality", "Behavioral"}
    expected_categories = {
        str(row.get("category")) for row in assessment_scores or []
    } & psychometric
    missing_categories = expected_categories - set(narrative.summaries_by_category())
    if missing_categories:
        logger.warning(
            "report_synthesis_missing_category_summaries categories=%s",
            sorted(missing_categories),
        )


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


def _parse_and_validate(
    raw: str,
    assessment_scores: list[dict[str, Any]] | None,
) -> ReportNarrative:
    narrative = parse_evaluation_json(raw)
    validate_narrative_keys(narrative, assessment_scores)
    assert_no_banned_words(narrative)
    return narrative


def score_against_jd_with_model(
    *,
    job_description: str,
    candidate_name: str,
    package_title: str,
    evidence: list[dict[str, Any]],
    assessment_scores: list[dict[str, Any]] | None = None,
    target_role: str = "",
    complete: CompleteFn | None = None,
) -> tuple[ReportNarrative, str]:
    """Generate the report synthesis and report which model produced it.

    Retries once on parse, key, or banned-word failure. Persistent banned
    language raises ``BannedLanguageError`` so the caller can hold the report
    for manual review.

    Args:
        job_description: JD text (or synthesized role brief).
        candidate_name: Candidate display name.
        package_title: Package title for context.
        evidence: Output of ``build_evidence``.
        assessment_scores: Output of ``prompt_assessments`` (server-computed).
        target_role: Role the candidate is assessed for.
        complete: Optional completion stub (tests).

    Returns:
        Parsed synthesis and the serving model name.
    """
    assert_no_answer_key_fields(evidence)
    prompt = build_user_prompt(
        target_role=target_role,
        job_description=job_description,
        candidate_name=candidate_name,
        package_title=package_title,
        assessment_scores_json=json.dumps(assessment_scores or [], ensure_ascii=False),
        evidence_json=json.dumps(evidence, ensure_ascii=False, default=str),
    )
    completer = complete or complete_with_gemini
    last_error: Exception | None = None
    model = settings.GEMINI_MODEL
    for attempt in range(2):
        try:
            raw = completer(prompt)
            model = getattr(raw, "model", None) or settings.GEMINI_MODEL
            synthesis = _parse_and_validate(raw, assessment_scores)
            return synthesis, model
        except (ValidationError, BannedLanguageError, JdScoringUnavailable, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning(
                "report_synthesis_attempt_failed attempt=%s error=%s",
                attempt + 1,
                exc,
            )
            if attempt == 0:
                continue
            break
    assert last_error is not None
    if isinstance(last_error, BannedLanguageError):
        raise last_error
    if isinstance(last_error, ValidationError):
        raise JdScoringUnavailable(f"invalid_synthesis_json: {last_error}") from last_error
    raise last_error


def score_against_jd(
    *,
    job_description: str,
    candidate_name: str,
    package_title: str,
    evidence: list[dict[str, Any]],
    assessment_scores: list[dict[str, Any]] | None = None,
    target_role: str = "",
    complete: CompleteFn | None = None,
) -> ReportNarrative:
    """Generate the report synthesis.

    Args:
        job_description: JD text (or synthesized role brief).
        candidate_name: Candidate display name.
        package_title: Package title for context.
        evidence: Output of ``build_evidence``.
        assessment_scores: Output of ``prompt_assessments`` (server-computed).
        target_role: Role the candidate is assessed for.
        complete: Optional completion stub (tests).

    Returns:
        Parsed synthesis.
    """
    synthesis, _model = score_against_jd_with_model(
        job_description=job_description,
        candidate_name=candidate_name,
        package_title=package_title,
        evidence=evidence,
        assessment_scores=assessment_scores,
        target_role=target_role,
        complete=complete,
    )
    return synthesis


class JdScoringService:
    @staticmethod
    async def read_cached(
        session: AsyncSession,
        *,
        candidate: Candidate,
        package: Package | None,
        outcomes: list[ModuleOutcome],
        now: datetime | None = None,
    ) -> CachedSynthesis:
        """Look up the stored synthesis without ever calling Gemini.

        Report views use this so page loads stay database-only; generation
        happens in ``app.services.background.refresh_report_synthesis``.

        Args:
            session: Async SQLAlchemy session.
            candidate: Candidate being reported on.
            package: Candidate's package (role / JD source).
            outcomes: Module outcomes the report is rendering.
            now: Clock override (tests).

        Returns:
            The cache state and whether a background refresh should be queued.
        """
        jd = resolve_job_description(package)
        if not jd or not outcomes:
            return CachedSynthesis(None, "skipped", needs_refresh=False)

        digest = synthesis_cache_key(jd, outcomes)
        row = (
            await session.execute(
                select(CandidateEvaluation).where(
                    CandidateEvaluation.candidate_id == candidate.id
                )
            )
        ).scalars().first()
        if row is None:
            return CachedSynthesis(None, "missing", needs_refresh=True)
        if row.jd_hash != digest:
            return CachedSynthesis(None, "stale", needs_refresh=True)
        if evaluation_is_ok(row):
            try:
                return CachedSynthesis(
                    ReportNarrative.model_validate(row.payload), "ok", needs_refresh=False
                )
            except ValidationError:
                logger.warning("jd_scoring_cache_invalid candidate_id=%s", candidate.id)
                return CachedSynthesis(None, "stale", needs_refresh=True)

        generated_at = getattr(row, "generated_at", None)
        current = now or datetime.now(timezone.utc)
        cooled_down = generated_at is None or current - generated_at >= FAILED_RETRY_COOLDOWN
        return CachedSynthesis(None, "failed", needs_refresh=cooled_down)

    @staticmethod
    async def get_or_evaluate(
        session: AsyncSession,
        *,
        candidate: Candidate,
        package: Package | None,
        assessments: list[Assessment],
        progresses: list[CandidateProgress],
        responses: list[CandidateResponse],
        outcomes: list[ModuleOutcome] | None = None,
        complete: CompleteFn | None = None,
    ) -> tuple[ReportNarrative | None, str]:
        """Return the cached or freshly generated report synthesis.

        Status is one of: cached, generated, skipped, failed. Failures never raise
        to the report download path; they are persisted as ``status='failed'``
        rows (with ``last_error``) so HR and ops can see them, and retried on
        the next call. Banned language after retry is recorded as
        ``banned_language_held_for_review``.

        Args:
            session: Async SQLAlchemy session.
            candidate: Candidate being scored.
            package: Candidate's package (role / JD source).
            assessments: Package assessments.
            progresses: Candidate progress rows.
            responses: Candidate response rows.
            outcomes: Pre-computed module outcomes (computed when omitted).
            complete: Optional completion stub (tests).

        Returns:
            ``(synthesis | None, status)``.
        """
        jd = resolve_job_description(package)
        if not jd:
            logger.info("jd_scoring_skipped_no_role candidate_id=%s", candidate.id)
            return None, "skipped"

        if outcomes is None:
            catalog = await load_catalog_categories(session, assessments)
            outcomes = build_module_outcomes(assessments, progresses, responses, catalog)
        if not outcomes:
            logger.info("jd_scoring_skipped_no_completed candidate_id=%s", candidate.id)
            return None, "skipped"
        digest = synthesis_cache_key(jd, outcomes)
        existing = (
            await session.execute(
                select(CandidateEvaluation).where(
                    CandidateEvaluation.candidate_id == candidate.id
                )
            )
        ).scalars().first()
        if existing and existing.jd_hash == digest and evaluation_is_ok(existing):
            try:
                return ReportNarrative.model_validate(existing.payload), "cached"
            except ValidationError:
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
                    assessment_scores=prompt_assessments(outcomes),
                    target_role=(getattr(package, "target_role", None) or "") if package else "",
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
            existing.overall_fit = None
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
                    overall_fit=None,
                    payload=payload,
                    status=EVAL_STATUS_OK,
                    last_error=None,
                    generated_at=now,
                )
            )
        await session.commit()
        logger.info(
            "jd_scoring_generated candidate_id=%s model=%s assessments=%s",
            candidate.id,
            model,
            len(evaluation.competency_breakdown),
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
