-- Gemini JD evaluations are written only by FastAPI (service_role / superuser).
-- HR clients are SELECT-only so a browser session cannot rewrite fit scores.
-- candidate_overview gains jd_fit from the latest cached evaluation.

create table public.candidate_evaluations (
    id            uuid primary key default gen_random_uuid(),
    corporate_id  uuid not null references public.corporates(id) on delete cascade,
    candidate_id  uuid not null references public.candidates(id) on delete cascade,
    package_id    uuid not null references public.packages(id) on delete cascade,
    jd_hash       text not null,
    model         text not null,
    overall_fit   numeric(5, 2),
    payload       jsonb not null,
    generated_at  timestamptz not null default now(),
    unique (candidate_id)
);

create index candidate_evaluations_corporate_id_idx
    on public.candidate_evaluations (corporate_id);

alter table public.candidate_evaluations enable row level security;
grant select on public.candidate_evaluations to authenticated;
grant all on public.candidate_evaluations to service_role;

create policy "candidate_evaluations_select_own" on public.candidate_evaluations
    for select to authenticated
    using (corporate_id = (select private.user_corporate_id()));

-- Recreate the tracker view with jd_fit (CREATE OR REPLACE cannot add a column
-- in the middle of an existing view definition on all PG versions).
drop view if exists public.candidate_overview;

create view public.candidate_overview
with (security_invoker = on) as
select
    c.id,
    c.corporate_id,
    c.package_id,
    c.full_name,
    c.email,
    c.access_code,
    c.logged_in_at,
    c.created_at,
    pk.title as package_title,
    (select count(*) from public.assessments a where a.package_id = c.package_id) as total_assessments,
    (select count(*) from public.candidate_progress p
        where p.candidate_id = c.id and p.status = 'COMPLETED') as completed_assessments,
    (select round(avg(p.score), 1) from public.candidate_progress p
        where p.candidate_id = c.id and p.score is not null) as avg_score,
    (select e.overall_fit from public.candidate_evaluations e
        where e.candidate_id = c.id) as jd_fit
from public.candidates c
join public.packages pk on pk.id = c.package_id;

grant select on public.candidate_overview to authenticated, service_role;
