import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.prompts.jd_scoring import PROMPT_VERSION, SYSTEM_INSTRUCTION, build_user_prompt
from app.schemas.jd_evaluation import ReportSynthesis
from app.services.jd_scoring import (
    EVAL_STATUS_FAILED,
    EVAL_STATUS_OK,
    ModelText,
    build_evidence,
    crt_reasoning,
    evaluation_is_ok,
    hash_job_description,
    parse_evaluation_json,
    resolve_job_description,
    score_against_jd,
    synthesis_cache_key,
    JdScoringService,
)
from app.services.report_service import ReportService
from app.services.report_synthesis import ModuleOutcome


def _assessment(questions, title="Math"):
    return SimpleNamespace(id=uuid4(), title=title, questions=questions)


LEAKY_MCQ = {
    "id": "q1",
    "text": "What is 2+2?",
    "type": "mcq",
    "options": ["3", "4"],
    "correct_answer": "4",
    "is_correct": True,
}

VALID_SYNTHESIS = {
    "executive_summary": "Solid quantitative reasoning with thin written evidence.",
    "strengths": ["Accurate numerical reasoning under time pressure."],
    "risks_and_antipatterns": ["Limited open-ended depth."],
    "competency_breakdown": [
        {
            "assessment_key": "A1",
            "assessment_name": "Math",
            "performance_summary": "Scored 80%, indicating strong numerical reasoning.",
        }
    ],
    "category_summaries": [
        {
            "category": "Cognitive",
            "summary": "Strong quantitative reasoning for the role. Applies structured logic consistently.",
        }
    ],
}

LEGACY_FIT = {
    "overall_fit": 72,
    "summary": "Solid quantitative fit with thin written evidence.",
    "strengths": ["Accurate MCQ performance"],
    "risks": ["No open-ended depth"],
    "hiring_recommendation": "consider",
    "competencies": [{"name": "Quantitative", "score": 80}],
}


def _prompt(**overrides):
    kwargs = {
        "target_role": "Backend Engineer",
        "job_description": "Backend engineer",
        "candidate_name": "Pat",
        "package_title": "Eng pack",
        "assessment_scores_json": '[{"assessment_key":"A1","score":80}]',
        "evidence_json": '{"title":"Math"}',
    }
    kwargs.update(overrides)
    return build_user_prompt(**kwargs)


def test_prompt_does_not_embed_json_schema():
    assert '"type": "object"' not in SYSTEM_INSTRUCTION
    assert "properties" not in SYSTEM_INSTRUCTION
    prompt = _prompt()
    assert "Backend engineer" in prompt
    assert "Pat" in prompt
    assert '"type": "object"' not in prompt
    assert "required" not in prompt
    assert "interview_questions" not in SYSTEM_INSTRUCTION
    assert "Do not generate interview questions" in SYSTEM_INSTRUCTION


@pytest.mark.parametrize(
    "instruction",
    [
        "Do not include any overall hiring recommendation (such as 'Hire', 'Strong Hire', "
        "or 'Do Not Hire') and do not generate a 'Candidate Fit' score.",
        "For each assessment in the competency breakdown, generate exactly one analytical "
        "sentence summarizing the candidate's performance based on their score.",
        "Generate an executive summary and detailed bullet points for Strengths and "
        "Risks/Anti-patterns.",
        "The psychometric assessments are grouped into three pillars: Cognitive, Personality, "
        "and Behavioral. Technical assessments are separate and never get a pillar summary.",
        "category_summaries must contain one entry per psychometric category (Cognitive, "
        "Personality, or Behavioral) present in assessment_scores",
    ],
)
def test_system_instruction_contains_required_directives_verbatim(instruction):
    assert instruction in SYSTEM_INSTRUCTION


def test_prompt_includes_target_role_and_score_table():
    prompt = _prompt()
    assert "Target role: Backend Engineer" in prompt
    assert '"assessment_key":"A1"' in prompt


def test_prompt_falls_back_to_package_title_without_role():
    assert "Target role: Eng pack" in _prompt(target_role="  ")


def test_prompt_version_is_report_synthesis():
    assert PROMPT_VERSION == "mindq-report-v2"


def test_build_evidence_strips_answer_keys():
    assessment = _assessment([LEAKY_MCQ])
    progress = SimpleNamespace(
        assessment_id=assessment.id, status="COMPLETED", score=100
    )
    response = SimpleNamespace(
        assessment_id=assessment.id, question_id="q1", response={"answer": "4"}
    )
    evidence = build_evidence([assessment], [progress], [response])
    dumped = json.dumps(evidence)
    assert "correct_answer" not in dumped
    assert "is_correct" not in dumped
    assert evidence[0]["mcq"][0]["selected"] == "4"
    assert evidence[0]["mcq_score"] == 100.0


def test_build_evidence_stringifies_nested_answer_objects():
    assessment = _assessment(
        [{"id": "q1", "text": "Explain", "type": "open", "correct_answer": "secret"}]
    )
    progress = SimpleNamespace(assessment_id=assessment.id, status="COMPLETED", score=None)
    response = SimpleNamespace(
        assessment_id=assessment.id,
        question_id="q1",
        response={"answer": {"correct_answer": "nested-should-not-abort"}},
    )
    evidence = build_evidence([assessment], [progress], [response])
    dumped = json.dumps(evidence)
    assert "secret" not in dumped
    # Nested payload is text, not a leaked key field.
    score_against_jd(
        job_description="Role",
        candidate_name="Pat",
        package_title="Pkg",
        evidence=evidence,
        complete=lambda _p: json.dumps(VALID_SYNTHESIS),
    )


def test_score_against_jd_rejects_leaked_key_fields():
    with pytest.raises(RuntimeError, match="leaked"):
        score_against_jd(
            job_description="Role",
            candidate_name="Pat",
            package_title="Pkg",
            evidence=[{"correct_answer": "4"}],
            complete=lambda _prompt: json.dumps(VALID_SYNTHESIS),
        )


def test_score_against_jd_allows_correct_answer_in_prose():
    result = score_against_jd(
        job_description="Role",
        candidate_name="Pat",
        package_title="Pkg",
        evidence=[
            {
                "title": "Coding",
                "open_ended": [
                    {
                        "question": "Write a checker",
                        "answer": "def is_correct(x): return x == correct_answer",
                    }
                ],
            }
        ],
        complete=lambda _prompt: json.dumps(VALID_SYNTHESIS),
    )
    assert result.executive_summary.startswith("Solid quantitative")


def test_score_against_jd_parses_structured_output():
    captured = {}

    def complete(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(VALID_SYNTHESIS)

    result = score_against_jd(
        job_description="Backend engineer. Python, Postgres.",
        candidate_name="Pat",
        package_title="Eng pack",
        evidence=[{"title": "Math", "mcq_score": 80, "mcq": [], "open_ended": [], "likert": []}],
        assessment_scores=[
            {"assessment_key": "A1", "assessment_name": "Math", "category": "Cognitive", "score": 80.0}
        ],
        target_role="Backend Engineer",
        complete=complete,
    )
    assert result.summaries_by_key() == {
        "A1": "Scored 80%, indicating strong numerical reasoning."
    }
    assert "correct_answer" not in captured["prompt"]
    assert "Backend engineer" in captured["prompt"]
    assert '"category": "Cognitive"' in captured["prompt"]


def test_score_against_jd_logs_missing_assessment_summaries(caplog):
    result = score_against_jd(
        job_description="Role",
        candidate_name="Pat",
        package_title="Pkg",
        evidence=[],
        assessment_scores=[
            {"assessment_key": "A1", "assessment_name": "Math", "category": "Cognitive", "score": 80.0},
            {"assessment_key": "A2", "assessment_name": "SQL", "category": "Technical", "score": 40.0},
        ],
        complete=lambda _p: json.dumps(VALID_SYNTHESIS),
    )
    assert "A2" not in result.summaries_by_key()
    assert "report_synthesis_missing_summaries" in caplog.text


def test_parse_evaluation_json_strips_markdown_fences():
    fenced = "```json\n" + json.dumps(VALID_SYNTHESIS) + "\n```"
    result = parse_evaluation_json(fenced)
    assert result.strengths == ["Accurate numerical reasoning under time pressure."]


def test_malformed_gemini_json_raises():
    with pytest.raises(Exception):
        score_against_jd(
            job_description="Role",
            candidate_name="Pat",
            package_title="Pkg",
            evidence=[{"title": "Math"}],
            complete=lambda _p: "not-json",
        )


def test_synthesis_drops_hallucinated_fit_and_recommendation():
    hallucinated = {
        **VALID_SYNTHESIS,
        "overall_fit": 91,
        "hiring_recommendation": "strong_hire",
        "interview_questions": ["Tell me about yourself."],
    }
    dumped = ReportSynthesis.model_validate(hallucinated).model_dump()
    assert set(dumped) == {
        "executive_summary",
        "strengths",
        "risks_and_antipatterns",
        "competency_breakdown",
        "category_summaries",
    }


def test_synthesis_without_category_summaries_still_validates():
    legacy = {k: v for k, v in VALID_SYNTHESIS.items() if k != "category_summaries"}
    result = ReportSynthesis.model_validate(legacy)
    assert result.category_summaries == []
    assert result.summaries_by_category() == {}


def test_category_summaries_first_occurrence_wins_and_rejects_technical():
    result = ReportSynthesis.model_validate(
        {
            **VALID_SYNTHESIS,
            "category_summaries": [
                {"category": "Cognitive", "summary": "  First   summary. "},
                {"category": "Cognitive", "summary": "Second summary."},
            ],
        }
    )
    assert result.summaries_by_category() == {"Cognitive": "First summary."}
    with pytest.raises(ValidationError):
        ReportSynthesis.model_validate(
            {**VALID_SYNTHESIS, "category_summaries": [{"category": "Technical", "summary": "Nope."}]}
        )


def test_synthesis_requires_executive_summary():
    with pytest.raises(ValidationError):
        ReportSynthesis.model_validate({**VALID_SYNTHESIS, "executive_summary": ""})


def test_legacy_jd_fit_payload_is_not_a_valid_synthesis():
    with pytest.raises(ValidationError):
        ReportSynthesis.model_validate(LEGACY_FIT)


def test_multi_sentence_performance_summary_is_truncated_to_one():
    payload = {
        **VALID_SYNTHESIS,
        "competency_breakdown": [
            {
                "assessment_key": "A1",
                "assessment_name": "Math",
                "performance_summary": "Scored 3.5 out of 5 on reasoning. Recommend hire.",
            }
        ],
    }
    result = ReportSynthesis.model_validate(payload)
    assert result.competency_breakdown[0].performance_summary == (
        "Scored 3.5 out of 5 on reasoning."
    )


@pytest.mark.asyncio
async def test_get_or_evaluate_skips_without_jd_or_role():
    evaluation, status = await JdScoringService.get_or_evaluate(
        None,
        candidate=SimpleNamespace(id=uuid4(), full_name="Pat"),
        package=SimpleNamespace(description="  ", title="", target_role=None),
        assessments=[],
        progresses=[],
        responses=[],
    )
    assert evaluation is None
    assert status == "skipped"


@pytest.mark.asyncio
async def test_get_or_evaluate_skips_without_completed_assessments():
    def complete(_prompt: str) -> str:
        raise AssertionError("no completed assessments must not call Gemini")

    evaluation, status = await JdScoringService.get_or_evaluate(
        None,
        candidate=SimpleNamespace(id=uuid4(), full_name="Pat"),
        package=SimpleNamespace(description="Ops lead", title="Ops", target_role="Ops"),
        assessments=[],
        progresses=[],
        responses=[],
        outcomes=[],
        complete=complete,
    )
    assert (evaluation, status) == (None, "skipped")


def test_resolve_job_description_prefers_description():
    pkg = SimpleNamespace(description=" Build ETL ", title="Analyst", target_role="Data")
    assert resolve_job_description(pkg) == "Build ETL"


def test_resolve_job_description_falls_back_to_role_then_title():
    with_role = SimpleNamespace(description="", title="Pack", target_role="Data Analyst")
    assert "Role: Data Analyst" in resolve_job_description(with_role)
    title_only = SimpleNamespace(description=None, title="Junior Data Analyst", target_role=None)
    assert "Role: Junior Data Analyst" in resolve_job_description(title_only)
    assert resolve_job_description(None) == ""


def test_jd_hash_is_stable():
    assert hash_job_description("  Hello \n") == hash_job_description("Hello")


def _report(**overrides):
    report = {
        "candidate_id": str(uuid4()),
        "candidate_full_name": "Pat Doe",
        "candidate_email": "pat@example.com",
        "target_role": "Backend Engineer",
        "company_name": "Acme",
        "company_logo_url": None,
        "completed_at": None,
        "synthesis_status": "ok",
        "total_assessments_completed": 2,
        "category_averages": {"Cognitive": 80.0, "Technical": 62.5},
        "executive_summary": "Solid quantitative reasoning with thin written evidence.",
        "strengths": ["Accurate numerical reasoning."],
        "risks_and_antipatterns": ["Limited open-ended depth."],
        "competency_breakdown": [
            {
                "category": "Cognitive",
                "assessment_name": "Math",
                "score": 80.0,
                "performance_summary": "Scored 80%, indicating strong numerical reasoning.",
            }
        ],
        "category_summaries": [
            {"category": "Cognitive", "summary": "Strong quantitative pillar overall."}
        ],
        "custom_questions": [],
    }
    report.update(overrides)
    return report


def test_report_html_renders_synthesis_without_fit_or_recommendation():
    html = ReportService.render_report_html(_report())
    assert "Assessment Report" in html
    assert "Mind Q Report - " in html
    assert "Solid quantitative reasoning" in html
    assert "62.5%" in html
    assert "strong numerical reasoning" in html
    assert "Risks &amp; Anti-patterns" in html
    assert "Overall Fit" not in html
    assert "Recommendation" not in html
    assert "MCQ Score" not in html
    assert "Assess Pulse" not in html
    assert "AI " not in html
    assert "auto-generated Mind Queue report" in html
    assert "MindQ (Pvt.) Ltd." in html
    assert "Mind Queue Private Limited" not in html
    assert "not an indication of whether the candidate is a good fit" in html
    assert "This is merely an analysis of an assessment." in html
    assert "Strong quantitative pillar overall." in html


def test_report_html_shows_na_for_categories_without_assessments():
    html = ReportService.render_report_html(_report(category_averages={"Cognitive": 80.0}))
    assert "80.0%" in html
    assert html.count("N/A") == 3
    for category in ("Cognitive", "Personality", "Behavioral", "Technical"):
        assert category in html


def test_report_html_skipped_synthesis():
    html = ReportService.render_report_html(
        _report(
            synthesis_status="skipped",
            executive_summary="",
            strengths=[],
            risks_and_antipatterns=[],
            competency_breakdown=[],
            category_averages={},
            total_assessments_completed=0,
        )
    )
    assert "needs a target role" in html
    assert "No scored assessments" in html


def test_build_evidence_includes_benchmark_rubric():
    assessment = _assessment(
        [
            {
                "id": "q1",
                "text": "Explain",
                "type": "open",
                "benchmark_rubric": "Mention latency and retries",
            }
        ]
    )
    progress = SimpleNamespace(assessment_id=assessment.id, status="COMPLETED", score=None)
    response = SimpleNamespace(
        assessment_id=assessment.id,
        question_id="q1",
        response={"answer": "Use retries with backoff"},
    )
    evidence = build_evidence([assessment], [progress], [response])
    assert evidence[0]["open_ended"][0]["benchmark_rubric"] == "Mention latency and retries"


LIKERT_ITEM = {"id": "l1", "text": "I take charge.", "type": "likert", "facet": "PA"}
COMPLETE_PROFILE = {
    "resolver": "ipip_ipc_v1",
    "version": "1.0.0",
    "status": "complete",
    "data": {
        "dominance": 2.0,
        "warmth": 0.0,
        "vector_length": 2.0,
        "angle_deg": 90.0,
        "style_code": "PA",
        "style_label": "Assured-Dominant",
        "octant_means": {"PA": 5.0},
    },
}


def _likert_evidence(derived_profile):
    assessment = _assessment([LIKERT_ITEM], title="Interpersonal")
    progress = SimpleNamespace(
        assessment_id=assessment.id,
        status="COMPLETED",
        score=None,
        derived_profile=derived_profile,
    )
    response = SimpleNamespace(
        assessment_id=assessment.id, question_id="l1", response={"answer": 5}
    )
    return build_evidence([assessment], [progress], [response])


def test_complete_profile_replaces_raw_likert():
    evidence = _likert_evidence(COMPLETE_PROFILE)
    assert "likert" not in evidence[0]
    profile = evidence[0]["interpersonal_profile"]
    assert profile["resolver"] == "ipip_ipc_v1"
    assert profile["style_label"] == "Assured-Dominant"
    assert profile["dominance"] == 2.0
    score_against_jd(
        job_description="Team lead",
        candidate_name="Pat",
        package_title="Pkg",
        evidence=evidence,
        complete=lambda _p: json.dumps(VALID_SYNTHESIS),
    )


@pytest.mark.parametrize(
    "derived_profile",
    [
        None,
        {"resolver": "ipip_ipc_v1", "version": "1.0.0", "status": "insufficient_data",
         "data": {"missing_octants": ["NO"], "min_items": 3}},
        {"resolver": "ipip_ipc_v1", "status": "bogus"},
        "not-a-dict",
    ],
)
def test_non_complete_profile_falls_back_to_likert(derived_profile):
    evidence = _likert_evidence(derived_profile)
    assert "interpersonal_profile" not in evidence[0]
    assert evidence[0]["likert"] == [{"question": "I take charge.", "rating": 5}]


def test_prompt_marks_interpersonal_profile_authoritative():
    assert "interpersonal_profile" in SYSTEM_INSTRUCTION
    assert "never recompute" in SYSTEM_INSTRUCTION


SJT_ITEM = {
    "id": "s1",
    "text": "A report is due at 5 pm and you spot a data issue at 3 pm.",
    "type": "sjt",
    "facet": "Decision Making",
    "evaluated_competency": "Decision Making",
    "options": ["Say nothing", "Tell your manager and propose options", "Stay late", "Remove section"],
    "option_weights": [0, 3, 2, 1],
    "sme_rationale": "Escalating with options is best.",
}
# Mirrors production rows where the author pasted a quoted list into one answer box.
CRT_MALFORMED = {
    "id": "c1",
    "text": "A bat and a ball cost $1.10. The bat costs $1.00 more. Ball cost?",
    "type": "crt",
    "facet": "Cognitive Reflection",
    "match": "exact",
    "options": [],
    "accepted_answers": ['"5",   "5 cents",   "0.05",   ".05"'],
}
CRT_NUMERIC = {
    "id": "c2",
    "text": "5 machines, 5 minutes, 5 widgets. 100 machines for 100 widgets?",
    "type": "crt",
    "match": "numeric",
    "accepted_answers": ["5"],
}


def _module_evidence(questions, answers, title="Module"):
    assessment = _assessment(questions, title=title)
    progress = SimpleNamespace(assessment_id=assessment.id, status="COMPLETED", score=50)
    responses = [
        SimpleNamespace(assessment_id=assessment.id, question_id=qid, response={"answer": value})
        for qid, value in answers.items()
    ]
    return build_evidence([assessment], [progress], responses)[0]


@pytest.mark.parametrize(
    "answer, credit",
    [("Tell your manager and propose options", 1.0), ("Stay late", 0.67), ("Say nothing", 0.0)],
)
def test_build_evidence_includes_sjt_choice_competency_and_credit(answer, credit):
    entry = _module_evidence([SJT_ITEM], {"s1": answer}, title="Situational Judgment")
    assert entry["sjt"] == [
        {
            "scenario": SJT_ITEM["text"],
            "competency": "Decision Making",
            "chosen_option": answer,
            "credit": credit,
        }
    ]
    dumped = json.dumps(entry)
    assert "option_weights" not in dumped
    assert "sme_rationale" not in dumped
    assert "Escalating with options" not in dumped


def test_build_evidence_sjt_unanswered_has_no_choice_or_credit():
    entry = _module_evidence([SJT_ITEM], {})
    assert entry["sjt"][0]["chosen_option"] is None
    assert entry["sjt"][0]["credit"] is None


def test_build_evidence_sjt_without_weights_reports_null_credit():
    unweighted = {**SJT_ITEM, "option_weights": [1, 2]}
    entry = _module_evidence([unweighted], {"s1": "Stay late"})
    assert entry["sjt"][0]["chosen_option"] == "Stay late"
    assert entry["sjt"][0]["credit"] is None


@pytest.mark.parametrize(
    "question, answer, reasoning",
    [
        (CRT_MALFORMED, ".05", "reflective"),
        (CRT_MALFORMED, "5 Cents", "reflective"),
        (CRT_MALFORMED, "10 cents", "intuitive"),
        (CRT_MALFORMED, "   ", "unanswered"),
        (CRT_NUMERIC, "5.0", "reflective"),
        (CRT_NUMERIC, "100", "intuitive"),
        (CRT_NUMERIC, "a lot", "intuitive"),
    ],
)
def test_build_evidence_includes_crt_prompt_answer_and_reasoning(question, answer, reasoning):
    entry = _module_evidence([question], {question["id"]: answer}, title="CRT")
    assert entry["crt"] == [
        {"question": question["text"], "answer": answer, "reasoning": reasoning}
    ]
    dumped = json.dumps(entry)
    assert "accepted_answers" not in dumped
    assert '"5 cents"' not in dumped


def test_crt_reasoning_missing_answer_and_ungradable_key():
    assert crt_reasoning(CRT_NUMERIC, None) == "unanswered"
    assert crt_reasoning({**CRT_NUMERIC, "accepted_answers": []}, "5") == "ungraded"


def test_build_evidence_omits_sjt_crt_keys_for_other_modules():
    entry = _module_evidence([LEAKY_MCQ], {"q1": "4"})
    assert "sjt" not in entry
    assert "crt" not in entry


def test_sjt_crt_evidence_passes_leak_guard_end_to_end():
    entry = _module_evidence(
        [SJT_ITEM, CRT_MALFORMED], {"s1": "Stay late", "c1": "0.05"}, title="Mixed"
    )
    captured = {}

    def complete(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(VALID_SYNTHESIS)

    score_against_jd(
        job_description="Ops lead",
        candidate_name="Pat",
        package_title="Pkg",
        evidence=[entry],
        complete=complete,
    )
    assert '"reasoning": "reflective"' in captured["prompt"]
    assert '"chosen_option": "Stay late"' in captured["prompt"]


def test_prompt_explains_sjt_credit_and_crt_reasoning():
    assert "credit" in SYSTEM_INSTRUCTION
    assert "reflective" in SYSTEM_INSTRUCTION
    assert "intuitive" in SYSTEM_INSTRUCTION


class _Result:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class FakeSession:
    """Minimal AsyncSession stand-in for get_or_evaluate persistence paths."""

    def __init__(self, existing=None, fail_commit=False):
        self.existing = existing
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = fail_commit

    async def execute(self, _stmt):
        return _Result(self.existing)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("db down")
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _outcomes(score: float = 80.0):
    return [
        ModuleOutcome(
            key="A1",
            id=uuid4(),
            title="Math",
            category="cognitive",
            score=score,
            completed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]


def _scoring_kwargs(outcomes=None):
    candidate = SimpleNamespace(
        id=uuid4(), full_name="Pat", corporate_id=uuid4(), package_id=uuid4()
    )
    package = SimpleNamespace(description="Ops lead role", title="Ops", target_role="Ops")
    return {
        "candidate": candidate,
        "package": package,
        "assessments": [],
        "progresses": [],
        "responses": [],
        "outcomes": outcomes if outcomes is not None else _outcomes(),
    }


def _provider_503(_prompt: str) -> str:
    raise RuntimeError("503 UNAVAILABLE. model is experiencing high demand")


@pytest.mark.asyncio
async def test_get_or_evaluate_persists_failed_status_on_provider_error():
    session = FakeSession()
    evaluation, status = await JdScoringService.get_or_evaluate(
        session, complete=_provider_503, **_scoring_kwargs()
    )
    assert evaluation is None
    assert status == "failed"
    assert session.commits == 1
    row = session.added[0]
    assert row.status == EVAL_STATUS_FAILED
    assert "503 UNAVAILABLE" in row.last_error
    assert row.payload == {}
    assert row.overall_fit is None
    assert not evaluation_is_ok(row)


@pytest.mark.asyncio
async def test_get_or_evaluate_persists_failed_status_on_malformed_json():
    session = FakeSession()
    _evaluation, status = await JdScoringService.get_or_evaluate(
        session, complete=lambda _p: "not-json", **_scoring_kwargs()
    )
    assert status == "failed"
    assert session.added[0].status == EVAL_STATUS_FAILED
    assert "ValidationError" in session.added[0].last_error


@pytest.mark.asyncio
async def test_get_or_evaluate_failure_clears_stale_payload_for_changed_jd():
    stale = SimpleNamespace(
        jd_hash="old-jd", status=EVAL_STATUS_OK, payload=VALID_SYNTHESIS, overall_fit=72,
        last_error=None, model="m", generated_at=None,
    )
    session = FakeSession(existing=stale)
    _evaluation, status = await JdScoringService.get_or_evaluate(
        session, complete=_provider_503, **_scoring_kwargs()
    )
    assert status == "failed"
    assert stale.status == EVAL_STATUS_FAILED
    assert stale.payload == {}
    assert stale.overall_fit is None


@pytest.mark.asyncio
async def test_get_or_evaluate_retries_failed_row_and_records_served_model():
    kwargs = _scoring_kwargs()
    failed = SimpleNamespace(
        jd_hash=synthesis_cache_key(kwargs["package"].description, kwargs["outcomes"]),
        status=EVAL_STATUS_FAILED, payload={}, overall_fit=None,
        last_error="503", model="gemini-3.6-flash", generated_at=None,
    )
    session = FakeSession(existing=failed)
    calls = {"n": 0}

    def complete(_prompt: str) -> str:
        calls["n"] += 1
        return ModelText.tagged(json.dumps(VALID_SYNTHESIS), "gemini-3.5-flash")

    evaluation, status = await JdScoringService.get_or_evaluate(
        session, complete=complete, **kwargs
    )
    assert calls["n"] == 1
    assert status == "generated"
    assert evaluation.executive_summary.startswith("Solid quantitative")
    assert failed.status == EVAL_STATUS_OK
    assert failed.last_error is None
    assert failed.overall_fit is None
    assert failed.model == "gemini-3.5-flash"
    assert "overall_fit" not in failed.payload
    assert evaluation_is_ok(failed)


@pytest.mark.asyncio
async def test_get_or_evaluate_cache_hit_skips_provider():
    kwargs = _scoring_kwargs()
    ok_row = SimpleNamespace(
        jd_hash=synthesis_cache_key(kwargs["package"].description, kwargs["outcomes"]),
        status=EVAL_STATUS_OK, payload=VALID_SYNTHESIS,
    )

    def complete(_prompt: str) -> str:
        raise AssertionError("cache hit must not call Gemini")

    evaluation, status = await JdScoringService.get_or_evaluate(
        FakeSession(existing=ok_row), complete=complete, **kwargs
    )
    assert status == "cached"
    assert evaluation.strengths == VALID_SYNTHESIS["strengths"]


@pytest.mark.asyncio
async def test_score_change_invalidates_cached_synthesis():
    kwargs = _scoring_kwargs(outcomes=_outcomes(score=40.0))
    ok_row = SimpleNamespace(
        jd_hash=synthesis_cache_key(kwargs["package"].description, _outcomes(score=80.0)),
        status=EVAL_STATUS_OK, payload=VALID_SYNTHESIS, overall_fit=None,
        last_error=None, model="m", generated_at=None,
    )
    calls = {"n": 0}

    def complete(_prompt: str) -> str:
        calls["n"] += 1
        return json.dumps(VALID_SYNTHESIS)

    _evaluation, status = await JdScoringService.get_or_evaluate(
        FakeSession(existing=ok_row), complete=complete, **kwargs
    )
    assert status == "generated"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_legacy_jd_fit_row_is_regenerated_not_served():
    kwargs = _scoring_kwargs()
    legacy = SimpleNamespace(
        jd_hash=synthesis_cache_key(kwargs["package"].description, kwargs["outcomes"]),
        status=EVAL_STATUS_OK, payload=LEGACY_FIT, overall_fit=72,
        last_error=None, model="m", generated_at=None,
    )
    evaluation, status = await JdScoringService.get_or_evaluate(
        FakeSession(existing=legacy),
        complete=lambda _p: json.dumps(VALID_SYNTHESIS),
        **kwargs,
    )
    assert status == "generated"
    assert legacy.overall_fit is None
    assert "hiring_recommendation" not in legacy.payload
    assert evaluation.risks_and_antipatterns == ["Limited open-ended depth."]


def test_cache_key_changes_with_prompt_inputs():
    base = synthesis_cache_key("Role", _outcomes(80.0))
    assert base == synthesis_cache_key("Role", _outcomes(80.0))
    assert base != synthesis_cache_key("Other role", _outcomes(80.0))
    assert base != synthesis_cache_key("Role", _outcomes(81.0))


@pytest.mark.asyncio
async def test_failure_record_error_does_not_raise_into_report_path():
    session = FakeSession(fail_commit=True)
    evaluation, status = await JdScoringService.get_or_evaluate(
        session, complete=_provider_503, **_scoring_kwargs()
    )
    assert (evaluation, status) == (None, "failed")
    assert session.rollbacks == 1


def test_evaluation_is_ok_treats_legacy_rows_without_status_as_ok():
    assert evaluation_is_ok(SimpleNamespace(payload=VALID_SYNTHESIS))
    assert not evaluation_is_ok(None)
    assert not evaluation_is_ok(SimpleNamespace(status=EVAL_STATUS_OK, payload={}))
