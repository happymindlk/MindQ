-- HR / Client portal email-OTP challenges.
--
-- HR users prove inbox ownership with a one-time code emailed by FastAPI
-- via AWS SES instead of a Supabase Auth magic link / OTP email. otp_hash
-- is an HMAC of the code (the code itself is never stored).
-- anon/authenticated/service_role cannot read the table, so a leaked API
-- key cannot pull codes. The FastAPI service connects as the database
-- owner and is the only writer. Idempotent: safe to paste into the
-- Supabase SQL editor or run via `supabase migration up`.

create table if not exists public.hr_login_challenges (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.hr_users (user_id) on delete cascade,
    email text not null check (char_length(email) between 3 and 320),
    otp_hash text not null default '',
    expires_at timestamptz not null,
    attempt_count integer not null default 0 check (attempt_count >= 0),
    locked_until timestamptz,
    consumed_at timestamptz,
    created_at timestamptz not null default now()
);

alter table public.hr_login_challenges
    add column if not exists id uuid default gen_random_uuid(),
    add column if not exists user_id uuid,
    add column if not exists email text,
    add column if not exists otp_hash text not null default '',
    add column if not exists expires_at timestamptz,
    add column if not exists attempt_count integer not null default 0,
    add column if not exists locked_until timestamptz,
    add column if not exists consumed_at timestamptz,
    add column if not exists created_at timestamptz not null default now();

create index if not exists hr_login_challenges_user_created_idx
    on public.hr_login_challenges (user_id, created_at desc);

create index if not exists hr_login_challenges_user_lock_idx
    on public.hr_login_challenges (user_id)
    where locked_until is not null;

alter table public.hr_login_challenges enable row level security;

revoke all on table public.hr_login_challenges from public, anon, authenticated, service_role;

comment on table public.hr_login_challenges is
    'In-progress HR/client email OTP. Code is an HMAC; verified via FastAPI + SES, session is a backend client_hr JWT.';
