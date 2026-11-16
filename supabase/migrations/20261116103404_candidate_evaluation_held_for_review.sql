-- Hard-list wording after retries keeps the synthesis payload (with a placeholder
-- executive summary) under status = held_for_review. Reopening must not auto-retry.

alter table public.candidate_evaluations
    drop constraint if exists candidate_evaluations_status_check;

alter table public.candidate_evaluations
    add constraint candidate_evaluations_status_check
    check (status in ('ok', 'failed', 'held_for_review'));

comment on column public.candidate_evaluations.status is
    'ok = usable synthesis; failed = empty payload + last_error (provider/parse); '
    'held_for_review = hard-list wording after retries, payload kept with placeholder summary.';
comment on column public.candidate_evaluations.last_error is
    'Provider/timeout/banned-language detail from the most recent failed or held attempt; '
    'null when status = ok.';

-- held_for_review still has a readable payload, so overview treats it as evaluated.
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
           and e.status in ('ok', 'held_for_review')
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
