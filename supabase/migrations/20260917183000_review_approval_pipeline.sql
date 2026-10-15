-- HR blind-review approval flags + richer candidate_overview for History/pipeline.

alter table public.packages
    add column if not exists client_approved boolean not null default false,
    add column if not exists reviewed_at timestamptz;

-- Recreate overview with completed_at (when fully done) and technical-only score.
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
    (select e.overall_fit from public.candidate_evaluations e
        where e.candidate_id = c.id) as jd_fit,
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
join public.packages pk on pk.id = c.package_id;

grant select on public.candidate_overview to authenticated, service_role;
