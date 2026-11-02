export type ModuleStatus = 'not_started' | 'in_progress' | 'completed';

/** Cache key for the candidate portal dashboard package payload. */
export const CANDIDATE_DASHBOARD_KEY = 'portal:candidate-dashboard';

/**
 * Normalize API / DB progress status into the portal card lifecycle.
 *
 * @param status - Raw status from the dashboard payload or progress row.
 * @returns Canonical lowercase lifecycle status.
 */
export function normalizeModuleStatus(status: string | null | undefined): ModuleStatus {
  const raw = String(status || 'not_started')
    .trim()
    .toUpperCase()
    .replace(/[-\s]/g, '_');
  if (raw === 'COMPLETED') return 'completed';
  if (raw === 'IN_PROGRESS') return 'in_progress';
  return 'not_started';
}
