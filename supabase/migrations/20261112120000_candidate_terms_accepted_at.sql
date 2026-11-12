-- Record when the candidate accepted Privacy Policy + Terms at OTP sign-in.
-- Nullable: invited-but-never-signed-in rows and legacy candidates have no stamp
-- until their next OTP verify/login.

alter table public.candidates
    add column if not exists terms_accepted_at timestamptz;

comment on column public.candidates.terms_accepted_at is
    'UTC timestamp when the candidate accepted Privacy Policy and Terms at OTP login; null until first consented sign-in.';
