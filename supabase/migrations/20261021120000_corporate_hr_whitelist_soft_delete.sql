-- HR portal access whitelist + company soft delete.
-- allowed_hr_emails is an additional gate on top of hr_users membership:
-- backfill it from existing members (and the legacy single contact email)
-- so no current HR user loses access when the gate is switched on.
alter table public.corporates
    add column if not exists allowed_hr_emails text[] not null default '{}',
    add column if not exists is_active boolean not null default true;

update public.corporates c
set allowed_hr_emails = sub.emails
from (
    select
        corp.id,
        coalesce(
            array_agg(distinct lower(e.email)) filter (where e.email is not null),
            '{}'
        ) as emails
    from public.corporates corp
    left join (
        select h.corporate_id, u.email::text as email
        from public.hr_users h
        join auth.users u on u.id = h.user_id
        union
        select corp2.id, corp2.contact_email
        from public.corporates corp2
        where corp2.contact_email is not null and btrim(corp2.contact_email) <> ''
    ) e on e.corporate_id = corp.id
    group by corp.id
) sub
where sub.id = c.id
  and coalesce(cardinality(c.allowed_hr_emails), 0) = 0;
