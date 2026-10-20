-- Candidate email-OTP challenges.
--
-- Candidates prove inbox ownership with a one-time code instead of a
-- Supabase Auth OTP. otp_hash is an HMAC of the code (the code itself is
-- never stored). anon/authenticated/service_role cannot read the table,
-- so a leaked API key cannot pull codes. The FastAPI service connects
-- as the database owner and is the only writer.
--
-- This migration is idempotent and also upgrades the legacy table shape
-- created by the initial schema (attempts/max_attempts/temp_token/
-- first_name/full_name, no locked_until) to the shape the ORM expects.
-- The legacy table held no production challenges, so dropping its
-- legacy-only columns loses nothing.

create table if not exists public.candidate_login_challenges (
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

-- Legacy rename: attempts -> attempt_count (only when the new name is free).
do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'candidate_login_challenges'
          and column_name = 'attempts'
    ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'candidate_login_challenges'
          and column_name = 'attempt_count'
    ) then
        alter table public.candidate_login_challenges
            rename column attempts to attempt_count;
    end if;
end $$;

alter table public.candidate_login_challenges
    add column if not exists attempt_count integer not null default 0,
    add column if not exists locked_until timestamptz,
    add column if not exists consumed_at timestamptz,
    add column if not exists created_at timestamptz not null default now(),
    add column if not exists expires_at timestamptz,
    drop column if exists attempts,
    drop column if exists max_attempts,
    drop column if exists temp_token,
    drop column if exists first_name,
    drop column if exists full_name;

-- Normalize legacy varchar columns to the text + check shape above.
alter table public.candidate_login_challenges
    alter column email type text,
    alter column access_code type text,
    alter column otp_hash type text;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'candidate_login_challenges_email_len'
          and conrelid = 'public.candidate_login_challenges'::regclass
    ) then
        alter table public.candidate_login_challenges
            add constraint candidate_login_challenges_email_len
            check (char_length(email) between 3 and 320);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'candidate_login_challenges_access_code_len'
          and conrelid = 'public.candidate_login_challenges'::regclass
    ) then
        alter table public.candidate_login_challenges
            add constraint candidate_login_challenges_access_code_len
            check (char_length(access_code) between 1 and 36);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'candidate_login_challenges_attempt_count_nonneg'
          and conrelid = 'public.candidate_login_challenges'::regclass
    ) then
        alter table public.candidate_login_challenges
            add constraint candidate_login_challenges_attempt_count_nonneg
            check (attempt_count >= 0);
    end if;
end $$;

create index if not exists candidate_login_challenges_email_created_idx
    on public.candidate_login_challenges (email, created_at desc);

create index if not exists candidate_login_challenges_email_lock_idx
    on public.candidate_login_challenges (email)
    where locked_until is not null;

alter table public.candidate_login_challenges enable row level security;

revoke all on table public.candidate_login_challenges from public, anon, authenticated, service_role;

comment on table public.candidate_login_challenges is
    'In-progress candidate email OTP. Code is an HMAC; no session is withheld.';
