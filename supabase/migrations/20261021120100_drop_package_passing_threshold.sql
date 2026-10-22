-- passing_threshold was write-only (never read by scoring/reporting).
-- The Package Builder threshold input is removed; drop the column.
-- Recreate package_overview without it (the view selects p.*).
drop view if exists public.package_overview;

alter table public.packages
    drop column if exists passing_threshold;

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
