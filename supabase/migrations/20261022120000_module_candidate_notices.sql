-- Module-level candidate notices: top disclaimer + confidentiality/integrity
-- notice, editable per psychometric module in the Standard Library and
-- snapshotted onto assessments at package publish (mirrors timer config).

alter table public.global_modules
    add column if not exists show_top_disclaimer boolean not null default false,
    add column if not exists top_disclaimer_text text not null
        default 'There are no right or wrong answers for this assessment. Answer all questions from your own perspective.',
    add column if not exists show_confidentiality_notice boolean not null default false,
    add column if not exists confidentiality_notice_text text not null
        default 'CONFIDENTIALITY & INTEGRITY NOTICE
This assessment is monitored for unauthorized AI assistance, automated inputs, and screen capture. Copying, reproducing, or sharing these questions is strictly prohibited. Violations will result in immediate test invalidation and reporting to the hiring organization.';

alter table public.assessments
    add column if not exists show_top_disclaimer boolean not null default false,
    add column if not exists top_disclaimer_text text not null
        default 'There are no right or wrong answers for this assessment. Answer all questions from your own perspective.',
    add column if not exists show_confidentiality_notice boolean not null default false,
    add column if not exists confidentiality_notice_text text not null
        default 'CONFIDENTIALITY & INTEGRITY NOTICE
This assessment is monitored for unauthorized AI assistance, automated inputs, and screen capture. Copying, reproducing, or sharing these questions is strictly prohibited. Violations will result in immediate test invalidation and reporting to the hiring organization.';

-- Preserve the previously hard-coded runner behaviour: psychometric modules
-- and their already-published assessment snapshots showed the notice.
update public.global_modules
   set show_confidentiality_notice = true
 where module_kind = 'psychometric';

update public.assessments
   set show_confidentiality_notice = true
 where module_kind = 'psychometric';

comment on column public.global_modules.show_top_disclaimer is
    'When true, top_disclaimer_text renders above every question in this module.';
comment on column public.global_modules.show_confidentiality_notice is
    'When true, confidentiality_notice_text renders bold-italic below the answers of every question in this module.';
comment on column public.assessments.show_top_disclaimer is
    'Snapshot of global_modules.show_top_disclaimer taken at package publish.';
comment on column public.assessments.show_confidentiality_notice is
    'Snapshot of global_modules.show_confidentiality_notice taken at package publish.';

-- Defense in depth: published modules are immutable in runner-facing fields.
-- Recreate the guard from 20261005120000 with the notice columns included.
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
           or new.show_top_disclaimer is distinct from old.show_top_disclaimer
           or new.top_disclaimer_text is distinct from old.top_disclaimer_text
           or new.show_confidentiality_notice is distinct from old.show_confidentiality_notice
           or new.confidentiality_notice_text is distinct from old.confidentiality_notice_text
           or new.version is distinct from old.version
           or new.lineage_id is distinct from old.lineage_id then
            raise exception 'Module % is published and locked; clone a new version', old.id
                using errcode = '23514';
        end if;
    end if;
    return new;
end;
$$;
