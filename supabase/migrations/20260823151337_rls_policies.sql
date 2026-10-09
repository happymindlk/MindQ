-- ---------------------------------------------------------------------------
-- Row Level Security: multi-tenant isolation by corporate_id.
-- ---------------------------------------------------------------------------
-- These policies enforce tenancy on the supabase-js (HR) path. The FastAPI
-- service connects with the service_role key, which BYPASSES RLS by design and
-- enforces corporate_id in application code instead.
-- ---------------------------------------------------------------------------

-- Tenant resolver. Reads corporate_id from the JWT app_metadata claim (populated
-- by the custom access token hook). app_metadata is not user-editable => safe.
create schema if not exists private;

create or replace function private.user_corporate_id()
returns uuid
language sql
stable
set search_path = ''
as $$
  select nullif(
    ((select auth.jwt()) -> 'app_metadata' ->> 'corporate_id'),
    ''
  )::uuid;
$$;

revoke all on function private.user_corporate_id() from public, anon;
grant usage on schema private to authenticated, service_role;
grant execute on function private.user_corporate_id() to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- corporates (tenant root: keyed by id)
-- ---------------------------------------------------------------------------
alter table public.corporates enable row level security;
grant select, insert, update on public.corporates to authenticated;
grant all on public.corporates to service_role;

create policy "corporates_select_own" on public.corporates
    for select to authenticated
    using (id = (select private.user_corporate_id()));

create policy "corporates_insert_own" on public.corporates
    for insert to authenticated
    with check (id = (select private.user_corporate_id()));

create policy "corporates_update_own" on public.corporates
    for update to authenticated
    using (id = (select private.user_corporate_id()))
    with check (id = (select private.user_corporate_id()));

-- ---------------------------------------------------------------------------
-- hr_users (a user can read their own membership; auth admin policy added in
-- the auth-hook migration)
-- ---------------------------------------------------------------------------
alter table public.hr_users enable row level security;
grant select on public.hr_users to authenticated;
grant all on public.hr_users to service_role;

create policy "hr_users_select_self" on public.hr_users
    for select to authenticated
    using (user_id = (select auth.uid()));

-- ---------------------------------------------------------------------------
-- Tenant-scoped business tables. Uniform policy: the row's corporate_id must
-- equal the caller's corporate_id. INSERT/UPDATE use WITH CHECK to block
-- cross-tenant writes; UPDATE also needs USING (and SELECT) to see the row.
-- ---------------------------------------------------------------------------

-- packages
alter table public.packages enable row level security;
grant select, insert, update on public.packages to authenticated;
grant all on public.packages to service_role;

create policy "packages_select_own" on public.packages
    for select to authenticated
    using (corporate_id = (select private.user_corporate_id()));
create policy "packages_insert_own" on public.packages
    for insert to authenticated
    with check (corporate_id = (select private.user_corporate_id()));
create policy "packages_update_own" on public.packages
    for update to authenticated
    using (corporate_id = (select private.user_corporate_id()))
    with check (corporate_id = (select private.user_corporate_id()));

-- assessments
alter table public.assessments enable row level security;
grant select, insert, update on public.assessments to authenticated;
grant all on public.assessments to service_role;

create policy "assessments_select_own" on public.assessments
    for select to authenticated
    using (corporate_id = (select private.user_corporate_id()));
create policy "assessments_insert_own" on public.assessments
    for insert to authenticated
    with check (corporate_id = (select private.user_corporate_id()));
create policy "assessments_update_own" on public.assessments
    for update to authenticated
    using (corporate_id = (select private.user_corporate_id()))
    with check (corporate_id = (select private.user_corporate_id()));

-- candidates
alter table public.candidates enable row level security;
grant select, insert, update on public.candidates to authenticated;
grant all on public.candidates to service_role;

create policy "candidates_select_own" on public.candidates
    for select to authenticated
    using (corporate_id = (select private.user_corporate_id()));
create policy "candidates_insert_own" on public.candidates
    for insert to authenticated
    with check (corporate_id = (select private.user_corporate_id()));
create policy "candidates_update_own" on public.candidates
    for update to authenticated
    using (corporate_id = (select private.user_corporate_id()))
    with check (corporate_id = (select private.user_corporate_id()));

-- candidate_progress
alter table public.candidate_progress enable row level security;
grant select, insert, update on public.candidate_progress to authenticated;
grant all on public.candidate_progress to service_role;

create policy "candidate_progress_select_own" on public.candidate_progress
    for select to authenticated
    using (corporate_id = (select private.user_corporate_id()));
create policy "candidate_progress_insert_own" on public.candidate_progress
    for insert to authenticated
    with check (corporate_id = (select private.user_corporate_id()));
create policy "candidate_progress_update_own" on public.candidate_progress
    for update to authenticated
    using (corporate_id = (select private.user_corporate_id()))
    with check (corporate_id = (select private.user_corporate_id()));

-- candidate_responses
alter table public.candidate_responses enable row level security;
grant select, insert, update on public.candidate_responses to authenticated;
grant all on public.candidate_responses to service_role;

create policy "candidate_responses_select_own" on public.candidate_responses
    for select to authenticated
    using (corporate_id = (select private.user_corporate_id()));
create policy "candidate_responses_insert_own" on public.candidate_responses
    for insert to authenticated
    with check (corporate_id = (select private.user_corporate_id()));
create policy "candidate_responses_update_own" on public.candidate_responses
    for update to authenticated
    using (corporate_id = (select private.user_corporate_id()))
    with check (corporate_id = (select private.user_corporate_id()));
