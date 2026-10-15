import { useEffect, useRef, useState } from 'react';
import type { TimerMode } from '../assessment-builder/types/module';

export interface ModuleTimerState {
  /** Seconds left; negative when a flexible timer runs over. Null when untimed. */
  remainingSeconds: number | null;
  expired: boolean;
  overtime: boolean;
}

interface ModuleTimerOptions {
  durationSeconds: number | null;
  timerMode: TimerMode;
  /** Server attempt start; null falls back to mount time (preview). */
  startedAt: string | null;
  onExpire?: () => void;
  enabled?: boolean;
  now?: () => number;
}

function computeRemaining(deadline: number | null, now: number): number | null {
  if (deadline === null) return null;
  return Math.ceil((deadline - now) / 1000);
}

/**
 * Countdown anchored to the server's `started_at`, so a reload resumes the
 * real remaining time instead of restarting the clock. Strict mode fires
 * `onExpire` exactly once; flexible mode keeps counting into overtime.
 *
 * @param options - Duration, mode, anchor, and expiry callback.
 * @returns Remaining seconds plus expiry/overtime flags.
 */
export function useModuleTimer({
  durationSeconds,
  timerMode,
  startedAt,
  onExpire,
  enabled = true,
  now = Date.now,
}: ModuleTimerOptions): ModuleTimerState {
  const nowRef = useRef(now);
  nowRef.current = now;
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;
  const firedRef = useRef(false);

  const [deadline] = useState<number | null>(() => {
    if (!durationSeconds) return null;
    const anchor = startedAt ? Date.parse(startedAt) : nowRef.current();
    return (Number.isFinite(anchor) ? anchor : nowRef.current()) + durationSeconds * 1000;
  });
  const [remaining, setRemaining] = useState<number | null>(() => computeRemaining(deadline, nowRef.current()));

  useEffect(() => {
    if (deadline === null || !enabled) return undefined;
    const tick = () => {
      const next = computeRemaining(deadline, nowRef.current());
      setRemaining(next);
      if (next !== null && next <= 0 && timerMode === 'strict' && !firedRef.current) {
        firedRef.current = true;
        onExpireRef.current?.();
      }
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [deadline, enabled, timerMode]);

  return {
    remainingSeconds: remaining,
    expired: remaining !== null && remaining <= 0 && timerMode === 'strict',
    overtime: remaining !== null && remaining < 0 && timerMode === 'flexible',
  };
}

export type TimerTone = 'safe' | 'urgent';

/** Fraction of the total duration that counts as the urgent final stretch. */
export const URGENT_FRACTION = 0.25;

/**
 * Green while more than the final quarter remains; red from the last 25%
 * onward, including expiry and flexible-mode overtime.
 *
 * @param remainingSeconds - Signed seconds left.
 * @param totalSeconds - Full module duration.
 * @returns Visual tone for the countdown.
 */
export function timerTone(remainingSeconds: number, totalSeconds: number): TimerTone {
  if (totalSeconds <= 0) return 'urgent';
  return remainingSeconds > totalSeconds * URGENT_FRACTION ? 'safe' : 'urgent';
}

/**
 * Format seconds as m:ss (or -m:ss for overtime).
 *
 * @param seconds - Signed seconds.
 * @returns Clock string.
 */
export function formatClock(seconds: number): string {
  const sign = seconds < 0 ? '-' : '';
  const abs = Math.abs(seconds);
  const m = Math.floor(abs / 60);
  const s = abs % 60;
  return `${sign}${m}:${String(s).padStart(2, '0')}`;
}
