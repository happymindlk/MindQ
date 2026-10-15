-- ---------------------------------------------------------------------------
-- One-off staging repair. NOT a migration: lives outside supabase/migrations so
-- the CLI never applies it to production or a fresh database.
--
-- Staging (MindQ, djshmrkerssvpvcxqkqo) carries a pre-migration legacy schema
-- (packages.assessment_ids[], track_token, candidate_responses.test_id, enum
-- candidate_progress_status) while supabase_migrations.schema_migrations claims
-- every migration through 20261008150000 ran. `initial_schema` uses plain
-- CREATE TABLE, so `supabase db push` cannot run on top of the legacy tables.
--
-- This script drops the legacy public objects and clears the fabricated
-- history so `supabase db push` replays the full chain in order. It refuses to
-- run if any public table holds rows or the canonical schema is present.
-- auth.users and storage are untouched.
-- ---------------------------------------------------------------------------

begin;

do $$
declare
    v_table text;
    v_rows  bigint;
begin
    if to_regclass('public.hr_users') is not null
       or to_regnamespace('private') is not null then
        raise exception 'Canonical schema detected (public.hr_users / private); refusing to reset';
    end if;

    for v_table in
        select format('%I.%I', schemaname, tablename)
          from pg_tables
         where schemaname = 'public'
    loop
        execute format('select count(*) from %s', v_table) into v_rows;
        if v_rows > 0 then
            raise exception 'Table % holds % rows; refusing to drop data', v_table, v_rows;
        end if;
    end loop;
end;
$$;

drop view if exists public.package_overview;

drop table if exists
    public.candidate_responses,
    public.candidate_progress,
    public.candidates,
    public.packages,
    public.assessments,
    public.corporates
    cascade;

drop type if exists public.candidate_progress_status;

-- Every recorded version was marked applied without its DDL executing.
delete from supabase_migrations.schema_migrations
 where version <= '20261008150000';

commit;
