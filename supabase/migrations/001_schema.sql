-- AssessPulse / Happy Mind — core multi-tenant schema
-- Six relational tables only. RLS policies are intentionally omitted (see 002_rls.sql).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------

CREATE TYPE candidate_progress_status AS ENUM (
    'NOT_STARTED',
    'IN_PROGRESS',
    'COMPLETED'
);

-- ---------------------------------------------------------------------------
-- corporates — B2B tenant umbrella (branding stored as URL / color strings)
-- ---------------------------------------------------------------------------

CREATE TABLE corporates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL,
    logo_url        TEXT,
    primary_color   TEXT,
    contact_name    TEXT,
    contact_email   TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT corporates_slug_unique UNIQUE (slug),
    CONSTRAINT corporates_name_nonempty CHECK (length(trim(name)) > 0),
    CONSTRAINT corporates_slug_nonempty CHECK (length(trim(slug)) > 0)
);

CREATE INDEX idx_corporates_slug ON corporates (slug);

-- ---------------------------------------------------------------------------
-- assessments — reusable question-bank modules (questions as JSONB)
-- Expected question shape (enforced in application layer):
--   [{ "id", "text", "type": "likert"|"mcq"|"open", "options"?: [...], ... }]
-- ---------------------------------------------------------------------------

CREATE TABLE assessments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    description     TEXT,
    assessment_type TEXT NOT NULL DEFAULT 'psychometric',
    questions       JSONB NOT NULL DEFAULT '[]'::jsonb,
    time_limit_minutes INTEGER,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT assessments_title_nonempty CHECK (length(trim(title)) > 0),
    CONSTRAINT assessments_questions_is_array CHECK (jsonb_typeof(questions) = 'array')
);

CREATE INDEX idx_assessments_is_active ON assessments (is_active);
CREATE INDEX idx_assessments_type ON assessments (assessment_type);

-- ---------------------------------------------------------------------------
-- packages — corporate test config + JD + access code + HR track token
-- assessment_ids: ordered list of library assessment UUIDs (max 6)
-- ---------------------------------------------------------------------------

CREATE TABLE packages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corporate_id    UUID NOT NULL REFERENCES corporates (id) ON DELETE RESTRICT,
    title           TEXT NOT NULL,
    description     TEXT,
    job_description TEXT NOT NULL DEFAULT '',
    assessment_ids  UUID[] NOT NULL DEFAULT '{}',
    access_code     TEXT NOT NULL,
    track_token     UUID NOT NULL DEFAULT gen_random_uuid(),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT packages_title_nonempty CHECK (length(trim(title)) > 0),
    CONSTRAINT packages_access_code_unique UNIQUE (access_code),
    CONSTRAINT packages_track_token_unique UNIQUE (track_token),
    CONSTRAINT packages_max_six_assessments CHECK (cardinality(assessment_ids) <= 6)
);

CREATE INDEX idx_packages_corporate_id ON packages (corporate_id);
CREATE INDEX idx_packages_access_code ON packages (access_code);
CREATE INDEX idx_packages_track_token ON packages (track_token);
CREATE INDEX idx_packages_is_active ON packages (is_active);

-- ---------------------------------------------------------------------------
-- candidates — participant sessions (email = system key; full_name = HR fallback)
-- ---------------------------------------------------------------------------

CREATE TABLE candidates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    package_id      UUID NOT NULL REFERENCES packages (id) ON DELETE CASCADE,
    full_name       TEXT NOT NULL,
    email           TEXT NOT NULL,
    due_date        TIMESTAMPTZ,
    reminder_sent_at TIMESTAMPTZ,
    logged_in_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT candidates_full_name_nonempty CHECK (length(trim(full_name)) > 0),
    CONSTRAINT candidates_email_nonempty CHECK (length(trim(email)) > 0),
    -- Email is the primary unique key within a package (PDF dual-identity model)
    CONSTRAINT candidates_package_email_unique UNIQUE (package_id, email)
);

CREATE INDEX idx_candidates_package_id ON candidates (package_id);
CREATE INDEX idx_candidates_email ON candidates (email);
CREATE INDEX idx_candidates_due_date ON candidates (due_date)
    WHERE due_date IS NOT NULL AND reminder_sent_at IS NULL;

-- ---------------------------------------------------------------------------
-- candidate_progress — per-assessment status + AI evaluation payload
-- ---------------------------------------------------------------------------

CREATE TABLE candidate_progress (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id    UUID NOT NULL REFERENCES candidates (id) ON DELETE CASCADE,
    assessment_id   UUID NOT NULL REFERENCES assessments (id) ON DELETE RESTRICT,
    status          candidate_progress_status NOT NULL DEFAULT 'NOT_STARTED',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    -- Trait scores, strengths, cautions, follow-ups (Gemini structured JSON)
    ai_evaluation   JSONB NOT NULL DEFAULT '{}'::jsonb,
    trait_scores    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT candidate_progress_candidate_assessment_unique
        UNIQUE (candidate_id, assessment_id),
    CONSTRAINT candidate_progress_ai_evaluation_is_object
        CHECK (jsonb_typeof(ai_evaluation) = 'object'),
    CONSTRAINT candidate_progress_trait_scores_is_object
        CHECK (jsonb_typeof(trait_scores) = 'object')
);

CREATE INDEX idx_candidate_progress_candidate_id ON candidate_progress (candidate_id);
CREATE INDEX idx_candidate_progress_assessment_id ON candidate_progress (assessment_id);
CREATE INDEX idx_candidate_progress_status ON candidate_progress (status);

-- ---------------------------------------------------------------------------
-- candidate_responses — incremental upserts (UNIQUE candidate + test + question)
-- ---------------------------------------------------------------------------

CREATE TABLE candidate_responses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id    UUID NOT NULL REFERENCES candidates (id) ON DELETE CASCADE,
    -- test_id aligns with an assessment module id within the package
    test_id         TEXT NOT NULL,
    question_id     TEXT NOT NULL,
    response        JSONB NOT NULL DEFAULT '{}'::jsonb,
    saved_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT candidate_responses_upsert_unique
        UNIQUE (candidate_id, test_id, question_id)
);

CREATE INDEX idx_candidate_responses_candidate_id ON candidate_responses (candidate_id);
CREATE INDEX idx_candidate_responses_candidate_test
    ON candidate_responses (candidate_id, test_id);
