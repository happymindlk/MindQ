/** Pipeline status for Assessment History and the HR client dashboard. */

export function pipelineStatus(row) {
  const total = Number(row.total_assessments) || 0;
  const completed = Number(row.completed_assessments) || 0;
  let status;
  // Prefer server-provided status, but never keep a fully submitted package
  // in Scoring just because report synthesis failed or is still pending.
  if (total > 0 && completed >= total) status = 'completed';
  else if (row.pipeline_status) status = row.pipeline_status;
  else if (completed > 0 || row.logged_in_at) status = 'scoring';
  else status = 'pending';
  // #region agent log
  if (total > 0 && completed >= total) {
    fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'f04232'},body:JSON.stringify({sessionId:'f04232',runId:'post-fix',hypothesisId:'H1',location:'pipeline-status.js:pipelineStatus',message:'ui_status_for_full_package',data:{id:row.id||row.candidate_id||null,completed,total,evaluated:!!row.evaluated,pipeline_status:row.pipeline_status||null,status,label:status==='scoring'?'In Progress':status},timestamp:Date.now()})}).catch(()=>{});
  }
  // #endregion
  return status;
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
