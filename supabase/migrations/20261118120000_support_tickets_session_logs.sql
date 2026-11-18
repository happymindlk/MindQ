-- Issue 02: expand support_tickets + add candidate_session_logs audit trail.
-- FastAPI uses service_role; HR SELECT on support tickets stays tenant-scoped.

-- ---------------------------------------------------------------------------
-- support_tickets: contact + device context columns
-- ---------------------------------------------------------------------------
alter table public.support_tickets
    add column if not exists submitter_email text,
    add column if not exists contact_number text,
    add column if not exists access_code_entered text,
    add column if not exists entered_name text,
    add column if not exists issue_category text not null default 'TECHNICAL',
    add column if not exists description text,
    add column if not exists device_id text,
    add column if not exists browser text,
    add column if not exists page_url text,
    add column if not exists status text not null default 'OPEN';

-- Backfill description from legacy details; then require description going forward.
update public.support_tickets
set description = details
where description is null;

alter table public.support_tickets
    alter column description set not null;

-- Legacy rows may lack contact fields; keep nullable for history but new inserts
-- always supply them via the FastAPI support endpoint.
comment on column public.support_tickets.submitter_email is
    'Required on new tickets; nullable only for pre-Issue-02 rows.';
comment on column public.support_tickets.contact_number is
    'Required on new tickets; nullable only for pre-Issue-02 rows.';
comment on column public.support_tickets.description is
    'Issue body (mirrors details for newer clients).';

create index if not exists support_tickets_status_idx
    on public.support_tickets (status);

create index if not exists support_tickets_device_id_idx
    on public.support_tickets (device_id)
    where device_id is not null;

-- ---------------------------------------------------------------------------
-- candidate_session_logs: login / module timing audit trail
-- ---------------------------------------------------------------------------
create table if not exists public.candidate_session_logs (
    id                 uuid primary key default gen_random_uuid(),
    corporate_id       uuid not null references public.corporates(id) on delete cascade,
    candidate_id       uuid not null references public.candidates(id) on delete cascade,
    assessment_id      uuid references public.assessments(id) on delete set null,
    assessment_name    text,
    event_type         text not null
        check (event_type in ('LOGIN', 'MODULE_START', 'MODULE_COMPLETE', 'MODULE_TIMEOUT')),
    occurred_at        timestamptz not null default now(),
    duration_seconds   integer,
    device_id          text,
    browser            text,
    ip_hash            text
);

create index if not exists candidate_session_logs_candidate_occurred_idx
    on public.candidate_session_logs (candidate_id, occurred_at desc);

create index if not exists candidate_session_logs_corporate_id_idx
    on public.candidate_session_logs (corporate_id);

create index if not exists candidate_session_logs_event_type_idx
    on public.candidate_session_logs (event_type);

alter table public.candidate_session_logs enable row level security;

grant select on public.candidate_session_logs to authenticated;
grant all on public.candidate_session_logs to service_role;

create policy "candidate_session_logs_select_own" on public.candidate_session_logs
    for select to authenticated
    using (corporate_id = private.user_corporate_id());
