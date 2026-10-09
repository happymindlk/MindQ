-- Profile resolvers: composite instruments (e.g. IPIP-IPC circumplex) derive a
-- structured profile from facet means after generic scoring.

alter table public.global_modules
    add column if not exists scoring_profile varchar(50);

alter table public.assessments
    add column if not exists scoring_profile varchar(50);

alter table public.candidate_progress
    add column if not exists derived_profile jsonb;

comment on column public.global_modules.scoring_profile is
    'Registry key of the profile resolver applied after scoring (e.g. ipip_ipc_v1).';
comment on column public.assessments.scoring_profile is
    'Snapshot of global_modules.scoring_profile copied at package publish.';
comment on column public.candidate_progress.derived_profile is
    'Versioned resolver output: {resolver, version, status, data}.';

-- The resolver changes what scores mean, so it is locked like questions.
create or replace function private.guard_published_global_module()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if old.status = 'published' then
        if new.status <> 'published' then
            raise exception 'Published module % cannot return to draft; clone a new version', old.id
                using errcode = '23514';
        end if;
        if new.questions is distinct from old.questions
           or new.duration_seconds is distinct from old.duration_seconds
           or new.time_limit_minutes is distinct from old.time_limit_minutes
           or new.timer_mode is distinct from old.timer_mode
           or new.shuffle_questions is distinct from old.shuffle_questions
           or new.scoring_profile is distinct from old.scoring_profile
           or new.version is distinct from old.version
           or new.lineage_id is distinct from old.lineage_id then
            raise exception 'Module % is published and locked; clone a new version', old.id
                using errcode = '23514';
        end if;
    end if;
    return new;
end;
$$;
