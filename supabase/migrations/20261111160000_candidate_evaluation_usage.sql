-- Per-report Gemini token / cost visibility on cached MindQ syntheses.
alter table public.candidate_evaluations
    add column if not exists usage jsonb;

comment on column public.candidate_evaluations.usage is
    'Gemini usage for the call that wrote this row: prompt_tokens, candidates_tokens, thoughts_tokens, total_tokens, estimated_cost_usd, model.';
