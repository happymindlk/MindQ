insert into public.corporates (name, slug)
values ('Happy Mind', 'happy-mind')
on conflict (slug) do update set name = excluded.name
returning id;