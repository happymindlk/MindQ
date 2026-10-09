-- Local/CI-only shim that emulates the Supabase runtime (auth schema, roles,
-- and helper functions) so migrations and RLS can be tested against a vanilla
-- Postgres WITHOUT the full Supabase stack (e.g. a GitHub Actions postgres
-- service). On a real Supabase instance these already exist; never apply this
-- to a real project.
create extension if not exists "pgcrypto";

do $$ begin
  if not exists (select from pg_roles where rolname = 'anon') then create role anon nologin noinherit; end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then create role authenticated nologin noinherit; end if;
  if not exists (select from pg_roles where rolname = 'service_role') then create role service_role nologin noinherit bypassrls; end if;
  if not exists (select from pg_roles where rolname = 'supabase_auth_admin') then create role supabase_auth_admin nologin noinherit; end if;
end $$;

create schema if not exists auth;

create table if not exists auth.users (
  id uuid primary key default gen_random_uuid(),
  email text
);

create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claims', true)::json ->> 'sub', '')::uuid;
$$;

create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb);
$$;

create or replace function auth.role() returns text language sql stable as $$
  select nullif(current_setting('request.jwt.claims', true)::json ->> 'role', '')::text;
$$;

grant usage on schema auth to anon, authenticated, service_role;
