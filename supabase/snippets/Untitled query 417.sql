-- 1. Ensure our company and a sample client company exist
insert into public.corporates (name, slug)
values 
  ('Happy Mind', 'happy-mind'),
  ('Acme Corp', 'acme-corp')
on conflict (slug) do update set name = excluded.name;

-- 2. Provision Ops Admin (mapped to Happy Mind)
insert into public.hr_users (user_id, corporate_id, full_name, role)
values (
  (select id from auth.users where email = 'muhammed01n@gmail.com'),
  (select id from public.corporates where slug = 'happy-mind'),
  'Ops Admin',
  'admin'
)
on conflict (user_id) do update set role = 'admin';

-- 3. Provision Client HR User (mapped to Acme Corp)
insert into public.hr_users (user_id, corporate_id, full_name, role)
values (
  (select id from auth.users where email = 'muhamadnas44@gmail.com'),
  (select id from public.corporates where slug = 'acme-corp'),
  'HR Contact',
  'hr'
)
on conflict (user_id) do update set role = 'hr';