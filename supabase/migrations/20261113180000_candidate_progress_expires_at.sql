-- Immutable display deadline for timed assessment attempts.
-- Set once at start: expires_at = started_at + duration_seconds. Never extended.

alter table public.candidate_progress
    add column if not exists expires_at timestamptz;

comment on column public.candidate_progress.expires_at is
    'Server-authoritative display deadline (started_at + duration). Immutable after start.';

-- Backfill in-progress timed attempts from started_at + assessment duration.
update public.candidate_progress cp
set expires_at = cp.started_at
    + make_interval(
        secs => coalesce(
            nullif(a.duration_seconds, 0),
            case when a.time_limit_minutes is not null and a.time_limit_minutes > 0
                 then a.time_limit_minutes * 60
                 else null
            end
        )
    )
from public.assessments a
where a.id = cp.assessment_id
  and cp.started_at is not null
  and cp.expires_at is null
  and cp.status = 'IN_PROGRESS'
  and coalesce(
        nullif(a.duration_seconds, 0),
        case when a.time_limit_minutes is not null and a.time_limit_minutes > 0
             then a.time_limit_minutes * 60
             else null
        end
      ) is not null;

create index if not exists idx_candidate_progress_expires_in_progress
    on public.candidate_progress (expires_at)
    where status = 'IN_PROGRESS' and expires_at is not null;
