-- Dynamic assessment builder: module versioning + immutability, timer config,
-- per-question response telemetry, and the assessment-media storage bucket.

-- ---------------------------------------------------------------------------
-- global_modules: lifecycle, lineage, and runner configuration.
-- `assessment_category` is the psychometric taxonomy shown in the builder hub;
-- `module_kind` keeps its psychometric|technical meaning for HR visibility rules.
-- ---------------------------------------------------------------------------
alter table public.global_modules
    add column if not exists assessment_category text
        check (assessment_category in ('behavioral', 'cognitive', 'personality')),
    add column if not exists status text not null default 'draft'
        check (status in ('draft', 'published')),
    add column if not exists version integer not null default 1
        check (version >= 1),
    add column if not exists lineage_id uuid,
    add column if not exists parent_module_id uuid
        references public.global_modules(id) on delete set null,
    add column if not exists published_at timestamptz,
    add column if not exists timer_mode text not null default 'flexible'
        check (timer_mode in ('strict', 'flexible')),
    add column if not exists duration_seconds integer
        check (duration_seconds is null or (duration_seconds >= 0 and duration_seconds <= 28800)),
    add column if not exists shuffle_questions boolean not null default false;

-- Backfill: everything already in the catalog is treated as live v1.
update public.global_modules
   set lineage_id = coalesce(lineage_id, id),
       status = 'published',
       published_at = coalesce(published_at, updated_at, now()),
       duration_seconds = coalesce(duration_seconds, time_limit_minutes * 60)
 where lineage_id is null;

update public.global_modules
   set assessment_category = case
         when slug ~* '(cognitive|reasoning|numerical|verbal|abstract|crt|logic)'
           or title ~* '(cognitive|reasoning|numerical|verbal|abstract|logic)'
           then 'cognitive'
         when slug ~* '(personality|hexaco|ipip|big-five|emotional|motivation|drive)'
           or title ~* '(personality|hexaco|ipip|big five|emotional|motivation)'
           then 'personality'
         else 'behavioral'
       end
 where module_kind = 'psychometric'
   and assessment_category is null;

alter table public.global_modules
    alter column lineage_id set not null;

create unique index if not exists global_modules_lineage_version_uidx
    on public.global_modules (lineage_id, version);

create index if not exists global_modules_status_idx
    on public.global_modules (status, is_active);

comment on column public.global_modules.lineage_id is
    'Shared id across all versions of one logical module (v1 row id).';
comment on column public.global_modules.timer_mode is
    'strict = client lock + auto-submit at expiry (server rejects late saves); '
    'flexible = timer shown or silent, overtime flagged but never terminated.';

-- New rows default lineage_id to their own id.
create or replace function private.global_modules_default_lineage()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.lineage_id is null then
        new.lineage_id := new.id;
    end if;
    return new;
end;
$$;

drop trigger if exists global_modules_default_lineage on public.global_modules;
create trigger global_modules_default_lineage
    before insert on public.global_modules
    for each row execute function private.global_modules_default_lineage();

-- Defense in depth: published modules are immutable in scoring-relevant fields.
-- The API returns 409 MODULE_LOCKED first; this catches direct SQL / RLS writes.
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
           or new.version is distinct from old.version
           or new.lineage_id is distinct from old.lineage_id then
            raise exception 'Module % is published and locked; clone a new version', old.id
                using errcode = '23514';
        end if;
    end if;
    return new;
end;
$$;

drop trigger if exists global_modules_guard_published on public.global_modules;
create trigger global_modules_guard_published
    before update on public.global_modules
    for each row execute function private.guard_published_global_module();

create or replace function private.guard_published_template_question()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
    v_template uuid;
    v_status text;
begin
    v_template := coalesce(new.template_id, old.template_id);
    select status into v_status from public.global_modules where id = v_template;
    if v_status = 'published' then
        raise exception 'Questions of published module % are locked; clone a new version', v_template
            using errcode = '23514';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

drop trigger if exists template_questions_guard_published on public.template_questions;
create trigger template_questions_guard_published
    before insert or update or delete on public.template_questions
    for each row execute function private.guard_published_template_question();

-- ---------------------------------------------------------------------------
-- assessments: runner configuration snapshot (copied at add-template/publish).
-- ---------------------------------------------------------------------------
alter table public.assessments
    add column if not exists timer_mode text not null default 'flexible'
        check (timer_mode in ('strict', 'flexible')),
    add column if not exists duration_seconds integer
        check (duration_seconds is null or (duration_seconds >= 0 and duration_seconds <= 28800)),
    add column if not exists shuffle_questions boolean not null default false;

update public.assessments
   set duration_seconds = time_limit_minutes * 60
 where duration_seconds is null
   and time_limit_minutes is not null;

-- ---------------------------------------------------------------------------
-- Cognitive velocity telemetry.
-- ---------------------------------------------------------------------------
alter table public.candidate_responses
    add column if not exists elapsed_seconds numeric(8, 2)
        check (elapsed_seconds is null or elapsed_seconds >= 0);

alter table public.candidate_progress
    add column if not exists client_duration_seconds numeric(10, 2)
        check (client_duration_seconds is null or client_duration_seconds >= 0),
    add column if not exists server_duration_seconds numeric(10, 2)
        check (server_duration_seconds is null or server_duration_seconds >= 0),
    add column if not exists overtime boolean not null default false,
    add column if not exists facet_scores jsonb;

comment on column public.candidate_responses.elapsed_seconds is
    'Client-measured active time on the question (sum of visits). Advisory only.';
comment on column public.candidate_progress.server_duration_seconds is
    'Authoritative module duration derived from started_at/completed_at.';

-- ---------------------------------------------------------------------------
-- assessment-media: public-read puzzle assets, ops-only writes.
-- SVG is excluded: it can carry script and is served from the project origin.
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'assessment-media',
    'assessment-media',
    true,
    5242880,
    array['image/png', 'image/jpeg', 'image/webp']
)
on conflict (id) do update
    set public = excluded.public,
        file_size_limit = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "assessment_media_public_read" on storage.objects;
create policy "assessment_media_public_read"
    on storage.objects
    for select
    to anon, authenticated
    using (bucket_id = 'assessment-media');

drop policy if exists "assessment_media_ops_insert" on storage.objects;
create policy "assessment_media_ops_insert"
    on storage.objects
    for insert
    to authenticated
    with check (
        bucket_id = 'assessment-media'
        and (select private.user_is_ops())
    );

drop policy if exists "assessment_media_ops_update" on storage.objects;
create policy "assessment_media_ops_update"
    on storage.objects
    for update
    to authenticated
    using (
        bucket_id = 'assessment-media'
        and (select private.user_is_ops())
    )
    with check (
        bucket_id = 'assessment-media'
        and (select private.user_is_ops())
    );

drop policy if exists "assessment_media_ops_delete" on storage.objects;
create policy "assessment_media_ops_delete"
    on storage.objects
    for delete
    to authenticated
    using (
        bucket_id = 'assessment-media'
        and (select private.user_is_ops())
    );
