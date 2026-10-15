-- Corporate white-label: contact phone + public logo storage bucket.

alter table public.corporates
  add column if not exists contact_phone text;

insert into storage.buckets (id, name, public)
values ('corporate-logos', 'corporate-logos', true)
on conflict (id) do nothing;

-- Path convention: `{corporate_id}/{filename}`.
create policy "HR can read corporate logos"
  on storage.objects
  for select
  to authenticated, anon
  using (bucket_id = 'corporate-logos');

create policy "HR can upload own corporate logos"
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'corporate-logos'
    and (storage.foldername(name))[1] = (select private.user_corporate_id())::text
  );

create policy "HR can update own corporate logos"
  on storage.objects
  for update
  to authenticated
  using (
    bucket_id = 'corporate-logos'
    and (storage.foldername(name))[1] = (select private.user_corporate_id())::text
  )
  with check (
    bucket_id = 'corporate-logos'
    and (storage.foldername(name))[1] = (select private.user_corporate_id())::text
  );

create policy "HR can delete own corporate logos"
  on storage.objects
  for delete
  to authenticated
  using (
    bucket_id = 'corporate-logos'
    and (storage.foldername(name))[1] = (select private.user_corporate_id())::text
  );
