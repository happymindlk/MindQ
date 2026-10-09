-- JD-fit outcomes become visible: failed Gemini runs are persisted instead of
-- vanishing into logs. 'ok' rows carry payload; 'failed' rows carry last_error,
-- an empty payload, and a null overall_fit, and are retried on the next read.

alter table public.candidate_evaluations
    add column if not exists status text not null default 'ok',
    add column if not exists last_error text;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'candidate_evaluations_status_check'
          and conrelid = 'public.candidate_evaluations'::regclass
    ) then
        alter table public.candidate_evaluations
            add constraint candidate_evaluations_status_check
            check (status in ('ok', 'failed'));
    end if;
end;
$$;

comment on column public.candidate_evaluations.status is
    'ok = payload holds a JD-fit evaluation; failed = last attempt failed (see last_error).';
comment on column public.candidate_evaluations.last_error is
    'Provider/timeout error from the most recent failed attempt; null when status = ok.';
