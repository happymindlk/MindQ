import { useEffect, useState } from 'react';

export type WindowState = 'not_open' | 'open' | 'closed';

/** Browsers clamp setTimeout delays above 2^31-1 ms (~24.8 days) to fire immediately. */
const MAX_TIMEOUT_MS = 2_147_483_647;
/** Fire just after the boundary so the recomputed state is past it. */
const BOUNDARY_GRACE_MS = 250;

/**
 * Classify `now` against the package window, mirroring the backend rules.
 *
 * @returns `not_open` before open, `closed` at/after close, else `open`.
 */
export function computeWindowState(
  openTime: string | null | undefined,
  closeTime: string | null | undefined,
  now: number = Date.now(),
): WindowState {
  const open = openTime ? Date.parse(openTime) : Number.NaN;
  const close = closeTime ? Date.parse(closeTime) : Number.NaN;
  if (!Number.isNaN(open) && now < open) return 'not_open';
  if (!Number.isNaN(close) && now >= close) return 'closed';
  return 'open';
}

/**
 * Why a module tile cannot be launched, mirroring the backend launch gate:
 * nothing before open; after close only modules already in progress.
 *
 * @returns Short reason for the tile, or `null` when it can be launched/viewed.
 */
export function lockedReasonFor(status: string, state: WindowState): string | null {
  if (status === 'completed') return null;
  if (state === 'not_open') return 'Not open yet';
  if (state === 'closed' && status !== 'in_progress') return 'Assessment closed';
  return null;
}

function nextBoundaryDelay(
  openTime: string | null | undefined,
  closeTime: string | null | undefined,
  now: number,
): number | null {
  const upcoming = [openTime, closeTime]
    .map((value) => (value ? Date.parse(value) : Number.NaN))
    .filter((ts) => !Number.isNaN(ts) && ts > now);
  if (upcoming.length === 0) return null;
  return Math.min(Math.min(...upcoming) - now + BOUNDARY_GRACE_MS, MAX_TIMEOUT_MS);
}

/**
 * Live window state for the candidate dashboard. Starts from the server's
 * verdict (authoritative against client clock skew) and re-evaluates locally
 * when the open/close boundary passes while the page is open.
 *
 * @param serverState - `window_state` from the dashboard API, if provided.
 * @param openTime - ISO open instant.
 * @param closeTime - ISO deadline.
 */
export function usePackageWindow(
  serverState: WindowState | null | undefined,
  openTime: string | null | undefined,
  closeTime: string | null | undefined,
): WindowState {
  const [state, setState] = useState<WindowState>(
    serverState ?? computeWindowState(openTime, closeTime),
  );

  useEffect(() => {
    setState(serverState ?? computeWindowState(openTime, closeTime));
  }, [serverState, openTime, closeTime]);

  useEffect(() => {
    const delay = nextBoundaryDelay(openTime, closeTime, Date.now());
    if (delay === null) return undefined;
    const timer = window.setTimeout(() => {
      setState(computeWindowState(openTime, closeTime));
    }, delay);
    return () => window.clearTimeout(timer);
  }, [openTime, closeTime, state]);

  return state;
}
