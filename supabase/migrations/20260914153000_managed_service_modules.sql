-- ---------------------------------------------------------------------------
-- Managed-service pivot: Global Modules vs Client Packages.
-- Ops assembles packages from proprietary psychometric templates + custom
-- technical questions. HR is read-only and must never see psychometric items.
-- ---------------------------------------------------------------------------

-- Ops detector. JWT app_metadata.corporate_role is set by the access-token hook
-- from public.hr_users.role (not user_metadata — that claim is user-editable).
create or replace function private.user_is_ops()
returns boolean
language sql
stable
set search_path = ''
as $$
  select coalesce(
    (select auth.jwt()) -> 'app_metadata' ->> 'corporate_role',
    (select auth.jwt()) -> 'app_metadata' ->> 'role',
    ''
  ) in ('admin', 'owner');
$$;

revoke all on function private.user_is_ops() from public, anon;
grant execute on function private.user_is_ops() to authenticated, service_role;

-- Mirror corporate_role onto app_metadata.role so FastAPI and clients can
-- read a single claim. Source remains hr_users.role.
create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
as $$
declare
    claims jsonb;
    corp_id uuid;
    corp_role text;
begin
    select corporate_id, role
      into corp_id, corp_role
      from public.hr_users
     where user_id = (event ->> 'user_id')::uuid;

    claims := event -> 'claims';

    if jsonb_typeof(claims -> 'app_metadata') is distinct from 'object' then
        claims := jsonb_set(claims, '{app_metadata}', '{}'::jsonb);
    end if;

    if corp_id is not null then
        claims := jsonb_set(claims, '{app_metadata, corporate_id}', to_jsonb(corp_id::text));
        claims := jsonb_set(
            claims,
            '{app_metadata, corporate_role}',
            to_jsonb(coalesce(corp_role, 'hr'))
        );
        claims := jsonb_set(
            claims,
            '{app_metadata, role}',
            to_jsonb(coalesce(corp_role, 'hr'))
        );
    end if;

    event := jsonb_set(event, '{claims}', claims);
    return event;
end;
$$;

-- ---------------------------------------------------------------------------
-- global_modules: proprietary templates (not tenant-scoped).
-- ---------------------------------------------------------------------------
create table public.global_modules (
    id                  uuid primary key default gen_random_uuid(),
    slug                text not null unique,
    title               text not null,
    description         text,
    module_kind         text not null
                          check (module_kind in ('psychometric', 'technical')),
    time_limit_minutes  integer,
    questions           jsonb not null default '[]'::jsonb,
    is_active           boolean not null default true,
    position            integer not null default 0,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create trigger global_modules_set_updated_at
    before update on public.global_modules
    for each row execute function public.set_updated_at();

create index global_modules_kind_idx on public.global_modules (module_kind, position);

alter table public.global_modules enable row level security;
grant select on public.global_modules to authenticated;
grant all on public.global_modules to service_role;

-- Catalog is ops-only. HR never lists psychometric templates via supabase-js.
create policy "global_modules_select_ops" on public.global_modules
    for select to authenticated
    using ((select private.user_is_ops()));

create policy "global_modules_write_ops" on public.global_modules
    for all to authenticated
    using ((select private.user_is_ops()))
    with check ((select private.user_is_ops()));

-- ---------------------------------------------------------------------------
-- Client packages (existing public.packages): draft/publish + review token.
-- ---------------------------------------------------------------------------
alter table public.packages
    add column if not exists status text not null default 'draft'
        check (status in ('draft', 'published')),
    add column if not exists review_token text unique,
    add column if not exists published_at timestamptz;

update public.packages
   set status = case when is_active then 'published' else 'draft' end,
       published_at = coalesce(published_at, case when is_active then updated_at else null end)
 where status = 'draft' and is_active = true;

create unique index if not exists packages_review_token_uidx
    on public.packages (review_token)
    where review_token is not null;

create index if not exists packages_status_idx on public.packages (status);

-- ---------------------------------------------------------------------------
-- package_modules: client_package ⋈ global_modules (many-to-many).
-- ---------------------------------------------------------------------------
create table public.package_modules (
    package_id        uuid not null references public.packages(id) on delete cascade,
    global_module_id  uuid not null references public.global_modules(id) on delete restrict,
    position          integer not null default 0,
    created_at        timestamptz not null default now(),
    primary key (package_id, global_module_id)
);

create index package_modules_module_idx on public.package_modules (global_module_id);

alter table public.package_modules enable row level security;
grant select on public.package_modules to authenticated;
grant all on public.package_modules to service_role;

create policy "package_modules_select_ops" on public.package_modules
    for select to authenticated
    using ((select private.user_is_ops()));

create policy "package_modules_write_ops" on public.package_modules
    for all to authenticated
    using ((select private.user_is_ops()))
    with check ((select private.user_is_ops()));

-- ---------------------------------------------------------------------------
-- custom_technical_questions: per-package items authored by ops.
-- ---------------------------------------------------------------------------
create table public.custom_technical_questions (
    id                         uuid primary key default gen_random_uuid(),
    package_id                 uuid not null references public.packages(id) on delete cascade,
    corporate_id               uuid not null references public.corporates(id) on delete cascade,
    prompt                     text not null,
    question_type              text not null default 'mcq'
                                 check (question_type in ('mcq', 'likert', 'open_ended')),
    options                    jsonb not null default '[]'::jsonb,
    correct_answer_or_rubric   text not null default '',
    evaluated_competency       text not null default 'Technical',
    weight                     integer not null default 3
                                 check (weight >= 1 and weight <= 5),
    likert_label_1             text,
    likert_label_5             text,
    position                   integer not null default 0,
    created_at                 timestamptz not null default now(),
    updated_at                 timestamptz not null default now()
);

create index custom_technical_questions_package_idx
    on public.custom_technical_questions (package_id, position);

create trigger custom_technical_questions_set_updated_at
    before update on public.custom_technical_questions
    for each row execute function public.set_updated_at();

alter table public.custom_technical_questions enable row level security;
grant select on public.custom_technical_questions to authenticated;
grant all on public.custom_technical_questions to service_role;

-- HR may read their tenant's custom items (review/scorecard). Writes are ops.
create policy "custom_technical_questions_select_tenant" on public.custom_technical_questions
    for select to authenticated
    using (
        (select private.user_is_ops())
        or corporate_id = (select private.user_corporate_id())
    );

create policy "custom_technical_questions_write_ops" on public.custom_technical_questions
    for all to authenticated
    using ((select private.user_is_ops()))
    with check ((select private.user_is_ops()));

-- ---------------------------------------------------------------------------
-- assessments: snapshot kind so HR review can filter psychometric rows.
-- ---------------------------------------------------------------------------
alter table public.assessments
    add column if not exists module_kind text not null default 'technical'
        check (module_kind in ('psychometric', 'technical')),
    add column if not exists global_module_id uuid
        references public.global_modules(id) on delete set null;

create index if not exists assessments_module_kind_idx
    on public.assessments (package_id, module_kind);

-- ---------------------------------------------------------------------------
-- RLS: ops sees every tenant; HR stays tenant-scoped and cannot author packages.
-- ---------------------------------------------------------------------------
drop policy if exists "corporates_select_own" on public.corporates;
create policy "corporates_select_own_or_ops" on public.corporates
    for select to authenticated
    using (
        (select private.user_is_ops())
        or id = (select private.user_corporate_id())
    );

drop policy if exists "packages_select_own" on public.packages;
create policy "packages_select_own_or_ops" on public.packages
    for select to authenticated
    using (
        (select private.user_is_ops())
        or corporate_id = (select private.user_corporate_id())
    );

drop policy if exists "packages_insert_own" on public.packages;
create policy "packages_insert_ops" on public.packages
    for insert to authenticated
    with check ((select private.user_is_ops()));

drop policy if exists "packages_update_own" on public.packages;
create policy "packages_update_ops" on public.packages
    for update to authenticated
    using ((select private.user_is_ops()))
    with check ((select private.user_is_ops()));

drop policy if exists "assessments_select_own" on public.assessments;
-- HR may SELECT technical snapshots only. Psychometric items stay ops-only
-- (FastAPI review endpoint also filters — defense in depth).
create policy "assessments_select_ops_or_technical" on public.assessments
    for select to authenticated
    using (
        (select private.user_is_ops())
        or (
            corporate_id = (select private.user_corporate_id())
            and module_kind = 'technical'
        )
    );

drop policy if exists "assessments_insert_own" on public.assessments;
create policy "assessments_insert_ops" on public.assessments
    for insert to authenticated
    with check ((select private.user_is_ops()));

drop policy if exists "assessments_update_own" on public.assessments;
create policy "assessments_update_ops" on public.assessments
    for update to authenticated
    using ((select private.user_is_ops()))
    with check ((select private.user_is_ops()));

drop policy if exists "candidates_select_own" on public.candidates;
create policy "candidates_select_own_or_ops" on public.candidates
    for select to authenticated
    using (
        (select private.user_is_ops())
        or corporate_id = (select private.user_corporate_id())
    );

drop policy if exists "candidate_progress_select_own" on public.candidate_progress;
create policy "candidate_progress_select_own_or_ops" on public.candidate_progress
    for select to authenticated
    using (
        (select private.user_is_ops())
        or corporate_id = (select private.user_corporate_id())
    );

drop policy if exists "candidate_responses_select_own" on public.candidate_responses;
create policy "candidate_responses_select_own_or_ops" on public.candidate_responses
    for select to authenticated
    using (
        (select private.user_is_ops())
        or corporate_id = (select private.user_corporate_id())
    );

drop policy if exists "candidate_evaluations_select_own" on public.candidate_evaluations;
create policy "candidate_evaluations_select_own_or_ops" on public.candidate_evaluations
    for select to authenticated
    using (
        (select private.user_is_ops())
        or corporate_id = (select private.user_corporate_id())
    );

-- ---------------------------------------------------------------------------
-- create_package: ops-only; optional target corporate (managed-service dispatch).
-- ---------------------------------------------------------------------------
drop function if exists public.create_package(text, text, jsonb);

create or replace function public.create_package(
    p_title text,
    p_description text,
    p_tests jsonb,
    p_corporate_id uuid default null
)
returns public.packages
language plpgsql
security invoker
set search_path = public, extensions
as $$
declare
    v_corp uuid;
    v_pkg public.packages;
    v_test jsonb;
    v_pos int := 0;
begin
    if not private.user_is_ops() then
        raise exception 'Operations role required' using errcode = '42501';
    end if;

    v_corp := coalesce(p_corporate_id, private.user_corporate_id());
    if v_corp is null then
        raise exception 'No corporate context in token' using errcode = '42501';
    end if;

    insert into public.packages (
        corporate_id, title, description, access_code, track_secret, status, is_active
    )
    values (
        v_corp,
        p_title,
        nullif(p_description, ''),
        public.gen_access_code(),
        encode(gen_random_bytes(24), 'hex'),
        'published',
        true
    )
    returning * into v_pkg;

    update public.packages
       set published_at = now()
     where id = v_pkg.id;

    for v_test in select * from jsonb_array_elements(coalesce(p_tests, '[]'::jsonb))
    loop
        insert into public.assessments (
            corporate_id, package_id, title, description,
            time_limit_minutes, position, questions, module_kind
        )
        values (
            v_corp,
            v_pkg.id,
            coalesce(v_test ->> 'title', 'Untitled'),
            v_test ->> 'description',
            nullif(v_test ->> 'time_limit_minutes', '')::int,
            v_pos,
            coalesce(v_test -> 'questions', '[]'::jsonb),
            coalesce(nullif(v_test ->> 'module_kind', ''), 'technical')
        );
        v_pos := v_pos + 1;
    end loop;

    return v_pkg;
end;
$$;

grant execute on function public.create_package(text, text, jsonb, uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- package_overview: include tenant name + lifecycle for the history grid.
-- ---------------------------------------------------------------------------
drop view if exists public.package_overview;

create view public.package_overview
with (security_invoker = on) as
select
    p.*,
    corp.name as corporate_name,
    corp.slug as corporate_slug,
    (select count(*) from public.candidates c where c.package_id = p.id) as candidate_count
from public.packages p
join public.corporates corp on corp.id = p.corporate_id;

grant select on public.package_overview to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Seed: 6 proprietary psychometric modules + technical blocks.
-- Question JSONB matches the candidate-portal storage shape.
-- ---------------------------------------------------------------------------
insert into public.global_modules
    (id, slug, title, description, module_kind, time_limit_minutes, position, questions)
values
(
    'a1000000-0000-4000-8000-000000000001',
    'cognitive-ability',
    'Cognitive Ability',
    'Reasoning, pattern recognition, and working-memory items.',
    'psychometric',
    20,
    1,
    '[
      {"id":"cog-01","text":"Which number completes the series: 2, 6, 12, 20, 30, ?","type":"mcq","options":["40","42","44","46"],"correct_answer":"42","evaluated_competency":"Numerical reasoning","weight":3,"builder_type":"mcq"},
      {"id":"cog-02","text":"If all Bloops are Razzies and some Razzies are Lazzies, which statement must be true?","type":"mcq","options":["All Bloops are Lazzies","Some Bloops are Lazzies","Some Bloops may be Lazzies","No Bloops are Lazzies"],"correct_answer":"Some Bloops may be Lazzies","evaluated_competency":"Verbal reasoning","weight":4,"builder_type":"mcq"},
      {"id":"cog-03","text":"I prefer tasks that require holding several constraints in mind at once.","type":"likert","options":[],"likert_label_1":"Strongly Disagree","likert_label_5":"Strongly Agree","evaluated_competency":"Working memory","weight":2,"builder_type":"likert"}
    ]'::jsonb
),
(
    'a1000000-0000-4000-8000-000000000002',
    'personality-inventory',
    'Personality Inventory',
    'Big-Five workplace inventory (Likert).',
    'psychometric',
    15,
    2,
    '[
      {"id":"per-01","text":"I stay calm when priorities shift without warning.","type":"likert","options":[],"likert_label_1":"Strongly Disagree","likert_label_5":"Strongly Agree","evaluated_competency":"Emotional stability","weight":3,"builder_type":"likert"},
      {"id":"per-02","text":"I prefer structured plans over improvising.","type":"likert","options":[],"likert_label_1":"Strongly Disagree","likert_label_5":"Strongly Agree","evaluated_competency":"Conscientiousness","weight":3,"builder_type":"likert"},
      {"id":"per-03","text":"I seek out unfamiliar problems even when the current approach works.","type":"likert","options":[],"likert_label_1":"Strongly Disagree","likert_label_5":"Strongly Agree","evaluated_competency":"Openness","weight":3,"builder_type":"likert"}
    ]'::jsonb
),
(
    'a1000000-0000-4000-8000-000000000003',
    'emotional-intelligence',
    'Emotional Intelligence',
    'Self-regulation, empathy, and interpersonal judgment.',
    'psychometric',
    12,
    3,
    '[
      {"id":"eq-01","text":"I can name what I am feeling while a discussion is still heated.","type":"likert","options":[],"likert_label_1":"Almost never","likert_label_5":"Almost always","evaluated_competency":"Self-awareness","weight":3,"builder_type":"likert"},
      {"id":"eq-02","text":"When a colleague withdraws, I check in before assuming intent.","type":"likert","options":[],"likert_label_1":"Almost never","likert_label_5":"Almost always","evaluated_competency":"Empathy","weight":3,"builder_type":"likert"}
    ]'::jsonb
),
(
    'a1000000-0000-4000-8000-000000000004',
    'motivation-drive',
    'Motivation & Drive',
    'Achievement orientation, persistence, and autonomy preference.',
    'psychometric',
    10,
    4,
    '[
      {"id":"mot-01","text":"I set a higher bar for my own work than the role requires.","type":"likert","options":[],"likert_label_1":"Strongly Disagree","likert_label_5":"Strongly Agree","evaluated_competency":"Achievement","weight":3,"builder_type":"likert"},
      {"id":"mot-02","text":"Unfinished work bothers me until it is closed.","type":"likert","options":[],"likert_label_1":"Strongly Disagree","likert_label_5":"Strongly Agree","evaluated_competency":"Persistence","weight":3,"builder_type":"likert"}
    ]'::jsonb
),
(
    'a1000000-0000-4000-8000-000000000005',
    'integrity-ethic',
    'Integrity & Work Ethic',
    'Honesty, reliability, and policy adherence (forced-choice + Likert).',
    'psychometric',
    12,
    5,
    '[
      {"id":"int-01","text":"I would report a process bypass even if it delayed a launch.","type":"likert","options":[],"likert_label_1":"Strongly Disagree","likert_label_5":"Strongly Agree","evaluated_competency":"Integrity","weight":4,"builder_type":"likert"},
      {"id":"int-02","text":"A teammate asks you to mark their review as done so they can leave early. What do you do?","type":"mcq","options":["Mark it done and mention it later","Refuse and offer to cover the remaining checks","Ignore the request","Escalate immediately to HR"],"correct_answer":"Refuse and offer to cover the remaining checks","evaluated_competency":"Work ethic","weight":4,"builder_type":"mcq"}
    ]'::jsonb
),
(
    'a1000000-0000-4000-8000-000000000006',
    'situational-judgment',
    'Situational Judgment',
    'Workplace scenarios scored against a proprietary key.',
    'psychometric',
    18,
    6,
    '[
      {"id":"sjt-01","text":"A stakeholder demands a commitment you know the team cannot meet this sprint. Best action?","type":"mcq","options":["Agree and ask the team to stretch","State the constraint and offer a dated alternative","Escalate without a proposal","Ignore until the next standup"],"correct_answer":"State the constraint and offer a dated alternative","evaluated_competency":"Stakeholder judgment","weight":4,"builder_type":"mcq"},
      {"id":"sjt-02","text":"Two peers disagree in a client meeting. Your next move?","type":"mcq","options":["Pick a side publicly","Pause, restate both positions, park the decision","Let them finish then change the subject","Message your manager mid-meeting"],"correct_answer":"Pause, restate both positions, park the decision","evaluated_competency":"Conflict judgment","weight":4,"builder_type":"mcq"}
    ]'::jsonb
),
(
    'b1000000-0000-4000-8000-000000000001',
    'sql-fundamentals',
    'SQL Fundamentals',
    'Joins, aggregation, and query-shape items for analyst / backend roles.',
    'technical',
    25,
    10,
    '[
      {"id":"sql-01","text":"Which join returns only rows with matches in both tables?","type":"mcq","options":["LEFT JOIN","RIGHT JOIN","INNER JOIN","FULL OUTER JOIN"],"correct_answer":"INNER JOIN","evaluated_competency":"SQL","weight":3,"builder_type":"mcq"},
      {"id":"sql-02","text":"Write a query that returns each customer_id and their order count, highest first.","type":"open","options":[],"benchmark_rubric":"GROUP BY customer_id, COUNT(*), ORDER BY count DESC. Mentions handling NULLs.","evaluated_competency":"SQL","weight":4,"builder_type":"open_ended"}
    ]'::jsonb
),
(
    'b1000000-0000-4000-8000-000000000002',
    'python-problem-solving',
    'Python Problem Solving',
    'Data structures, complexity, and debugging prompts.',
    'technical',
    25,
    11,
    '[
      {"id":"py-01","text":"What is the average-case time complexity of dict lookup in CPython?","type":"mcq","options":["O(1)","O(log n)","O(n)","O(n log n)"],"correct_answer":"O(1)","evaluated_competency":"Python","weight":3,"builder_type":"mcq"},
      {"id":"py-02","text":"A function mutates a default list argument across calls. Explain the bug and a safe fix.","type":"open","options":[],"benchmark_rubric":"Mutable default; use None sentinel and create a new list inside the function.","evaluated_competency":"Python","weight":4,"builder_type":"open_ended"}
    ]'::jsonb
),
(
    'b1000000-0000-4000-8000-000000000003',
    'data-analysis-block',
    'Data Analysis',
    'Metrics, leakage, and experiment-design prompts.',
    'technical',
    20,
    12,
    '[
      {"id":"da-01","text":"A conversion rate rose after a UI change shipped with a holiday campaign. What is the primary validity threat?","type":"mcq","options":["Selection bias","History / confounds","Instrumentation","Attrition"],"correct_answer":"History / confounds","evaluated_competency":"Experiment design","weight":4,"builder_type":"mcq"},
      {"id":"da-02","text":"How would you detect target leakage in a churn model trained on account snapshots?","type":"open","options":[],"benchmark_rubric":"Mentions post-outcome features, time-aware splits, and feature-as-of dates.","evaluated_competency":"ML hygiene","weight":5,"builder_type":"open_ended"}
    ]'::jsonb
)
on conflict (slug) do nothing;
