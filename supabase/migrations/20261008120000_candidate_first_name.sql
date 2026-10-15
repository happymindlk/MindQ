-- Candidate sign-in now collects a first name (used for greetings) alongside the
-- full name shown on reports. Nullable: invited-but-never-signed-in rows and
-- legacy candidates have no first name until their next OTP sign-in.

alter table public.candidates
    add column if not exists first_name text;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'candidates_first_name_length_check'
          and conrelid = 'public.candidates'::regclass
    ) then
        alter table public.candidates
            add constraint candidates_first_name_length_check
            check (first_name is null or char_length(first_name) between 1 and 100);
    end if;
end;
$$;

comment on column public.candidates.first_name is
    'Candidate-entered first name from OTP sign-in; null until first sign-in.';
