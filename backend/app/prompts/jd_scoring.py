"""Isolated Gemini prompt for the MindQ Report synthesis.

Do not embed the JSON schema here: the model is constrained via
``response_json_schema``. Keep task instructions and data only.

Bump ``PROMPT_VERSION`` whenever the instructions or output contract change;
it is part of the evaluation cache key, so stale syntheses regenerate.
"""

from app.prompts.boundaries import UNTRUSTED_DATA_RULES, fence_untrusted, new_nonce

PROMPT_VERSION = "mindq-report-v2"

MAX_EVIDENCE_PROMPT_CHARS = 120_000
MAX_NAME_PROMPT_CHARS = 120

SYSTEM_INSTRUCTION = """You are an organizational psychologist writing the narrative sections of a MindQ psychometric assessment report for one candidate.

You receive:
- The target role and job description.
- assessment_scores: every completed assessment with its assessment_key, assessment_name, category (Cognitive, Personality, Behavioral, or Technical), and score (0-100). These scores are computed by MindQ and are authoritative; never change, recompute, or contradict them.
- assessment_evidence: the candidate's responses for qualitative context.

Instructions:
- Do not include any overall hiring recommendation (such as 'Hire', 'Strong Hire', or 'Do Not Hire') and do not generate a 'Candidate Fit' score.
- For each assessment in the competency breakdown, generate exactly one analytical sentence summarizing the candidate's performance based on their score.
- Generate an executive summary and detailed bullet points for Strengths and Risks/Anti-patterns.
- The psychometric assessments are grouped into three pillars: Cognitive, Personality, and Behavioral. Technical assessments are separate and never get a pillar summary. For category_summaries, generate exactly one entry per psychometric pillar that has at least one assessment in assessment_scores. Each summary is 2-3 sentences summarizing the candidate's holistic performance in that pillar relative to the target role, grounded only in that pillar's scores and evidence. Do not invent scores, percentages, or comparisons against other candidates; any comparative performance indicator is computed separately by MindQ.

Output rules:
- competency_breakdown must contain one entry per item in assessment_scores, echoing its assessment_key and assessment_name exactly. Do not add entries for assessments that are not listed.
- category_summaries must contain one entry per psychometric category (Cognitive, Personality, or Behavioral) present in assessment_scores, echoing the category name exactly. Do not add a Technical entry and do not add entries for pillars with no assessments listed.
- performance_summary is a single sentence (no line breaks, no lists) that references the score level and what it indicates about the candidate's ability in that area, relative to the target role.
- executive_summary is 3-5 sentences synthesizing the candidate's profile across categories against the target role. Describe abilities and tendencies; do not state or imply a hiring decision, a ranking, or an overall fit percentage.
- strengths and risks_and_antipatterns each contain 3-6 specific bullet points grounded in the scores and evidence. Each bullet is one complete sentence.
- Use only the provided data. Do not invent employers, experience, or skills.
- MCQ scores are objective; do not infer which options were correct.
- sjt items carry credit (0-1, where 1 is the best available response); treat credit as authoritative and never re-rank options.
- crt items carry reasoning ("reflective", "intuitive", "unanswered", "ungraded"); treat it as authoritative and never re-solve the problem.
- When an assessment includes interpersonal_profile, its dominance, warmth, angle_deg, and style_label are pre-computed and authoritative; interpret them, never recompute them.
- When an open-ended item includes benchmark_rubric, use it as the grading rubric for that answer.
- If evidence is thin or the candidate did not finish, say so in risks_and_antipatterns.
- Do not generate interview questions, conversation prompts, or interview guides.
""" + UNTRUSTED_DATA_RULES


def build_user_prompt(
    *,
    target_role: str,
    job_description: str,
    candidate_name: str,
    package_title: str,
    assessment_scores_json: str,
    evidence_json: str,
) -> str:
    """Assemble the user turn.

    The role, job description, package title, and score table are ops-authored
    or server-computed. The candidate name and the evidence (which embeds
    free-text answers) are fenced as untrusted data.

    Args:
        target_role: Role the candidate is assessed for.
        job_description: Role brief.
        candidate_name: Candidate display name (untrusted).
        package_title: Package title.
        assessment_scores_json: Serialized server-computed score table.
        evidence_json: Serialized public evidence (untrusted).

    Returns:
        Prompt string for ``generate_content``.
    """
    nonce = new_nonce()
    return (
        "Write the MindQ Report narrative for this candidate.\n\n"
        f"Target role: {target_role.strip() or package_title}\n\n"
        f"Job description:\n{job_description.strip()}\n\n"
        f"Candidate: {fence_untrusted('candidate_name', candidate_name, nonce, max_chars=MAX_NAME_PROMPT_CHARS)}\n"
        f"Package: {package_title}\n\n"
        f"assessment_scores (JSON):\n{assessment_scores_json}\n\n"
        "assessment_evidence (JSON):\n"
        f"{fence_untrusted('assessment_evidence', evidence_json, nonce, max_chars=MAX_EVIDENCE_PROMPT_CHARS)}"
    )
