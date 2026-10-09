-- FastAPI (service_role) is the only writer of exam state: answers and scores.
-- HR clients (authenticated / supabase-js) are SELECT-only on these tables so a
-- browser session cannot rewrite candidate_progress.score or responses.
-- Privilege checks run before RLS; dropping write policies is defense in depth
-- if GRANT is ever re-added.

drop policy if exists "candidate_progress_insert_own" on public.candidate_progress;
drop policy if exists "candidate_progress_update_own" on public.candidate_progress;
drop policy if exists "candidate_responses_insert_own" on public.candidate_responses;
drop policy if exists "candidate_responses_update_own" on public.candidate_responses;

revoke insert, update on public.candidate_progress from authenticated;
revoke insert, update on public.candidate_responses from authenticated;

grant select on public.candidate_progress to authenticated;
grant select on public.candidate_responses to authenticated;
