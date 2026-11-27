-- P2-01 / P2-02: at-most-once transactional email delivery.
--
-- sent_emails: the ARQ worker claims a row keyed on the job's idempotency key
-- (job_id + enqueue time) BEFORE calling SES. A worker restart that re-runs an
-- interrupted invite / nudge / share job finds the row and skips the send.
--
-- candidates.hr_notified_at: the HR "package complete" email is claimed with
-- UPDATE ... WHERE hr_notified_at IS NULL RETURNING, so two modules finalized
-- close together (sweep, retries, reconciler) send exactly one email. An HR
-- reset clears it so a retake notifies again.

create table if not exists public.sent_emails (
    idempotency_key text primary key,
    kind text not null,
    created_at timestamptz not null default now()
);

comment on table public.sent_emails is
    'Send markers for queued transactional emails (invite, nudge, package share). '
    'Written by the API service role before SES is called; never exposed to HR.';

create index if not exists ix_sent_emails_created_at
    on public.sent_emails (created_at);

-- Service-role only: RLS on with no policies denies anon / authenticated.
alter table public.sent_emails enable row level security;

alter table public.candidates
    add column if not exists hr_notified_at timestamptz;

comment on column public.candidates.hr_notified_at is
    'When the HR package-completion email was claimed/sent. NULL = not yet sent. '
    'Cleared by HR reset.';
