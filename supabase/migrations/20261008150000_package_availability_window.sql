-- Package availability window. Candidates cannot start work before open_time
-- or launch unstarted modules after close_time. Both nullable = unbounded, so
-- existing packages keep their current always-open behaviour.

alter table public.packages
    add column if not exists open_time timestamptz,
    add column if not exists close_time timestamptz;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'packages_window_order_check'
          and conrelid = 'public.packages'::regclass
    ) then
        alter table public.packages
            add constraint packages_window_order_check
            check (open_time is null or close_time is null or close_time > open_time);
    end if;
end;
$$;

comment on column public.packages.open_time is
    'Earliest instant candidates may start; null = open immediately. Entered in Sri Lanka time (GMT+5:30).';
comment on column public.packages.close_time is
    'Deadline after which unstarted modules cannot be launched; null = no deadline.';
comment on column public.packages.description is
    'Role Assessment Brief (formerly job description). Free text; feeds JD-fit scoring.';

-- p.* is expanded at view creation; recreate so the new columns are exposed.
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
