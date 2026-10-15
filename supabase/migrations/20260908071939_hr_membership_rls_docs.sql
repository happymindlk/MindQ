-- ---------------------------------------------------------------------------
-- HR membership read path for gated beta onboarding.
-- Source of truth: public.hr_users (there is no public.profiles table).
-- ---------------------------------------------------------------------------
-- Authenticated users must be able to SELECT their own hr_users row even when
-- JWT app_metadata.corporate_id is still missing (pre-refresh after SQL
-- provisioning). Policy "hr_users_select_self" already does:
--   using (user_id = auth.uid())
-- Recreate it here so hosted / drifted environments stay consistent.
--
-- Corporates remain gated by private.user_corporate_id() (JWT claim). After
-- provisioning, the client must call supabase.auth.refreshSession() so the
-- custom access token hook injects corporate_id into the JWT.

drop policy if exists "hr_users_select_self" on public.hr_users;
create policy "hr_users_select_self" on public.hr_users
    for select to authenticated
    using (user_id = (select auth.uid()));

grant select on public.hr_users to authenticated;

-- Allow reading the corporate row when the caller is a member via hr_users,
-- not only when the JWT already carries corporate_id. Avoids a chicken-and-egg
-- where getCorporate() returns null until the next token mint.
drop policy if exists "corporates_select_own" on public.corporates;
drop policy if exists "corporates_select_member" on public.corporates;

create policy "corporates_select_member" on public.corporates
    for select to authenticated
    using (
        id = (select private.user_corporate_id())
        or id in (
            select hu.corporate_id
              from public.hr_users hu
             where hu.user_id = (select auth.uid())
        )
    );

-- Keep insert/update policies JWT-scoped (only provisioned tenants mutate).
-- (Existing corporates_insert_own / corporates_update_own unchanged.)
