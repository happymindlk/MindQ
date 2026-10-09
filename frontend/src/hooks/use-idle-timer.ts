import { useCallback, useEffect, useRef } from 'react';

export const DEFAULT_IDLE_TIMEOUT_MS = 15 * 60 * 1000;
export const IDLE_ACTIVITY_EVENTS = ['mousemove', 'keydown', 'click', 'scroll'] as const;
export const LAST_ACTIVITY_STORAGE_KEY = 'mindq.lastActivity';
const ACTIVITY_THROTTLE_MS = 1000;

/** Options for {@link useIdleTimer}. */
export interface UseIdleTimerOptions {
  /** Fired once when no activity has been seen for `timeoutMs`. Re-armed by `reset()`. */
  onIdle: () => void;
  /** Inactivity window in milliseconds. Defaults to 15 minutes. */
  timeoutMs?: number;
  /** When false, no listeners or timers are installed. */
  enabled?: boolean;
  /** DOM events that count as user activity. */
  events?: readonly string[];
}

/** Imperative controls returned by {@link useIdleTimer}. */
export interface IdleTimerControls {
  /** Records activity now and re-arms the timer after it has fired. */
  reset: () => void;
  /** Milliseconds left before `onIdle` fires (0 once elapsed). */
  getRemainingMs: () => number;
}

function readSharedActivity(): number | null {
  try {
    const raw = window.localStorage.getItem(LAST_ACTIVITY_STORAGE_KEY);
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function writeSharedActivity(at: number): void {
  try {
    window.localStorage.setItem(LAST_ACTIVITY_STORAGE_KEY, String(at));
  } catch {
    // Storage can be unavailable (private mode / quota); the in-memory timestamp still works.
  }
}

/**
 * Calls `onIdle` after `timeoutMs` of continuous inactivity.
 *
 * The deadline is computed from a last-activity timestamp rather than a single long
 * `setTimeout`, so throttled background tabs still lock correctly on the next wake or
 * `visibilitychange`. The timestamp is mirrored to localStorage so activity in any
 * tab keeps every tab of the portal alive.
 */
export function useIdleTimer({
  onIdle,
  timeoutMs = DEFAULT_IDLE_TIMEOUT_MS,
  enabled = true,
  events = IDLE_ACTIVITY_EVENTS,
}: UseIdleTimerOptions): IdleTimerControls {
  const onIdleRef = useRef(onIdle);
  const lastActivityRef = useRef(Date.now());
  const lastWriteRef = useRef(0);
  const firedRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    onIdleRef.current = onIdle;
  }, [onIdle]);

  const getRemainingMs = useCallback(
    () => Math.max(0, timeoutMs - (Date.now() - lastActivityRef.current)),
    [timeoutMs],
  );

  const reset = useCallback(() => {
    const now = Date.now();
    firedRef.current = false;
    lastActivityRef.current = now;
    lastWriteRef.current = now;
    writeSharedActivity(now);
    scheduleRef.current();
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    const clearTimer = () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const check = () => {
      if (firedRef.current) return;
      const shared = readSharedActivity();
      if (shared !== null && shared > lastActivityRef.current) {
        lastActivityRef.current = shared;
      }
      if (Date.now() - lastActivityRef.current >= timeoutMs) {
        firedRef.current = true;
        clearTimer();
        onIdleRef.current();
        return;
      }
      schedule();
    };

    const schedule = () => {
      clearTimer();
      if (firedRef.current) return;
      const remaining = Math.max(0, timeoutMs - (Date.now() - lastActivityRef.current));
      timerRef.current = setTimeout(check, remaining);
    };
    scheduleRef.current = schedule;

    const onActivity = () => {
      if (firedRef.current) return;
      const now = Date.now();
      lastActivityRef.current = now;
      if (now - lastWriteRef.current < ACTIVITY_THROTTLE_MS) return;
      lastWriteRef.current = now;
      writeSharedActivity(now);
    };

    const onStorage = (event: StorageEvent) => {
      if (event.key !== LAST_ACTIVITY_STORAGE_KEY || !event.newValue) return;
      const at = Number(event.newValue);
      if (Number.isFinite(at) && at > lastActivityRef.current) {
        lastActivityRef.current = at;
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === 'visible') check();
    };

    firedRef.current = false;
    lastActivityRef.current = Date.now();
    lastWriteRef.current = lastActivityRef.current;
    writeSharedActivity(lastActivityRef.current);

    // Capture phase so `scroll` from nested overflow containers (which does not bubble) counts.
    const listenerOptions: AddEventListenerOptions = { passive: true, capture: true };
    events.forEach((name) => document.addEventListener(name, onActivity, listenerOptions));
    window.addEventListener('storage', onStorage);
    document.addEventListener('visibilitychange', onVisibility);
    schedule();

    return () => {
      clearTimer();
      scheduleRef.current = () => undefined;
      events.forEach((name) => document.removeEventListener(name, onActivity, listenerOptions));
      window.removeEventListener('storage', onStorage);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, timeoutMs, events]);

  return { reset, getRemainingMs };
}
