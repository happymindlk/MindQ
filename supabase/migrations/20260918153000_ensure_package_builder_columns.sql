-- Ensure package builder + draft override columns exist on databases
-- restored from older backups (supabase start from volume without migration up).
-- Safe to re-run: all statements use IF NOT EXISTS.

alter table public.packages
    add column if not exists target_role text,
    add column if not exists passing_threshold numeric(5, 2);

alter table public.packages
    add column if not exists status text not null default 'draft';

alter table public.packages
    add column if not exists review_token text;

alter table public.packages
    add column if not exists published_at timestamptz;

alter table public.packages
    add column if not exists client_approved boolean not null default false,
    add column if not exists reviewed_at timestamptz;

alter table public.package_modules
    add column if not exists questions jsonb;

comment on column public.package_modules.questions is
    'Optional draft override of global_modules.questions for this package cart row.';

create unique index if not exists packages_review_token_uidx
    on public.packages (review_token)
    where review_token is not null;

-- Refresh package_overview so p.* includes new columns.
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
