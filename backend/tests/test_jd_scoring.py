import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.prompts.jd_scoring import SYSTEM_INSTRUCTION, build_user_prompt
from app.schemas.jd_evaluation import JdFitEvaluation
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
    JdScoringService,
)
from app.services.report_service import _env


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

VALID_FIT = {
    "overall_fit": 72,
    "summary": "Solid quantitative fit with thin written evidence.",
    "strengths": ["Accurate MCQ performance"],
    "risks": ["No open-ended depth"],
    "hiring_recommendation": "consider",
    "competencies": [{"name": "Quantitative", "score": 80}],
    "per_assessment": [{"title": "Math", "fit": 80, "notes": "Score-led."}],
}

LEGACY_FIT = {
    "overall_fit": 72,
    "summary": "Solid quantitative fit with thin written evidence.",
    "strengths": ["Accurate MCQ performance"],
    "gaps": ["No open-ended depth"],
    "per_assessment": [{"title": "Math", "fit": 80, "notes": "Score-led."}],
}


def test_prompt_does_not_embed_json_schema():
    assert '"type": "object"' not in SYSTEM_INSTRUCTION
    assert "properties" not in SYSTEM_INSTRUCTION
    prompt = build_user_prompt(
        job_description="Backend engineer",
        candidate_name="Pat",
        package_title="Eng pack",
        evidence_json='{"title":"Math"}',
    )
    assert "Backend engineer" in prompt
    assert "Pat" in prompt
    assert '"type": "object"' not in prompt
    assert "required" not in prompt
    assert "interview_questions" not in SYSTEM_INSTRUCTION
    assert "interview follow-up" in SYSTEM_INSTRUCTION


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
        complete=lambda _p: json.dumps(VALID_FIT),
    )
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


def test_score_against_jd_rejects_leaked_key_fields():
    with pytest.raises(RuntimeError, match="leaked"):
        score_against_jd(
            job_description="Role",
            candidate_name="Pat",
            package_title="Pkg",
            evidence=[{"correct_answer": "4"}],
            complete=lambda _prompt: json.dumps(VALID_FIT),
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
        complete=lambda _prompt: json.dumps(VALID_FIT),
    )
    assert result.overall_fit == 72


def test_score_against_jd_parses_structured_output():
    captured = {}

    def complete(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps(VALID_FIT)

    result = score_against_jd(
        job_description="Backend engineer. Python, Postgres.",
        candidate_name="Pat",
        package_title="Eng pack",
        evidence=[{"title": "Math", "mcq_score": 80, "mcq": [], "open_ended": [], "likert": []}],
        complete=complete,
    )
    assert result.overall_fit == 72
    assert "correct_answer" not in captured["prompt"]
    assert "Backend engineer" in captured["prompt"]


def test_parse_evaluation_json_strips_markdown_fences():
    fenced = "```json\n" + json.dumps(VALID_FIT) + "\n```"
    result = parse_evaluation_json(fenced)
    assert result.overall_fit == 72


def test_malformed_gemini_json_raises():
    with pytest.raises(Exception):
        score_against_jd(
            job_description="Role",
            candidate_name="Pat",
            package_title="Pkg",
            evidence=[{"title": "Math"}],
            complete=lambda _p: "not-json",
        )


def test_fit_bounds_enforced():
    bad = {**VALID_FIT, "overall_fit": 140}
    with pytest.raises(Exception):
        JdFitEvaluation.model_validate(bad)


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


def test_legacy_gaps_payload_maps_to_risks():
    result = JdFitEvaluation.model_validate(LEGACY_FIT)
    assert result.risks == ["No open-ended depth"]
    assert result.hiring_recommendation == "consider"
    assert result.competencies[0].name == "Math"
    assert result.competencies[0].score == 80


def test_legacy_interview_questions_are_dropped():
    stale = {
        **VALID_FIT,
        "interview_questions": ["Walk me through a production incident you owned."],
    }
    result = JdFitEvaluation.model_validate(stale)
    dumped = result.model_dump()
    assert "interview_questions" not in dumped
    assert result.overall_fit == 72


def test_report_html_includes_jd_fit_section():
    html = _env.get_template("report.html").render(
        candidate_name="Pat",
        package_title="Eng pack",
        results=[{"assessment": "Math", "score": 80.0, "status": "COMPLETED"}],
        jd_fit=VALID_FIT,
        jd_status="generated",
        mcq_score=80.0,
        recommendation_label="Consider",
        recommendation_key="consider",
        corporate_name="Acme",
        corporate_logo_url="",
        generated_at="now",
        current_year=2026,
    )
    assert "Executive Fit Summary" in html
    assert "Solid quantitative fit" in html
    assert "72%" in html
    assert "Assess Pulse" in html
    assert "Interview Guide" not in html
    assert "Risks" in html


def test_report_html_omits_stale_interview_guide():
    stale = {
        **VALID_FIT,
        "interview_questions": ["How do you validate API contracts under time pressure?"],
    }
    html = _env.get_template("report.html").render(
        candidate_name="Pat",
        package_title="Eng pack",
        results=[{"assessment": "Math", "score": 80.0, "status": "COMPLETED"}],
        jd_fit=stale,
        jd_status="generated",
        mcq_score=80.0,
        recommendation_label="Consider",
        recommendation_key="consider",
        corporate_name="Acme",
        corporate_logo_url="",
        generated_at="now",
        current_year=2026,
    )
    assert "Interview Guide" not in html
    assert "validate API contracts" not in html


def test_report_html_skipped_jd():
    html = _env.get_template("report.html").render(
        candidate_name="Pat",
        package_title="Eng pack",
        results=[],
        jd_fit=None,
        jd_status="skipped",
        mcq_score=None,
        recommendation_label="Consider",
        recommendation_key="consider",
        corporate_name="",
        corporate_logo_url="",
        generated_at="now",
        current_year=2026,
    )
    assert "No job description" in html


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
        complete=lambda _p: json.dumps(VALID_FIT),
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
        return json.dumps(VALID_FIT)

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


def _scoring_kwargs():
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
        jd_hash="old-jd", status=EVAL_STATUS_OK, payload=VALID_FIT, overall_fit=72,
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
        jd_hash=hash_job_description(kwargs["package"].description),
        status=EVAL_STATUS_FAILED, payload={}, overall_fit=None,
        last_error="503", model="gemini-3.6-flash", generated_at=None,
    )
    session = FakeSession(existing=failed)
    calls = {"n": 0}

    def complete(_prompt: str) -> str:
        calls["n"] += 1
        return ModelText.tagged(json.dumps(VALID_FIT), "gemini-3.5-flash")

    evaluation, status = await JdScoringService.get_or_evaluate(
        session, complete=complete, **kwargs
    )
    assert calls["n"] == 1
    assert status == "generated"
    assert evaluation.overall_fit == 72
    assert failed.status == EVAL_STATUS_OK
    assert failed.last_error is None
    assert failed.model == "gemini-3.5-flash"
    assert evaluation_is_ok(failed)


@pytest.mark.asyncio
async def test_get_or_evaluate_cache_hit_skips_provider():
    kwargs = _scoring_kwargs()
    ok_row = SimpleNamespace(
        jd_hash=hash_job_description(kwargs["package"].description),
        status=EVAL_STATUS_OK, payload=VALID_FIT,
    )

    def complete(_prompt: str) -> str:
        raise AssertionError("cache hit must not call Gemini")

    evaluation, status = await JdScoringService.get_or_evaluate(
        FakeSession(existing=ok_row), complete=complete, **kwargs
    )
    assert status == "cached"
    assert evaluation.overall_fit == 72


@pytest.mark.asyncio
async def test_failure_record_error_does_not_raise_into_report_path():
    session = FakeSession(fail_commit=True)
    evaluation, status = await JdScoringService.get_or_evaluate(
        session, complete=_provider_503, **_scoring_kwargs()
    )
    assert (evaluation, status) == (None, "failed")
    assert session.rollbacks == 1


def test_evaluation_is_ok_treats_legacy_rows_without_status_as_ok():
    assert evaluation_is_ok(SimpleNamespace(payload=VALID_FIT))
    assert not evaluation_is_ok(None)
    assert not evaluation_is_ok(SimpleNamespace(status=EVAL_STATUS_OK, payload={}))
