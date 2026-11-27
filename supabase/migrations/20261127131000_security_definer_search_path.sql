-- P2-08: pin search_path = '' on gen_access_code() and custom_access_token_hook
-- and schema-qualify every non-pg_catalog reference, so no object in a
-- writable schema can shadow what these functions call.
--
-- pg_catalog is always searched implicitly, so built-ins (substr, ascii,
-- get_byte, jsonb_set, to_jsonb, ...) still resolve.
--
-- gen_random_bytes comes from pgcrypto, which lives in `extensions` on Supabase
-- but in `public` on vanilla Postgres (see 20260906162714). The schema is
-- resolved here and baked into the function body as a qualified name.
-- CREATE OR REPLACE keeps existing grants.

-- ---------------------------------------------------------------------------
-- gen_access_code()
-- ---------------------------------------------------------------------------
do $mig$
declare
    crypto_schema text;
begin
    select n.nspname
      into crypto_schema
      from pg_catalog.pg_proc p
      join pg_catalog.pg_namespace n on n.oid = p.pronamespace
     where p.proname = 'gen_random_bytes'
     order by (n.nspname = 'extensions') desc, (n.nspname = 'public') desc
     limit 1;

    if crypto_schema is null then
        raise exception 'P2-08: pgcrypto gen_random_bytes() not found; install pgcrypto first';
    end if;

    execute format($fn$
create or replace function public.gen_access_code()
returns text
language plpgsql
security definer
set search_path = ''
as $body$
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
            body := body || pg_catalog.substr(
                alphabet,
                1 + (pg_catalog.get_byte(%1$I.gen_random_bytes(1), 0) %% pg_catalog.length(alphabet)),
                1
            );
        end loop;

        checksum := 0;
        for i in 1..pg_catalog.length(body) loop
            checksum := checksum + pg_catalog.ascii(pg_catalog.substr(body, i, 1));
        end loop;
        check_char := pg_catalog.substr(alphabet, 1 + (checksum %% pg_catalog.length(alphabet)), 1);

        code := 'HM-' || body || '-' || check_char;

        select count(*) into existing from public.packages where access_code = code;
        exit when existing = 0;
    end loop;
    return code;
end;
$body$;
$fn$, crypto_schema);
end
$mig$;

revoke all on function public.gen_access_code() from public, anon;
grant execute on function public.gen_access_code() to authenticated;

-- ---------------------------------------------------------------------------
-- custom_access_token_hook(event jsonb)
-- Body identical to 20260914153000 apart from qualification + search_path.
-- ---------------------------------------------------------------------------
create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb
language plpgsql
stable
set search_path = ''
as $$
declare
    claims jsonb;
    corp_id uuid;
    corp_role text;
begin
    select h.corporate_id, h.role
      into corp_id, corp_role
      from public.hr_users h
     where h.user_id = (event ->> 'user_id')::uuid;

    claims := event -> 'claims';

    if pg_catalog.jsonb_typeof(claims -> 'app_metadata') is distinct from 'object' then
        claims := pg_catalog.jsonb_set(claims, '{app_metadata}', '{}'::jsonb);
    end if;

    if corp_id is not null then
        claims := pg_catalog.jsonb_set(
            claims, '{app_metadata, corporate_id}', pg_catalog.to_jsonb(corp_id::text)
        );
        claims := pg_catalog.jsonb_set(
            claims,
            '{app_metadata, corporate_role}',
            pg_catalog.to_jsonb(coalesce(corp_role, 'hr'))
        );
        claims := pg_catalog.jsonb_set(
            claims,
            '{app_metadata, role}',
            pg_catalog.to_jsonb(coalesce(corp_role, 'hr'))
        );
    end if;

    event := pg_catalog.jsonb_set(event, '{claims}', claims);
    return event;
end;
$$;

grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;
revoke execute on function public.custom_access_token_hook(jsonb) from authenticated, anon, public;
