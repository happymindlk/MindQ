-- ---------------------------------------------------------------------------
-- Happy Mind: initial normalized schema
-- ---------------------------------------------------------------------------
-- Multi-tenant psychometric assessment platform. Every business row carries a
-- denormalized `corporate_id` (the tenant key) so Row Level Security can be a
-- simple, index-friendly equality check (see the rls_policies migration).
-- ---------------------------------------------------------------------------

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- Auto-maintain updated_at on UPDATE.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- Auto-maintain saved_at on UPDATE (candidate_responses uses saved_at).
create or replace function public.set_saved_at()
returns trigger
language plpgsql
as $$
begin
  new.saved_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- corporates: the tenant root.
-- ---------------------------------------------------------------------------
create table public.corporates (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    slug        text not null unique,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create trigger corporates_set_updated_at
    before update on public.corporates
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- hr_users: maps a Supabase Auth user (auth.users) to their corporate.
-- This is the source of truth the access-token hook and RLS helper read from.
-- ---------------------------------------------------------------------------
create table public.hr_users (
    user_id      uuid primary key references auth.users(id) on delete cascade,
    corporate_id uuid not null references public.corporates(id) on delete cascade,
    full_name    text,
    role         text not null default 'hr' check (role in ('hr', 'admin', 'owner')),
    created_at   timestamptz not null default now()
);

create index hr_users_corporate_id_idx on public.hr_users(corporate_id);

-- ---------------------------------------------------------------------------
-- packages: an assessment package owned by a corporate.
-- ---------------------------------------------------------------------------
create table public.packages (
    id            uuid primary key default gen_random_uuid(),
    corporate_id  uuid not null references public.corporates(id) on delete cascade,
    title         text not null,
    description   text,
    access_code   text not null unique,
    is_active     boolean not null default true,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create index packages_corporate_id_idx on public.packages(corporate_id);

create trigger packages_set_updated_at
    before update on public.packages
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- assessments: a single test within a package (normalizes the old JSON blob).
-- Questions remain JSONB (question authoring is document-shaped).
-- ---------------------------------------------------------------------------
create table public.assessments (
    id                  uuid primary key default gen_random_uuid(),
    corporate_id        uuid not null references public.corporates(id) on delete cascade,
    package_id          uuid not null references public.packages(id) on delete cascade,
    title               text not null,
    description         text,
    time_limit_minutes  integer,
    position            integer not null default 0,
    questions           jsonb not null default '[]'::jsonb,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index assessments_corporate_id_idx on public.assessments(corporate_id);
create index assessments_package_id_idx on public.assessments(package_id);

create trigger assessments_set_updated_at
    before update on public.assessments
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- candidates: a person taking a package's assessments.
-- ---------------------------------------------------------------------------
create table public.candidates (
    id            uuid primary key default gen_random_uuid(),
    corporate_id  uuid not null references public.corporates(id) on delete cascade,
    package_id    uuid not null references public.packages(id) on delete cascade,
    full_name     text not null,
    email         text not null,
    access_code   text not null,
    logged_in_at  timestamptz,
    created_at    timestamptz not null default now(),
    unique (package_id, email)
);

create index candidates_corporate_id_idx on public.candidates(corporate_id);
create index candidates_package_id_idx on public.candidates(package_id);

-- ---------------------------------------------------------------------------
-- candidate_progress: per-candidate, per-assessment status and score.
-- ---------------------------------------------------------------------------
create table public.candidate_progress (
    id            uuid primary key default gen_random_uuid(),
    corporate_id  uuid not null references public.corporates(id) on delete cascade,
    candidate_id  uuid not null references public.candidates(id) on delete cascade,
    assessment_id uuid not null references public.assessments(id) on delete cascade,
    status        text not null default 'NOT_STARTED'
                    check (status in ('NOT_STARTED', 'IN_PROGRESS', 'COMPLETED')),
    started_at    timestamptz,
    completed_at  timestamptz,
    score         numeric(5, 2),
    unique (candidate_id, assessment_id)
);

create index candidate_progress_corporate_id_idx on public.candidate_progress(corporate_id);
create index candidate_progress_candidate_id_idx on public.candidate_progress(candidate_id);
create index candidate_progress_assessment_id_idx on public.candidate_progress(assessment_id);

-- ---------------------------------------------------------------------------
-- candidate_responses: per-question saved answers (autosave + submit).
-- ---------------------------------------------------------------------------
create table public.candidate_responses (
    id            uuid primary key default gen_random_uuid(),
    corporate_id  uuid not null references public.corporates(id) on delete cascade,
    candidate_id  uuid not null references public.candidates(id) on delete cascade,
    assessment_id uuid not null references public.assessments(id) on delete cascade,
    question_id   text not null,
    response      jsonb not null,
    saved_at      timestamptz not null default now(),
    unique (candidate_id, assessment_id, question_id)
);

create index candidate_responses_corporate_id_idx on public.candidate_responses(corporate_id);
create index candidate_responses_candidate_id_idx on public.candidate_responses(candidate_id);
create index candidate_responses_assessment_id_idx on public.candidate_responses(assessment_id);

create trigger candidate_responses_set_saved_at
    before update on public.candidate_responses
    for each row execute function public.set_saved_at();
