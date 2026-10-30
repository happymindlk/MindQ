-- Catch-up for QA schema drift: additive candidate_progress / response columns
-- that exist on the SQLAlchemy models but may be missing when an intermediate
-- migration (notably 20261028120000_scoring_v2_score_details) was not applied.
-- Idempotent: every statement uses IF NOT EXISTS. Safe to paste in the SQL editor.

alter table public.candidate_progress
    add column if not exists client_duration_seconds numeric(10, 2),
    add column if not exists server_duration_seconds numeric(10, 2),
    add column if not exists overtime boolean not null default false,
    add column if not exists facet_scores jsonb,
    add column if not exists derived_profile jsonb,
    add column if not exists score_details jsonb,
    add column if not exists scoring_version varchar(64);

alter table public.candidate_responses
    add column if not exists elapsed_seconds numeric(8, 2);

alter table public.global_modules
    add column if not exists scoring_profile varchar(50);

alter table public.assessments
    add column if not exists scoring_profile varchar(50);

comment on column public.candidate_progress.score_details is
    'MindQ scoring v2 instrument payload (band, subscales, completeness).';
comment on column public.candidate_progress.scoring_version is
    'Scoring-spec version string, e.g. mindq-scoring-2.0.0. Nullable; no default.';
