-- ---------------------------------------------------------------------------
-- Custom Access Token hook: inject the HR user's corporate_id (and role) into
-- the JWT app_metadata so RLS policies can read it via auth.jwt().
-- Source of truth is public.hr_users. app_metadata is NOT user-editable, so it
-- is safe for authorization (unlike user_metadata).
-- ---------------------------------------------------------------------------

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

    -- Ensure app_metadata exists as an object.
    if jsonb_typeof(claims -> 'app_metadata') is distinct from 'object' then
        claims := jsonb_set(claims, '{app_metadata}', '{}'::jsonb);
    end if;

    if corp_id is not null then
        claims := jsonb_set(claims, '{app_metadata, corporate_id}', to_jsonb(corp_id::text));
        claims := jsonb_set(claims, '{app_metadata, corporate_role}', to_jsonb(coalesce(corp_role, 'hr')));
    end if;

    event := jsonb_set(event, '{claims}', claims);
    return event;
end;
$$;

-- The Auth server calls the hook as the supabase_auth_admin role.
grant usage on schema public to supabase_auth_admin;

grant execute
    on function public.custom_access_token_hook
    to supabase_auth_admin;

revoke execute
    on function public.custom_access_token_hook
    from authenticated, anon, public;

grant select
    on table public.hr_users
    to supabase_auth_admin;

-- Allow the Auth admin to read hr_users even once RLS is enabled (next migration).
create policy "Auth admin can read hr_users"
    on public.hr_users
    as permissive
    for select
    to supabase_auth_admin
    using (true);
