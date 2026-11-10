-- Pre-computed MindQ Report JSON for HR/Admin "View Report".
-- Written by FastAPI after package scoring / synthesis; HR is SELECT-only.

create table public.candidate_reports (
    id                uuid primary key default gen_random_uuid(),
    corporate_id      uuid not null references public.corporates(id) on delete cascade,
    candidate_id      uuid not null references public.candidates(id) on delete cascade,
    package_id        uuid not null references public.packages(id) on delete cascade,
    payload           jsonb not null,
    pdf_cache_key     text,
    synthesis_status  text not null default 'pending',
    generated_at      timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    unique (candidate_id),
    constraint candidate_reports_synthesis_status_check
        check (synthesis_status in ('pending', 'generating', 'ok', 'failed'))
);

create index candidate_reports_corporate_id_idx
    on public.candidate_reports (corporate_id);

create index candidate_reports_package_id_idx
    on public.candidate_reports (package_id);

comment on table public.candidate_reports is
    'Cached MindQ Report JSON assembled after final scoring; View Report reads this row.';
comment on column public.candidate_reports.payload is
    'Full MindQReportResponse JSON (scores + narrative) for instant GET.';
comment on column public.candidate_reports.pdf_cache_key is
    'Content-addressed storage key for the compiled PDF, when known.';

alter table public.candidate_reports enable row level security;
grant select on public.candidate_reports to authenticated;
grant all on public.candidate_reports to service_role;
revoke insert, update, delete on public.candidate_reports from authenticated;

create policy "candidate_reports_select_own_or_ops" on public.candidate_reports
    for select to authenticated
    using (
        (select private.user_is_ops())
        or corporate_id = (select private.user_corporate_id())
    );
