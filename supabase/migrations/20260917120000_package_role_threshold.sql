-- Package builder metadata: target role and passing threshold for drafts.
alter table public.packages
    add column if not exists target_role text,
    add column if not exists passing_threshold numeric(5, 2);

-- Recreate overview so p.* includes the new columns.
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
