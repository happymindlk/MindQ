-- ---------------------------------------------------------------------------
-- Admin surface for the supabase-js (HR) path:
--   * secure server-side access-code generation
--   * a transactional create_package RPC (RLS-respecting)
--   * tenant-scoped read views for the dashboard and candidate tracker
-- ---------------------------------------------------------------------------

-- Crypto-random, collision-checked access code (HM-XXXXXX-C).
create or replace function public.gen_access_code()
returns text
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
    alphabet text := 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    body text;
    code text;
    check_char text;
    i int;
    checksum int;
    existing int;
begin
    loop
        body := '';
        for i in 1..6 loop
            body := body || substr(alphabet, 1 + (get_byte(gen_random_bytes(1), 0) % length(alphabet)), 1);
        end loop;

        checksum := 0;
        for i in 1..length(body) loop
            checksum := checksum + ascii(substr(body, i, 1));
        end loop;
        check_char := substr(alphabet, 1 + (checksum % length(alphabet)), 1);

        code := 'HM-' || body || '-' || check_char;

        select count(*) into existing from public.packages where access_code = code;
        exit when existing = 0;
    end loop;
    return code;
end;
$$;

revoke all on function public.gen_access_code() from public, anon;
grant execute on function public.gen_access_code() to authenticated;

-- Transactional package creation. security invoker => RLS applies; corporate_id
-- is taken from the caller's JWT so a tenant can only create its own data.
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

    insert into public.packages (corporate_id, title, description, access_code)
    values (v_corp, p_title, nullif(p_description, ''), public.gen_access_code())
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

grant execute on function public.create_package(text, text, jsonb) to authenticated;

-- ---------------------------------------------------------------------------
-- Read views (security_invoker => underlying-table RLS applies, so each view
-- is automatically tenant-scoped).
-- ---------------------------------------------------------------------------
create or replace view public.package_overview
with (security_invoker = on) as
select
    p.*,
    (select count(*) from public.candidates c where c.package_id = p.id) as candidate_count
from public.packages p;

create or replace view public.candidate_overview
with (security_invoker = on) as
select
    c.id,
    c.corporate_id,
    c.package_id,
    c.full_name,
    c.email,
    c.access_code,
    c.logged_in_at,
    c.created_at,
    pk.title as package_title,
    (select count(*) from public.assessments a where a.package_id = c.package_id) as total_assessments,
    (select count(*) from public.candidate_progress p
        where p.candidate_id = c.id and p.status = 'COMPLETED') as completed_assessments,
    (select round(avg(p.score), 1) from public.candidate_progress p
        where p.candidate_id = c.id and p.score is not null) as avg_score
from public.candidates c
join public.packages pk on pk.id = c.package_id;

grant select on public.package_overview to authenticated, service_role;
grant select on public.candidate_overview to authenticated, service_role;
