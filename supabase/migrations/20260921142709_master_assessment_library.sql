-- Master Assessment Library: normalize catalog questions into template_questions
-- while keeping global_modules as the template header and package_modules.questions
-- as the per-package JSONB snapshot.

-- ---------------------------------------------------------------------------
-- template_questions: canonical master-library items (FK → global_modules).
-- ---------------------------------------------------------------------------
create table if not exists public.template_questions (
    id                  uuid primary key default gen_random_uuid(),
    template_id         uuid not null references public.global_modules(id) on delete cascade,
    question_text       text not null,
    evaluation_rubric   text not null default '',
    question_payload    jsonb not null default '{}'::jsonb,
    is_active           boolean not null default true,
    position            integer not null default 0,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create trigger template_questions_set_updated_at
    before update on public.template_questions
    for each row execute function public.set_updated_at();

create index if not exists template_questions_template_pos_idx
    on public.template_questions (template_id, position)
    where is_active;

alter table public.template_questions enable row level security;
grant select on public.template_questions to authenticated;
grant all on public.template_questions to service_role;

-- Catalog is ops-only (mirror global_modules policies).
create policy "template_questions_select_ops" on public.template_questions
    for select to authenticated
    using ((select private.user_is_ops()));

create policy "template_questions_write_ops" on public.template_questions
    for all to authenticated
    using ((select private.user_is_ops()))
    with check ((select private.user_is_ops()));

-- ---------------------------------------------------------------------------
-- Backfill: explode global_modules.questions JSONB into template_questions.
-- Seeded catalog uses slug string ids (cog-01), so always mint new UUIDs.
-- Idempotent: skip when any template_questions rows already exist for a module.
-- ---------------------------------------------------------------------------
insert into public.template_questions
    (template_id, question_text, evaluation_rubric, question_payload, is_active, position)
select
    gm.id,
    coalesce(
        nullif(q.elem->>'text', ''),
        nullif(q.elem->>'prompt', ''),
        ''
    ),
    coalesce(
        nullif(q.elem->>'correct_answer_or_rubric', ''),
        nullif(q.elem->>'benchmark_rubric', ''),
        nullif(q.elem->>'correct_answer', ''),
        ''
    ),
    q.elem,
    true,
    (q.ord - 1)::integer
from public.global_modules gm
cross join lateral jsonb_array_elements(coalesce(gm.questions, '[]'::jsonb))
    with ordinality as q(elem, ord)
where coalesce(
        nullif(q.elem->>'text', ''),
        nullif(q.elem->>'prompt', ''),
        ''
      ) <> ''
  and not exists (
      select 1
        from public.template_questions tq
       where tq.template_id = gm.id
  );

-- Clarify snapshot semantics on package_modules.questions.
comment on column public.package_modules.questions is
    'Eager JSONB snapshot of template questions for this package cart row. '
    'Null only for legacy rows; new attaches always write a copy so master edits do not leak.';
