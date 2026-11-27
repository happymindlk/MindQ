-- MindQ Scoring Specification v2: persist instrument details and scoring version.
alter table candidate_progress
  add column if not exists score_details jsonb,
  add column if not exists scoring_version text;
