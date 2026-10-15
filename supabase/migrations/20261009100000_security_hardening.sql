-- ---------------------------------------------------------------------------
-- Pre-launch security hardening.
--
-- Threat: a non-ops HR user can obtain a valid Supabase access token (the
-- client-portal OTP exchange mints one) and call PostgREST directly, bypassing
-- every FastAPI filter. The client portal itself reads exclusively through
-- FastAPI with a backend-minted JWT, and the supabase-js admin portal is
-- ops-only, so non-ops HR needs no direct access to exam content or raw results.
-- ---------------------------------------------------------------------------

-- 1. Candidates: HR could INSERT ghost candidates or UPDATE a candidate's email
--    to their own inbox, then pass the email-OTP login and sit the test for them.
drop policy if exists "candidates_insert_own" on public.candidates;
drop policy if exists "candidates_update_own" on public.candidates;
revoke insert, update, delete on public.candidates from authenticated;
grant select on public.candidates to authenticated;

-- 2. Assessments: technical snapshots carry correct_answer / accepted_answers /
--    option_weights in questions JSONB. HR must never read keys it could pass
--    to a favoured candidate.
drop policy if exists "assessments_select_ops_or_technical" on public.assessments;
drop policy if exists "assessments_select_own_or_ops" on public.assessments;
drop policy if exists "assessments_select_ops" on public.assessments;
create policy "assessments_select_ops" on public.assessments
    for select to authenticated
    using ((select private.user_is_ops()));

-- 3. Custom technical questions: correct_answer_or_rubric is an answer key.
drop policy if exists "custom_technical_questions_select_tenant" on public.custom_technical_questions;
drop policy if exists "custom_technical_questions_select_ops" on public.custom_technical_questions;
create policy "custom_technical_questions_select_ops" on public.custom_technical_questions
    for select to authenticated
    using ((select private.user_is_ops()));

-- 4. Raw responses and per-module progress (facet_scores, derived_profile,
--    psychometric scores) are ops-only. HR sees curated results via FastAPI.
drop policy if exists "candidate_responses_select_ops_or_technical" on public.candidate_responses;
drop policy if exists "candidate_responses_select_own_or_ops" on public.candidate_responses;
drop policy if exists "candidate_responses_select_ops" on public.candidate_responses;
create policy "candidate_responses_select_ops" on public.candidate_responses
    for select to authenticated
    using ((select private.user_is_ops()));

drop policy if exists "candidate_progress_select_own_or_ops" on public.candidate_progress;
drop policy if exists "candidate_progress_select_ops" on public.candidate_progress;
create policy "candidate_progress_select_ops" on public.candidate_progress
    for select to authenticated
    using ((select private.user_is_ops()));

-- Re-assert: exam state and AI evaluations are written only by service_role.
revoke insert, update, delete on public.candidate_progress from authenticated;
revoke insert, update, delete on public.candidate_responses from authenticated;
revoke insert, update, delete on public.candidate_evaluations from authenticated;
revoke insert, update, delete on public.custom_technical_questions from authenticated;

-- 5. Corporates: HR could rewrite logo_url (pointing PDF rendering at internal
--    hosts) or rename the tenant. Edits are ops-only; HR keeps read access.
drop policy if exists "corporates_insert_own" on public.corporates;
drop policy if exists "corporates_update_own" on public.corporates;
drop policy if exists "corporates_insert_ops" on public.corporates;
drop policy if exists "corporates_update_ops" on public.corporates;
create policy "corporates_insert_ops" on public.corporates
    for insert to authenticated
    with check ((select private.user_is_ops()));
create policy "corporates_update_ops" on public.corporates
    for update to authenticated
    using ((select private.user_is_ops()))
    with check ((select private.user_is_ops()));

-- 6. Public logo bucket: only raster images, bounded size (no SVG/HTML payloads).
--    Reports bucket stays private; re-assert in case of dashboard drift.
--    Skipped on vanilla Postgres (CI RLS job), which has no storage schema.
do $$
begin
    if exists (
        select 1
        from pg_catalog.pg_namespace n
        join pg_catalog.pg_class c on c.relnamespace = n.oid
        where n.nspname = 'storage' and c.relname = 'buckets'
    ) then
        update storage.buckets
           set allowed_mime_types = array['image/png', 'image/jpeg', 'image/webp'],
               file_size_limit = 2097152
         where id = 'corporate-logos';

        update storage.buckets set public = false where id = 'reports';
    end if;
end
$$;

-- 7. Database-level answer lock. Even if an application bug skips the
--    COMPLETED check, a candidate's answer cannot change after submission.
--    Grading writes (ai_score, feedback, …) still succeed because only the
--    answer value is compared.
create or replace function private.response_answer(r jsonb)
returns jsonb
language sql
immutable
set search_path = ''
as $$
    select case
        when r is null then null
        when jsonb_typeof(r) <> 'object' then r
        else coalesce(r -> 'answer', r -> 'value', r -> 'selected')
    end;
$$;

create or replace function private.lock_completed_answers()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if exists (
        select 1
          from public.candidate_progress p
         where p.candidate_id = new.candidate_id
           and p.assessment_id = new.assessment_id
           and p.status = 'COMPLETED'
    ) then
        if tg_op = 'INSERT' then
            raise exception 'Assessment already completed; candidate answers are locked'
                using errcode = 'check_violation';
        end if;
        if private.response_answer(old.response) is distinct from private.response_answer(new.response)
           or old.question_id is distinct from new.question_id then
            raise exception 'Assessment already completed; candidate answers are locked'
                using errcode = 'check_violation';
        end if;
    end if;
    return new;
end;
$$;

revoke all on function private.lock_completed_answers() from public, anon, authenticated;
revoke all on function private.response_answer(jsonb) from public, anon;

drop trigger if exists candidate_responses_lock_completed on public.candidate_responses;
create trigger candidate_responses_lock_completed
    before insert or update on public.candidate_responses
    for each row execute function private.lock_completed_answers();

-- 8. Fail the migration if any public table is missing RLS.
do $$
declare
    missing text;
begin
    select string_agg(c.relname, ', ')
      into missing
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public'
       and c.relkind in ('r', 'p')
       and not c.relrowsecurity;
    if missing is not null then
        raise exception 'RLS is disabled on public tables: %', missing;
    end if;
end;
$$;
