-- ---------------------------------------------------------------------------
-- Private storage bucket for generated PDF reports.
-- Objects are stored under `{corporate_id}/{candidate_id}.pdf`. The FastAPI
-- service writes with the service_role key; HR users can read only their own
-- corporate's reports via the RLS policy below.
-- ---------------------------------------------------------------------------

insert into storage.buckets (id, name, public)
values ('reports', 'reports', false)
on conflict (id) do nothing;

-- HR can read report objects whose first path segment is their corporate_id.
create policy "HR can read own corporate reports"
    on storage.objects
    for select
    to authenticated
    using (
        bucket_id = 'reports'
        and (storage.foldername(name))[1] = (select private.user_corporate_id())::text
    );
