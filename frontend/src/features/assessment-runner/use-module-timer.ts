import { useCallback, useEffect, useRef, useState } from 'react';

export interface ModuleTimerState {
  /** Display seconds left, clamped at 0. Null when untimed. */
  remainingSeconds: number | null;
  expired: boolean;
  /**
   * Synchronously clear the interval and disarm auto-submit.
   * Call at the start of a manual submit so a near-zero tick cannot race.
   */
  stop: () => void;
}

interface ModuleTimerOptions {
  /** Server-computed display countdown seed; null when untimed. */
  remainingSeconds: number | null;
  /**
   * Seconds until write-lock / auto-submit. Defaults to ``remainingSeconds``.
   * When larger than the display seed (grace window), the clock shows 0:00
   * while ``onExpire`` waits for this deadline.
   */
  expireRemainingSeconds?: number | null;
  onExpire?: () => void;
  /** Fires once when the display clock hits 0 (may precede ``onExpire`` in grace). */
  onDisplayExpire?: () => void;
  enabled?: boolean;
  /** Monotonic millisecond clock; only differences are used, never absolute dates. */
  now?: () => number;
}

function monotonicNow(): number {
  return performance.now();
}

function computeRemaining(deadline: number | null, now: number): number | null {
  if (deadline === null) return null;
  return Math.ceil((deadline - now) / 1000);
}

function seedDeadline(
  remainingSeconds: number | null | undefined,
  now: number,
): number | null {
  if (remainingSeconds === null || remainingSeconds === undefined || !Number.isFinite(remainingSeconds)) {
    return null;
  }
  return now + Math.max(0, remainingSeconds) * 1000;
}

/**
 * Countdown seeded by the server's integer remaining seconds.
 *
 * The client never diffs `started_at` against its own wall clock, so device
 * clock skew or timezone parsing cannot shorten or extend an attempt. A
 * monotonic local deadline (rather than decrementing per interval) keeps the
 * display accurate when background tabs throttle `setInterval`.
 *
 * Display clamps at 00:00 from ``remainingSeconds``. Auto-submit fires from
 * ``expireRemainingSeconds`` (duration + grace) so resume during the server
 * grace window does not instant-submit.
 *
 * @param options - Server remaining seconds and expiry callback.
 * @returns Remaining seconds (clamped) plus an expiry flag.
 */
export function useModuleTimer({
  remainingSeconds,
  expireRemainingSeconds,
  onExpire,
  onDisplayExpire,
  enabled = true,
  now = monotonicNow,
}: ModuleTimerOptions): ModuleTimerState {
  const nowRef = useRef(now);
  nowRef.current = now;
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;
  const onDisplayExpireRef = useRef(onDisplayExpire);
  onDisplayExpireRef.current = onDisplayExpire;
  const expireFiredRef = useRef(false);
  const displayFiredRef = useRef(false);
  const pausedRef = useRef(false);
  const intervalRef = useRef<number | null>(null);

  const [displayDeadline] = useState<number | null>(() =>
    seedDeadline(remainingSeconds, nowRef.current()),
  );
  const [expireDeadline] = useState<number | null>(() => {
    const seed =
      expireRemainingSeconds === undefined ? remainingSeconds : expireRemainingSeconds;
    return seedDeadline(seed, nowRef.current());
  });
  const [remaining, setRemaining] = useState<number | null>(() => {
    const raw = computeRemaining(displayDeadline, nowRef.current());
    return raw === null ? null : Math.max(0, raw);
  });

  const clearTicker = useCallback(() => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    // Pause only — do not mark expired so a failed submit can resume the clock.
    pausedRef.current = true;
    clearTicker();
  }, [clearTicker]);

  useEffect(() => {
    if ((displayDeadline === null && expireDeadline === null) || !enabled) {
      clearTicker();
      return undefined;
    }
    // Re-arm after a failed submit flips `enabled` back on.
    pausedRef.current = false;
    const tick = () => {
      // Manual submit may freeze the clock mid-tick before React re-renders.
      if (pausedRef.current) return;
      const nowMs = nowRef.current();
      const displayRaw = computeRemaining(displayDeadline, nowMs);
      if (displayRaw === null) {
        setRemaining(null);
      } else {
        setRemaining(Math.max(0, displayRaw));
        if (displayRaw <= 0 && !displayFiredRef.current) {
          displayFiredRef.current = true;
          onDisplayExpireRef.current?.();
        }
      }
      const expireRaw = computeRemaining(expireDeadline, nowMs);
      if (expireRaw !== null && expireRaw <= 0 && !expireFiredRef.current) {
        expireFiredRef.current = true;
        onExpireRef.current?.();
      }
    };
    tick();
    intervalRef.current = window.setInterval(tick, 1000);
    return () => clearTicker();
  }, [clearTicker, displayDeadline, enabled, expireDeadline]);

  return {
    remainingSeconds: remaining,
    expired: remaining !== null && remaining <= 0,
    stop,
  };
}

export type TimerTone = 'safe' | 'caution' | 'urgent';

/** Remaining fraction above which the countdown stays green. */
export const SAFE_FRACTION = 2 / 3;
/** Remaining fraction above which the countdown is amber (below: red). */
export const CAUTION_FRACTION = 1 / 3;

/**
 * Dynamic 3-stage tone scaled to the total duration: green while more than
 * two-thirds remains, amber between one-third and two-thirds, red below
 * one-third — including expiry. E.g. an 18-minute test is green 18–12 min,
 * amber 12–6 min, red under 6 min.
 *
 * @param remainingSeconds - Seconds left (may be negative from callers).
 * @param totalSeconds - Full module duration.
 * @returns Visual tone for the countdown.
 */
export function timerTone(remainingSeconds: number, totalSeconds: number): TimerTone {
  if (totalSeconds <= 0) return 'urgent';
  if (remainingSeconds > totalSeconds * SAFE_FRACTION) return 'safe';
  if (remainingSeconds > totalSeconds * CAUTION_FRACTION) return 'caution';
  return 'urgent';
}

/**
 * Format seconds as m:ss. Values at or below zero render as ``0:00``.
 *
 * @param seconds - Seconds remaining (negative values clamp to zero).
 * @returns Clock string.
 */
export function formatClock(seconds: number): string {
  const abs = Math.max(0, Math.floor(seconds));
  const m = Math.floor(abs / 60);
  const s = abs % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}
