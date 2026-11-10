-- Candidate runner lookup indexes (adapted to real schema).
-- Note: Supabase migrations run inside a transaction, so CONCURRENTLY is omitted.
-- For online builds on a large live DB outside migrate, re-run with CONCURRENTLY.

-- Candidate login OTP / invite lookup uses lower(access_code).
CREATE INDEX IF NOT EXISTS idx_candidates_lower_access_code
  ON public.candidates (lower(access_code));

-- Bulk answer fetch on GET /test and submit.
-- Left-prefix of UNIQUE (candidate_id, assessment_id, question_id) already helps;
-- this explicit 2-col index keeps planner choice stable for "all answers for attempt".
CREATE INDEX IF NOT EXISTS idx_candidate_responses_cand_assessment
  ON public.candidate_responses (candidate_id, assessment_id);

-- VERIFY ONLY (do not duplicate):
-- candidate_progress already has UNIQUE (candidate_id, assessment_id)
-- which is a btree index covering the hot lookup in _get_progress.
