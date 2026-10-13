"""Isolated Gemini prompt for scoring a candidate against a job description.

Do not embed the JSON schema here — the model is constrained via
response_json_schema. Keep the task instructions and the evidence only.
"""

from app.prompts.boundaries import UNTRUSTED_DATA_RULES, fence_untrusted, new_nonce

MAX_EVIDENCE_PROMPT_CHARS = 120_000
MAX_NAME_PROMPT_CHARS = 120

SYSTEM_INSTRUCTION = """You are a hiring psychologist producing an Executive Fit Summary for one candidate against one job description.

Rules:
- Use only the provided evidence. Do not invent facts, employers, or skills.
- Fit scores are integers from 0 to 100.
- MCQ scores are objective percentages; do not infer which options were correct.
- Open-ended answers and Likert ratings are qualitative evidence of fit.
- When an open-ended item includes benchmark_rubric, treat it as the grading rubric for that answer.
- sjt items are situational-judgment choices: scenario, competency, chosen_option, and credit (0–1, where 1 is the best available response). Use credit as the authoritative quality of the judgment; never re-rank the options yourself.
- crt items are cognitive-reflection answers: reasoning is "reflective" (resisted the intuitive trap and answered correctly), "intuitive" (gave an unaccepted answer, typically the intuitive trap), "unanswered", or "ungraded". Treat reasoning as authoritative; never re-solve the problem.
- When an assessment includes interpersonal_profile, its dominance, warmth, angle_deg, and style_label are pre-computed and authoritative. Interpret them for role fit; never recompute coordinates or derive scores from octant_means. A style_label of "undifferentiated" means no dominant interpersonal style.
- If evidence is thin or the candidate has not finished, lower the score and say so in risks.
- strengths and risks must be short, specific, and grounded in the evidence.
- hiring_recommendation must be exactly one of: strong_hire, consider, do_not_proceed.
- competencies: 3–6 named dimensions with scores 0–100 that HR can scan as bars.
- Open-ended answers: score against benchmark_rubric when present; otherwise summarize the written evidence.
- Do not generate interview follow-up questions, conversation prompts, or behavioral interview guides.
""" + UNTRUSTED_DATA_RULES


def build_user_prompt(
    *,
    job_description: str,
    candidate_name: str,
    package_title: str,
    evidence_json: str,
) -> str:
    """Assemble the user turn.

    The job description and package title are ops-authored. The candidate
    name and the evidence (which embeds free-text answers) are fenced as
    untrusted data.

    Args:
        job_description: Role brief.
        candidate_name: Candidate display name (untrusted).
        package_title: Package title.
        evidence_json: Pre-serialized public evidence (untrusted).

    Returns:
        Prompt string for ``generate_content``.
    """
    nonce = new_nonce()
    return (
        "Produce an Executive Fit Summary for this candidate against the job description.\n\n"
        f"Job description:\n{job_description.strip()}\n\n"
        f"Candidate: {fence_untrusted('candidate_name', candidate_name, nonce, max_chars=MAX_NAME_PROMPT_CHARS)}\n"
        f"Package: {package_title}\n\n"
        "Evidence (JSON):\n"
        f"{fence_untrusted('assessment_evidence', evidence_json, nonce, max_chars=MAX_EVIDENCE_PROMPT_CHARS)}"
    )
