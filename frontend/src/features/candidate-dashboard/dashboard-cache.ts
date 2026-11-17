import { peekQuery, setQuery } from '../../lib/query-cache';
import { CANDIDATE_DASHBOARD_KEY, type ModuleStatus } from './module-status';

/** Dashboard list stays warm for 30s; remounts paint cache then revalidate. */
export const CANDIDATE_DASHBOARD_STALE_MS = 30000;

export interface DashboardModulePatch {
  status: ModuleStatus;
  started_at?: string | null;
  expires_at?: string | null;
  server_now?: string | null;
  remaining_seconds?: number | null;
}

/**
 * Seconds left until ``expiresAt``, floored at zero.
 *
 * @param expiresAt - Absolute ISO deadline, if any.
 * @param serverNow - ISO clock to subtract from.
 * @returns Remaining whole seconds, or null when inputs are missing/invalid.
 */
export function remainingSecondsFromExpiry(
  expiresAt: string | null | undefined,
  serverNow: string,
): number | null {
  if (!expiresAt) return null;
  const end = Date.parse(expiresAt);
  const now = Date.parse(serverNow);
  if (!Number.isFinite(end) || !Number.isFinite(now)) return null;
  return Math.max(0, Math.ceil((end - now) / 1000));
}

/**
 * Optimistically patch one module row in the cached candidate dashboard.
 *
 * Writes the entry as stale so the next dashboard mount revalidates in the
 * background while still rendering the patched cards on frame 1 (no spinner).
 *
 * @param assessmentId - Module id to update.
 * @param patch - Exact status / timer fields to apply.
 */
export function patchCandidateDashboardModule(
  assessmentId: string,
  patch: DashboardModulePatch,
): void {
  const dash = peekQuery(CANDIDATE_DASHBOARD_KEY);
  if (!dash || typeof dash !== 'object') return;
  const data = dash as Record<string, unknown>;
  const tests = data.tests;
  if (!Array.isArray(tests)) return;

  const serverNow = patch.server_now ?? new Date().toISOString();
  const id = String(assessmentId);
  const nextTests = tests.map((raw) => {
    if (!raw || typeof raw !== 'object') return raw;
    const row = raw as Record<string, unknown>;
    if (String(row.id) !== id) return row;
    return {
      ...row,
      status: patch.status,
      ...(patch.started_at !== undefined ? { started_at: patch.started_at } : {}),
      ...(patch.expires_at !== undefined ? { expires_at: patch.expires_at } : {}),
      server_now: serverNow,
      ...(patch.remaining_seconds !== undefined
        ? { remaining_seconds: patch.remaining_seconds }
        : {}),
      launchable: patch.status !== 'completed',
    };
  });

  setQuery(
    CANDIDATE_DASHBOARD_KEY,
    { ...data, server_now: serverNow, tests: nextTests },
    { fresh: false },
  );
}
