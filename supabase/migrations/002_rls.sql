-- AssessPulse — Row Level Security (Day 2)
-- Multi-tenant isolation: authenticated HR users (auth.uid()) may only access
-- rows that map to their corporate_id via public.corporate_users.
--
-- Candidate access-code flows and platform-admin operations use the FastAPI
-- service_role key (bypasses RLS). Do not expose service_role to clients.
--
-- Requires: 001_schema.sql applied first.

-- ---------------------------------------------------------------------------
-- Tenancy bridge: map Supabase Auth users → corporates
-- ---------------------------------------------------------------------------

CREATE TABLE public.corporate_users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    corporate_id    UUID NOT NULL REFERENCES public.corporates (id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'hr',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT corporate_users_user_corporate_unique UNIQUE (user_id, corporate_id)
);

CREATE INDEX idx_corporate_users_user_id ON public.corporate_users (user_id);
CREATE INDEX idx_corporate_users_corporate_id ON public.corporate_users (corporate_id);

-- Optional: scope tenant-owned assessments (NULL = platform-wide library readable by all HR)
ALTER TABLE public.assessments
    ADD COLUMN IF NOT EXISTS corporate_id UUID REFERENCES public.corporates (id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_assessments_corporate_id ON public.assessments (corporate_id);

-- ---------------------------------------------------------------------------
-- Helper functions (SECURITY DEFINER — read membership, not bypass RLS on data)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.current_corporate_id()
RETURNS UUID
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT cu.corporate_id
    FROM public.corporate_users AS cu
    WHERE cu.user_id = auth.uid()
    LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.package_belongs_to_current_corporate(p_package_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.packages AS p
        WHERE p.id = p_package_id
          AND p.corporate_id = public.current_corporate_id()
    );
$$;

CREATE OR REPLACE FUNCTION public.candidate_belongs_to_current_corporate(p_candidate_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.candidates AS c
        INNER JOIN public.packages AS p ON p.id = c.package_id
        WHERE c.id = p_candidate_id
          AND p.corporate_id = public.current_corporate_id()
    );
$$;

REVOKE ALL ON FUNCTION public.current_corporate_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.current_corporate_id() TO authenticated;

REVOKE ALL ON FUNCTION public.package_belongs_to_current_corporate(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.package_belongs_to_current_corporate(UUID) TO authenticated;

REVOKE ALL ON FUNCTION public.candidate_belongs_to_current_corporate(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.candidate_belongs_to_current_corporate(UUID) TO authenticated;

-- ---------------------------------------------------------------------------
-- Enable RLS
-- ---------------------------------------------------------------------------

ALTER TABLE public.corporates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.packages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidate_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidate_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.corporate_users ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- corporates
-- ---------------------------------------------------------------------------

CREATE POLICY corporates_select_hr
    ON public.corporates
    FOR SELECT
    TO authenticated
    USING (id = public.current_corporate_id());

CREATE POLICY corporates_insert_hr
    ON public.corporates
    FOR INSERT
    TO authenticated
    WITH CHECK (id = public.current_corporate_id());

CREATE POLICY corporates_update_hr
    ON public.corporates
    FOR UPDATE
    TO authenticated
    USING (id = public.current_corporate_id())
    WITH CHECK (id = public.current_corporate_id());

-- ---------------------------------------------------------------------------
-- assessments
-- Platform-wide rows (corporate_id IS NULL) are readable by any linked HR user.
-- Tenant-owned rows require matching corporate_id on read/write.
-- ---------------------------------------------------------------------------

CREATE POLICY assessments_select_hr
    ON public.assessments
    FOR SELECT
    TO authenticated
    USING (
        corporate_id IS NULL
        OR corporate_id = public.current_corporate_id()
    );

CREATE POLICY assessments_insert_hr
    ON public.assessments
    FOR INSERT
    TO authenticated
    WITH CHECK (corporate_id = public.current_corporate_id());

CREATE POLICY assessments_update_hr
    ON public.assessments
    FOR UPDATE
    TO authenticated
    USING (corporate_id = public.current_corporate_id())
    WITH CHECK (corporate_id = public.current_corporate_id());

-- ---------------------------------------------------------------------------
-- packages
-- ---------------------------------------------------------------------------

CREATE POLICY packages_select_hr
    ON public.packages
    FOR SELECT
    TO authenticated
    USING (corporate_id = public.current_corporate_id());

CREATE POLICY packages_insert_hr
    ON public.packages
    FOR INSERT
    TO authenticated
    WITH CHECK (corporate_id = public.current_corporate_id());

CREATE POLICY packages_update_hr
    ON public.packages
    FOR UPDATE
    TO authenticated
    USING (corporate_id = public.current_corporate_id())
    WITH CHECK (corporate_id = public.current_corporate_id());

-- ---------------------------------------------------------------------------
-- candidates  (tenancy via package → corporate_id)
-- ---------------------------------------------------------------------------

CREATE POLICY candidates_select_hr
    ON public.candidates
    FOR SELECT
    TO authenticated
    USING (public.package_belongs_to_current_corporate(package_id));

CREATE POLICY candidates_insert_hr
    ON public.candidates
    FOR INSERT
    TO authenticated
    WITH CHECK (public.package_belongs_to_current_corporate(package_id));

CREATE POLICY candidates_update_hr
    ON public.candidates
    FOR UPDATE
    TO authenticated
    USING (public.package_belongs_to_current_corporate(package_id))
    WITH CHECK (public.package_belongs_to_current_corporate(package_id));

-- ---------------------------------------------------------------------------
-- candidate_progress  (tenancy via candidate → package → corporate_id)
-- ---------------------------------------------------------------------------

CREATE POLICY candidate_progress_select_hr
    ON public.candidate_progress
    FOR SELECT
    TO authenticated
    USING (public.candidate_belongs_to_current_corporate(candidate_id));

CREATE POLICY candidate_progress_insert_hr
    ON public.candidate_progress
    FOR INSERT
    TO authenticated
    WITH CHECK (public.candidate_belongs_to_current_corporate(candidate_id));

CREATE POLICY candidate_progress_update_hr
    ON public.candidate_progress
    FOR UPDATE
    TO authenticated
    USING (public.candidate_belongs_to_current_corporate(candidate_id))
    WITH CHECK (public.candidate_belongs_to_current_corporate(candidate_id));

-- ---------------------------------------------------------------------------
-- candidate_responses  (tenancy via candidate → package → corporate_id)
-- ---------------------------------------------------------------------------

CREATE POLICY candidate_responses_select_hr
    ON public.candidate_responses
    FOR SELECT
    TO authenticated
    USING (public.candidate_belongs_to_current_corporate(candidate_id));

CREATE POLICY candidate_responses_insert_hr
    ON public.candidate_responses
    FOR INSERT
    TO authenticated
    WITH CHECK (public.candidate_belongs_to_current_corporate(candidate_id));

CREATE POLICY candidate_responses_update_hr
    ON public.candidate_responses
    FOR UPDATE
    TO authenticated
    USING (public.candidate_belongs_to_current_corporate(candidate_id))
    WITH CHECK (public.candidate_belongs_to_current_corporate(candidate_id));

-- ---------------------------------------------------------------------------
-- corporate_users — HR can read their own membership row(s).
-- Inserts/updates to corporate_users are performed via service_role during
-- onboarding (linking auth.users → corporates). No authenticated INSERT/UPDATE
-- policies — avoids chicken-and-egg before current_corporate_id() exists.
-- ---------------------------------------------------------------------------

CREATE POLICY corporate_users_select_own
    ON public.corporate_users
    FOR SELECT
    TO authenticated
    USING (user_id = auth.uid());
