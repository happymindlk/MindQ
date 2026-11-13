-- Soft-delete candidates: hide from active views while preserving history.
-- Partial unique index lets the same email be re-invited after soft delete.

alter table public.candidates
    add column if not exists deleted_at timestamptz;

comment on column public.candidates.deleted_at is
    'Set when an ops admin soft-deletes the candidate; null means active.';

-- Drop the table-level unique on (package_id, email) regardless of constraint name.
do $$
declare
  con_name text;
begin
  select c.conname into con_name
  from pg_constraint c
  join pg_class t on t.oid = c.conrelid
  join pg_namespace n on n.oid = t.relnamespace
  where n.nspname = 'public'
    and t.relname = 'candidates'
    and c.contype = 'u'
    and pg_get_constraintdef(c.oid) ilike '%package_id%'
    and pg_get_constraintdef(c.oid) ilike '%email%'
  limit 1;
  if con_name is not null then
    execute format('alter table public.candidates drop constraint %I', con_name);
  end if;
end $$;

create unique index if not exists uq_candidates_package_email_active
    on public.candidates (package_id, email)
    where deleted_at is null;

create index if not exists idx_candidates_package_active
    on public.candidates (package_id)
    where deleted_at is null;

-- ---------------------------------------------------------------------------
-- candidate_overview: exclude soft-deleted rows
-- ---------------------------------------------------------------------------
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
    (select round(avg(p.score), 1)
       from public.candidate_progress p
       join public.assessments a on a.id = p.assessment_id
      where p.candidate_id = c.id
        and p.score is not null
        and coalesce(a.module_kind, 'technical') = 'technical') as technical_score,
    (select round(avg(p.score), 1)
       from public.candidate_progress p
       join public.assessments a on a.id = p.assessment_id
      where p.candidate_id = c.id
        and p.score is not null
        and coalesce(a.module_kind, 'technical') = 'technical') as avg_score,
    exists (
        select 1 from public.candidate_evaluations e
         where e.candidate_id = c.id
           and e.status = 'ok'
           and e.payload <> '{}'::jsonb
    ) as evaluated,
    case
        when (select count(*) from public.assessments a where a.package_id = c.package_id) > 0
         and (select count(*) from public.candidate_progress p
                where p.candidate_id = c.id and p.status = 'COMPLETED')
             >= (select count(*) from public.assessments a where a.package_id = c.package_id)
        then (
            select max(p.completed_at)
              from public.candidate_progress p
             where p.candidate_id = c.id
               and p.status = 'COMPLETED'
        )
        else null
    end as completed_at
from public.candidates c
join public.packages pk on pk.id = c.package_id
where c.deleted_at is null;

grant select on public.candidate_overview to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- package_overview: candidate_count excludes soft-deleted
-- ---------------------------------------------------------------------------
drop view if exists public.package_overview;

create view public.package_overview
    with (security_invoker = on) as
select
    p.*,
    corp.name as corporate_name,
    corp.slug as corporate_slug,
    (select count(*)
       from public.candidates c
      where c.package_id = p.id
        and c.deleted_at is null) as candidate_count
from public.packages p
join public.corporates corp on corp.id = p.corporate_id;

grant select on public.package_overview to authenticated, service_role;
