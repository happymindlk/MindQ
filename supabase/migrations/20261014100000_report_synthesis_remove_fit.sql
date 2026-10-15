-- MindQ Report synthesis replaces the JD-fit evaluation: no overall fit score and
-- no hiring recommendation anywhere. candidate_evaluations.overall_fit is kept
-- (always null) until a contract-phase migration drops it.

update public.candidate_evaluations
   set overall_fit = null,
       payload = payload
           - 'overall_fit'
           - 'hiring_recommendation'
           - 'recommendation'
           - 'competencies'
           - 'per_assessment'
 where overall_fit is not null
    or payload ?| array['overall_fit', 'hiring_recommendation', 'recommendation', 'competencies', 'per_assessment'];

comment on column public.candidate_evaluations.overall_fit is
    'Deprecated: always null. Scheduled for removal.';
comment on column public.candidate_evaluations.payload is
    'MindQ Report synthesis: executive_summary, strengths, risks_and_antipatterns, competency_breakdown.';
comment on column public.candidate_evaluations.status is
    'ok = payload holds a report synthesis; failed = last attempt failed (see last_error).';

-- Pipeline "completed" now means a usable synthesis exists, not that a fit score exists.
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
join public.packages pk on pk.id = c.package_id;

grant select on public.candidate_overview to authenticated, service_role;
