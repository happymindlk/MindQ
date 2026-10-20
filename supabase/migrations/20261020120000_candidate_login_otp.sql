-- Candidate email-OTP challenges.
--
-- Candidates prove inbox ownership with a one-time code instead of a
-- Supabase Auth OTP. otp_hash is an HMAC of the code (the code itself is
-- never stored). anon/authenticated/service_role cannot read the table,
-- so a leaked API key cannot pull codes. The FastAPI service connects
-- as the database owner and is the only writer.

create table public.candidate_login_challenges (
    id uuid primary key default gen_random_uuid(),
    email text not null check (char_length(email) between 3 and 320),
    access_code text not null check (char_length(access_code) between 1 and 36),
    otp_hash text not null,
    expires_at timestamptz not null,
    attempt_count integer not null default 0 check (attempt_count >= 0),
    locked_until timestamptz,
    consumed_at timestamptz,
    created_at timestamptz not null default now()
);

create index candidate_login_challenges_email_created_idx
    on public.candidate_login_challenges (email, created_at desc);

create index candidate_login_challenges_email_lock_idx
    on public.candidate_login_challenges (email)
    where locked_until is not null;

alter table public.candidate_login_challenges enable row level security;

revoke all on table public.candidate_login_challenges from public, anon, authenticated, service_role;

comment on table public.candidate_login_challenges is
    'In-progress candidate email OTP. Code is an HMAC; no session is withheld.';
