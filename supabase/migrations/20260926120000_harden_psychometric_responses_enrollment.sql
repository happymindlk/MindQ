-- Harden HR visibility of psychometric answers + invite-only package enrollment.
-- HR may still SELECT technical assessment responses; psychometric response rows
-- are ops-only (mirrors assessments_select_ops_or_technical).

alter table public.packages
    add column if not exists allow_open_enrollment boolean not null default false;

comment on column public.packages.allow_open_enrollment is
    'When false (default), package access codes only admit pre-invited candidates. '
    'When true, any email may self-register with the shared package code.';

-- Re-assert RLS on core public tables (hosted projects that drifted without RLS).
alter table public.corporates enable row level security;
alter table public.packages enable row level security;
alter table public.assessments enable row level security;
alter table public.candidates enable row level security;
alter table public.candidate_progress enable row level security;
alter table public.candidate_responses enable row level security;

drop policy if exists "candidate_responses_select_own_or_ops" on public.candidate_responses;
drop policy if exists "candidate_responses_select_ops_or_technical" on public.candidate_responses;

create policy "candidate_responses_select_ops_or_technical" on public.candidate_responses
    for select to authenticated
    using (
        (select private.user_is_ops())
        or (
            corporate_id = (select private.user_corporate_id())
            and exists (
                select 1
                from public.assessments a
                where a.id = candidate_responses.assessment_id
                  and coalesce(a.module_kind, 'technical') = 'technical'
            )
        )
    );
