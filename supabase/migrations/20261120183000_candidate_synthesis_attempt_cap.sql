-- Hard cap on paid Gemini report-synthesis runs per candidate (cost-drain guard).
-- In-run 429/503 retries do not increment this counter; only discrete synthesis
-- jobs that enter score_against_jd_with_model do.

alter table public.candidates
    add column if not exists synthesis_attempt_count integer not null default 0;

comment on column public.candidates.synthesis_attempt_count is
    'Lifetime of Gemini report-synthesis runs for this candidate. Cap is 3; '
    'transient 429/503 retries inside one run are excluded.';
