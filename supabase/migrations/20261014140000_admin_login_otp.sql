-- Admin email-OTP challenges.
--
-- A successful password grant mints a Supabase session that stays in this
-- table until the emailed code is accepted. otp_hash is an HMAC of the code
-- (the code itself is never stored). anon/authenticated/service_role cannot
-- read the table, so a leaked API key cannot pull codes or session tokens.
-- The FastAPI service connects as the database owner and is the only writer.

create table public.admin_login_challenges (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.hr_users (user_id) on delete cascade,
    email text not null check (char_length(email) between 3 and 320),
    otp_hash text not null,
    expires_at timestamptz not null,
    attempt_count integer not null default 0 check (attempt_count >= 0),
    locked_until timestamptz,
    consumed_at timestamptz,
    access_token text,
    refresh_token text,
    expires_in integer not null check (expires_in > 0),
    created_at timestamptz not null default now()
);

create index admin_login_challenges_user_created_idx
    on public.admin_login_challenges (user_id, created_at desc);

create index admin_login_challenges_user_lock_idx
    on public.admin_login_challenges (user_id)
    where locked_until is not null;

alter table public.admin_login_challenges enable row level security;

revoke all on table public.admin_login_challenges from public, anon, authenticated, service_role;

comment on table public.admin_login_challenges is
    'In-progress admin email OTP. Code is an HMAC. Session tokens are Fernet-sealed and wiped after use.';
