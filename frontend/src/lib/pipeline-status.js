/** Pipeline status for Assessment History and the HR client dashboard. */

export function pipelineStatus(row) {
  const total = Number(row.total_assessments) || 0;
  const completed = Number(row.completed_assessments) || 0;
  if (row.pipeline_status) return row.pipeline_status;
  if (total > 0 && completed >= total) {
    return row.jd_fit != null ? 'completed' : 'scoring';
  }
  if (completed > 0 || row.logged_in_at) return 'scoring';
  return 'pending';
}

/** Shared Tailwind classes — keep in sync with Badge variants. */
export const PIPELINE_PILL = {
  pending: 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
  scoring: 'bg-blue-500/10 text-blue-400 border border-blue-500/20',
  completed: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
  draft: 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
  published: 'bg-neutral-800 text-neutral-400 border border-neutral-700',
  locked: 'bg-neutral-800 text-neutral-400 border border-neutral-700',
  archived: 'bg-neutral-800 text-neutral-400 border border-neutral-700',
  active: 'bg-blue-500/10 text-blue-400 border border-blue-500/20',
};

export const PIPELINE_LABEL = {
  pending: 'Pending',
  scoring: 'In Progress',
  completed: 'Completed',
  draft: 'Draft',
  published: 'Locked',
  locked: 'Locked',
  archived: 'Archived',
  active: 'Active',
};

export const PIPELINE_BADGE_VARIANT = {
  pending: 'pending',
  scoring: 'scoring',
  completed: 'completed',
  draft: 'draft',
  published: 'locked',
  locked: 'locked',
  archived: 'archived',
  active: 'active',
};

/**
 * Map package lifecycle status to a badge key.
 *
 * @param {string | undefined} status
 * @param {boolean} [isActive]
 * @returns {string}
 */
export function packageLifecycleStatus(status, isActive) {
  const raw = (status || (isActive ? 'published' : 'draft')).toLowerCase();
  if (raw === 'draft') return 'draft';
  if (raw === 'archived') return 'archived';
  if (raw === 'published' || raw === 'locked') return 'locked';
  return raw;
}
