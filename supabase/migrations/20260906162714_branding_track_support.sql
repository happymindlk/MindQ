-- Branding on corporates, public tracker secret on packages, support tickets.
-- HR can UPDATE own corporate branding. Support tickets are insertable by
-- service_role (FastAPI) and SELECT-only for authenticated HR of that tenant.
-- Public track uses FastAPI + service_role (no anon grants on track_secret).

alter table public.corporates
    add column if not exists logo_url text,
    add column if not exists primary_color text,
    add column if not exists contact_email text;

alter table public.packages
    add column if not exists track_secret text;

-- Backfill unique secrets for existing packages.
update public.packages
set track_secret = encode(gen_random_bytes(24), 'hex')
where track_secret is null;

alter table public.packages
    alter column track_secret set not null;

create unique index if not exists packages_track_secret_uidx
    on public.packages (track_secret);

-- Ensure create_package continues to mint a track_secret.
create or replace function public.create_package(
    p_title text,
    p_description text,
    p_tests jsonb
)
returns public.packages
language plpgsql
security invoker
set search_path = public, extensions
as $$
declare
    v_corp uuid := private.user_corporate_id();
    v_pkg public.packages;
    v_test jsonb;
    v_pos int := 0;
begin
    if v_corp is null then
        raise exception 'No corporate context in token' using errcode = '42501';
    end if;

    insert into public.packages (corporate_id, title, description, access_code, track_secret)
    values (
        v_corp,
        p_title,
        nullif(p_description, ''),
        public.gen_access_code(),
        encode(gen_random_bytes(24), 'hex')
    )
    returning * into v_pkg;

    for v_test in select * from jsonb_array_elements(coalesce(p_tests, '[]'::jsonb))
    loop
        insert into public.assessments
            (corporate_id, package_id, title, description, time_limit_minutes, position, questions)
        values (
            v_corp,
            v_pkg.id,
            coalesce(v_test ->> 'title', 'Untitled'),
            v_test ->> 'description',
            nullif(v_test ->> 'time_limit_minutes', '')::int,
            v_pos,
            coalesce(v_test -> 'questions', '[]'::jsonb)
        );
        v_pos := v_pos + 1;
    end loop;

    return v_pkg;
end;
$$;

create table if not exists public.support_tickets (
    id            uuid primary key default gen_random_uuid(),
    corporate_id  uuid references public.corporates(id) on delete set null,
    candidate_id  uuid references public.candidates(id) on delete set null,
    details       text not null,
    path          text,
    user_agent    text,
    created_at    timestamptz not null default now()
);

create index if not exists support_tickets_corporate_id_idx
    on public.support_tickets (corporate_id);
create index if not exists support_tickets_created_at_idx
    on public.support_tickets (created_at desc);

alter table public.support_tickets enable row level security;
grant select on public.support_tickets to authenticated;
grant all on public.support_tickets to service_role;

create policy "support_tickets_select_own" on public.support_tickets
    for select to authenticated
    using (
        corporate_id is not null
        and corporate_id = (select private.user_corporate_id())
    );

-- Recreate package_overview so track_secret is available to HR (not to anon).
drop view if exists public.package_overview;
create view public.package_overview
with (security_invoker = on) as
select
    p.*,
    (select count(*) from public.candidates c where c.package_id = p.id) as candidate_count
from public.packages p;

grant select on public.package_overview to authenticated, service_role;
