import { useCallback, useEffect, useRef, useState } from 'react';

export interface ServerTimerState {
  /** Display seconds left, clamped at 0. Null when untimed. */
  remainingSeconds: number | null;
  expired: boolean;
  /**
   * Synchronously clear the interval and disarm auto-submit.
   * Call at the start of a manual submit so a near-zero tick cannot race.
   */
  stop: () => void;
}

export interface ServerTimerOptions {
  /** ISO-8601 UTC display deadline (`expires_at`). */
  expiresAt: string | null | undefined;
  /**
   * ISO-8601 UTC write-lock deadline (`write_expires_at`).
   * Defaults to ``expiresAt`` when omitted.
   */
  writeExpiresAt?: string | null | undefined;
  /** ISO-8601 UTC server clock for offset: ``Date.parse(serverNow) - Date.now()``. */
  serverNow: string | null | undefined;
  onExpire?: () => void;
  /** Fires once when the display clock hits 0 (may precede ``onExpire`` in grace). */
  onDisplayExpire?: () => void;
  enabled?: boolean;
  /** Wall clock; injectable for tests. */
  now?: () => number;
}

/**
 * Compute client↔server clock offset in milliseconds.
 *
 * @param serverNow - ISO server timestamp.
 * @param clientNowMs - Local ``Date.now()`` (or test clock).
 * @returns Offset such that ``clientNow + offset ≈ serverNow``.
 */
export function computeServerOffsetMs(
  serverNow: string | null | undefined,
  clientNowMs: number = Date.now(),
): number {
  if (!serverNow) return 0;
  const parsed = Date.parse(serverNow);
  if (!Number.isFinite(parsed)) return 0;
  return parsed - clientNowMs;
}

/**
 * Whole seconds remaining until an absolute UTC deadline.
 *
 * @param expiresAt - ISO deadline.
 * @param offsetMs - Server clock offset.
 * @param clientNowMs - Local wall clock.
 * @returns Clamped remaining seconds, or null when untimed / unparseable.
 */
export function remainingFromDeadline(
  expiresAt: string | null | undefined,
  offsetMs: number,
  clientNowMs: number = Date.now(),
): number | null {
  if (!expiresAt) return null;
  const deadlineMs = Date.parse(expiresAt);
  if (!Number.isFinite(deadlineMs)) return null;
  return Math.max(0, Math.ceil((deadlineMs - (clientNowMs + offsetMs)) / 1000));
}

/**
 * Wall-clock assessment timer driven by immutable ``expires_at`` + ``server_now``.
 *
 * Recalculates from the wall clock on every tick, on ``visibilitychange``, and
 * on window ``focus`` so navigating away / backgrounding never pauses the
 * countdown. Falls back to a null timer when deadlines are absent (untimed /
 * preview).
 *
 * @param options - Absolute deadlines and expiry callbacks.
 * @returns Remaining seconds (clamped) plus an expiry flag.
 */
export function useServerTimer({
  expiresAt,
  writeExpiresAt,
  serverNow,
  onExpire,
  onDisplayExpire,
  enabled = true,
  now = () => Date.now(),
}: ServerTimerOptions): ServerTimerState {
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

  const offsetMs = computeServerOffsetMs(serverNow, nowRef.current());
  const writeAt = writeExpiresAt === undefined ? expiresAt : writeExpiresAt;

  const [remaining, setRemaining] = useState<number | null>(() =>
    remainingFromDeadline(expiresAt, offsetMs, nowRef.current()),
  );

  const clearTicker = useCallback(() => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    pausedRef.current = true;
    clearTicker();
  }, [clearTicker]);

  useEffect(() => {
    expireFiredRef.current = false;
    displayFiredRef.current = false;
  }, [expiresAt, writeAt, serverNow]);

  useEffect(() => {
    if (!expiresAt || !enabled) {
      clearTicker();
      if (!expiresAt) setRemaining(null);
      return undefined;
    }
    pausedRef.current = false;
    const offset = computeServerOffsetMs(serverNow, nowRef.current());

    const tick = () => {
      if (pausedRef.current) return;
      const clientNow = nowRef.current();
      const displayRaw = remainingFromDeadline(expiresAt, offset, clientNow);
      if (displayRaw === null) {
        setRemaining(null);
      } else {
        setRemaining(displayRaw);
        if (displayRaw <= 0 && !displayFiredRef.current) {
          displayFiredRef.current = true;
          onDisplayExpireRef.current?.();
        }
      }
      const expireRaw = remainingFromDeadline(writeAt, offset, clientNow);
      if (expireRaw !== null && expireRaw <= 0 && !expireFiredRef.current) {
        expireFiredRef.current = true;
        onExpireRef.current?.();
      }
    };

    tick();
    intervalRef.current = window.setInterval(tick, 1000);

    const onVisible = () => {
      if (document.visibilityState === 'visible') tick();
    };
    const onFocus = () => tick();
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onFocus);

    return () => {
      clearTicker();
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onFocus);
    };
  }, [clearTicker, enabled, expiresAt, writeAt, serverNow]);

  return {
    remainingSeconds: remaining,
    expired: remaining !== null && remaining <= 0,
    stop,
  };
}
