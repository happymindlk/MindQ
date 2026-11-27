-- P2-07: schema index & constraint cleanup.
--
--   (a) Active-email uniqueness becomes case-insensitive:
--       UNIQUE (package_id, lower(email)) WHERE deleted_at IS NULL.
--       Every lookup already uses lower(email), so mixed-case duplicates made
--       `.first()` pick an arbitrary row.
--   (b) Index lower(email) for the support lookup that has no package filter.
--   (c) Index the candidate_session_logs.assessment_id FK (ON DELETE SET NULL
--       otherwise scans the log table when an assessment is deleted).
--   (d) Drop the duplicate review_token unique index (only when the column
--       constraint already enforces uniqueness).
--   (e) Pin candidate_progress.scoring_version to varchar(64) (the SQLAlchemy
--       model type); it was text or varchar(64) depending on migration order.
--   (f) Drop the (candidate_id, assessment_id) responses index, which is a
--       redundant left prefix of UNIQUE (candidate_id, assessment_id, question_id).
--
-- Supabase migrations run in a transaction, so CONCURRENTLY is omitted.
-- Idempotent: safe to re-run.

-- ---------------------------------------------------------------------------
-- (a) Case-insensitive active-email uniqueness.
-- Abort with a clear message if active mixed-case duplicates already exist;
-- they must be resolved (soft-delete one of each pair) before this can apply.
-- ---------------------------------------------------------------------------
do $$
declare
    dup_count int;
begin
    select count(*) into dup_count
      from (
        select package_id, lower(email)
          from public.candidates
         where deleted_at is null
         group by package_id, lower(email)
        having count(*) > 1
      ) d;

    if dup_count > 0 then
        raise exception
            'P2-07: % (package_id, lower(email)) group(s) have more than one active candidate. '
            'Resolve with: select package_id, lower(email), array_agg(id order by created_at) '
            'from public.candidates where deleted_at is null '
            'group by 1, 2 having count(*) > 1;', dup_count;
    end if;
end $$;

create unique index if not exists uq_candidates_package_lower_email_active
    on public.candidates (package_id, lower(email))
    where deleted_at is null;

-- Strictly weaker than the index above.
drop index if exists public.uq_candidates_package_email_active;

-- ---------------------------------------------------------------------------
-- (b) lower(email) lookup without a package filter (support search).
-- ---------------------------------------------------------------------------
create index if not exists idx_candidates_lower_email
    on public.candidates (lower(email));

-- ---------------------------------------------------------------------------
-- (c) FK index on candidate_session_logs.assessment_id.
-- ---------------------------------------------------------------------------
create index if not exists candidate_session_logs_assessment_id_idx
    on public.candidate_session_logs (assessment_id);

-- ---------------------------------------------------------------------------
-- (d) review_token: keep a single unique index.
-- 20260914153000 created both a column UNIQUE constraint and a partial unique
-- index; 20260918153000 may have created only the partial index. Drop the
-- partial index only when a full unique constraint on review_token exists.
-- ---------------------------------------------------------------------------
do $$
begin
    if exists (
        select 1
          from pg_catalog.pg_constraint c
          join pg_catalog.pg_attribute a
            on a.attrelid = c.conrelid and a.attnum = any (c.conkey)
         where c.conrelid = 'public.packages'::regclass
           and c.contype = 'u'
           and array_length(c.conkey, 1) = 1
           and a.attname = 'review_token'
    ) then
        drop index if exists public.packages_review_token_uidx;
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- (e) Pin scoring_version type.
-- ---------------------------------------------------------------------------
alter table public.candidate_progress
    add column if not exists scoring_version varchar(64);

alter table public.candidate_progress
    alter column scoring_version type varchar(64);

-- ---------------------------------------------------------------------------
-- (f) Redundant responses index (left prefix of the 3-column unique index).
-- ---------------------------------------------------------------------------
drop index if exists public.idx_candidate_responses_cand_assessment;
