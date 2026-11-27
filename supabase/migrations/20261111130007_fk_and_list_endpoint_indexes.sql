-- Missing FK leading indexes + hot-path composites for ops list endpoints.
-- Supabase migrations run inside a transaction, so CONCURRENTLY is omitted.
-- For online builds on a large live DB outside migrate, re-run with CONCURRENTLY.

-- ---------------------------------------------------------------------------
-- Foreign keys that lacked a leading btree index
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS assessments_global_module_id_idx
  ON public.assessments (global_module_id);

CREATE INDEX IF NOT EXISTS candidate_evaluations_package_id_idx
  ON public.candidate_evaluations (package_id);

CREATE INDEX IF NOT EXISTS custom_technical_questions_corporate_id_idx
  ON public.custom_technical_questions (corporate_id);

CREATE INDEX IF NOT EXISTS global_modules_parent_module_id_idx
  ON public.global_modules (parent_module_id);

CREATE INDEX IF NOT EXISTS support_tickets_candidate_id_idx
  ON public.support_tickets (candidate_id);

-- ---------------------------------------------------------------------------
-- Composites for GET /packages and GET /packages/corporates
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS packages_corporate_created_idx
  ON public.packages (corporate_id, created_at DESC);

CREATE INDEX IF NOT EXISTS packages_corporate_active_status_idx
  ON public.packages (corporate_id)
  WHERE status = 'draft' OR is_active IS TRUE;

CREATE INDEX IF NOT EXISTS candidate_progress_candidate_status_idx
  ON public.candidate_progress (candidate_id, status);

CREATE INDEX IF NOT EXISTS corporates_active_name_idx
  ON public.corporates (is_active, name);
