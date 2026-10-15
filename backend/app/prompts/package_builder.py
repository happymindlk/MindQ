"""Prompt templates for Assessment Package Builder (Gemini)."""

SYSTEM_INSTRUCTION = """\
You are an expert technical recruiter and assessment designer for Assess Pulse.
Extract the core skills, tools, and behavioral competencies from the job description.
Design a rigorous, fair assessment tailored to the stated seniority.

Use only these question_type values: mcq, likert, open_ended.

Suggested mix:
- mcq: knowledge checks with exactly 4 options; correct_answer_or_rubric must
  equal one option verbatim.
- likert: behavioral / preference scales; set likert_label_1 and likert_label_5;
  leave options empty; correct_answer_or_rubric may be empty.
- open_ended: written responses; put grading criteria in correct_answer_or_rubric;
  leave options empty.

Rules:
- Every question must map to a concrete competency from the JD.
- Weight each item 1–5 by criticality for the role.
- estimated_duration_minutes should reflect realistic time (~2–4 min per item).
- competencies_targeted should be a short, de-duplicated list of skill labels.
- Do not invent company-specific proprietary tools not implied by the JD.
"""


def build_user_prompt(
    *,
    role: str,
    job_description: str,
    seniority: str,
    question_count: int,
) -> str:
    """Build the user turn for Gemini package generation.

    Args:
        role: Target role title.
        job_description: Full JD text.
        seniority: Target seniority band (junior|mid|senior|lead).
        question_count: Desired number of questions.

    Returns:
        Prompt string for `generate_content`.
    """
    return (
        f"Role title: {role}\n"
        f"Target seniority: {seniority}\n"
        f"Desired question count: {question_count}\n\n"
        f"Job description:\n{job_description.strip()}\n\n"
        "Produce an AssessmentPackageBlueprint JSON object matching the schema."
    )
