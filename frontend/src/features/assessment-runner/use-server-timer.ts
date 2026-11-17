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
 * Uses ``Math.max(0, Math.ceil((expiresAtMs - (Date.now() + clockOffsetMs)) / 1000))``
 * so a skewed local system clock cannot inflate or shrink the countdown.
 *
 * @param expiresAt - ISO deadline.
 * @param clockOffsetMs - Server clock offset from calibration.
 * @param clientNowMs - Local wall clock.
 * @returns Clamped remaining seconds, or null when untimed / unparseable.
 */
export function remainingFromDeadline(
  expiresAt: string | null | undefined,
  clockOffsetMs: number,
  clientNowMs: number = Date.now(),
): number | null {
  if (!expiresAt) return null;
  const expiresAtMs = Date.parse(expiresAt);
  if (!Number.isFinite(expiresAtMs)) return null;
  return Math.max(0, Math.ceil((expiresAtMs - (clientNowMs + clockOffsetMs)) / 1000));
}

/**
 * Wall-clock assessment timer driven by immutable ``expires_at`` + ``server_now``.
 *
 * Calibrates ``clockOffsetMs = server_now - Date.now()`` once when the payload
 * arrives and keeps that offset across pause/resume. Recalculates remaining
 * time from the wall clock on every tick, on ``visibilitychange``, and on
 * window ``focus`` so background tabs / sleep never pause the countdown.
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
  // Calibrate once per payload; do not recompute when `enabled` flips after a
  // failed submit — that would treat a stale server_now as "now" and inflate remaining.
  const clockOffsetMsRef = useRef(0);
  const calibratedForRef = useRef<string | null>(null);

  // Explicit null write deadline stays null — do not invent a deadline from thin air.
  // Omitted (undefined) falls back to display expiresAt for grace-less payloads.
  const writeAt =
    writeExpiresAt === undefined
      ? expiresAt
      : writeExpiresAt && writeExpiresAt.length > 0
        ? writeExpiresAt
        : null;
  const calibrationKey = `${expiresAt ?? ''}|${writeAt ?? ''}|${serverNow ?? ''}`;

  const [remaining, setRemaining] = useState<number | null>(() => {
    const offset = computeServerOffsetMs(serverNow, nowRef.current());
    return remainingFromDeadline(expiresAt, offset, nowRef.current());
  });

  // Recalibrate whenever GET /test or POST /start returns new timing metadata.
  // Derive remaining from the absolute deadline — never from a drifting counter.
  if (calibratedForRef.current !== calibrationKey) {
    const hadPriorCalibration = calibratedForRef.current !== null;
    calibratedForRef.current = calibrationKey;
    const clientNow = nowRef.current();
    clockOffsetMsRef.current = computeServerOffsetMs(serverNow, clientNow);
    // Skip setState on the initial mount — useState already seeded remaining.
    if (hadPriorCalibration) {
      setRemaining(remainingFromDeadline(expiresAt, clockOffsetMsRef.current, clientNow));
    }
  }

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
    // #region agent log
    fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'cb1f3d'},body:JSON.stringify({sessionId:'cb1f3d',runId:'pre-fix',hypothesisId:'B,C,D',location:'use-server-timer.ts:effect',message:'server timer effect arm',data:{expiresAt:expiresAt??null,writeAt:writeAt??null,serverNow:serverNow??null,enabled,hasExpires:Boolean(expiresAt),hasWrite:Boolean(writeAt)},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    if (!expiresAt || !enabled) {
      clearTicker();
      if (!expiresAt) setRemaining(null);
      return undefined;
    }
    pausedRef.current = false;
    const clockOffsetMs = clockOffsetMsRef.current;

    const tick = () => {
      if (pausedRef.current) return;
      const clientNow = nowRef.current();
      const displayRaw = remainingFromDeadline(expiresAt, clockOffsetMs, clientNow);
      if (displayRaw === null) {
        setRemaining(null);
      } else {
        setRemaining(displayRaw);
        if (displayRaw <= 0 && !displayFiredRef.current) {
          displayFiredRef.current = true;
          onDisplayExpireRef.current?.();
        }
      }
      // Auto-submit only when an absolute write deadline exists and has elapsed.
      const expireRaw = writeAt
        ? remainingFromDeadline(writeAt, clockOffsetMs, clientNow)
        : null;
      // #region agent log
      if (expireRaw !== null && expireRaw <= 0) {
        fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'cb1f3d'},body:JSON.stringify({sessionId:'cb1f3d',runId:'post-fix',hypothesisId:'B,D',location:'use-server-timer.ts:tick-expire',message:'server timer expire gate',data:{expiresAt:expiresAt??null,writeAt:writeAt??null,displayRaw,expireRaw,expireFired:expireFiredRef.current,willFire:!expireFiredRef.current&&Boolean(writeAt)},timestamp:Date.now()})}).catch(()=>{});
      }
      // #endregion
      if (writeAt && expireRaw !== null && expireRaw <= 0 && !expireFiredRef.current) {
        expireFiredRef.current = true;
        onExpireRef.current?.();
      }
    };

    tick();
    intervalRef.current = window.setInterval(tick, 1000);

    const onVisibility = () => {
      // Recalculate immediately when the tab wakes; also harmless on hide.
      tick();
    };
    const onFocus = () => tick();
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('focus', onFocus);

    return () => {
      clearTicker();
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('focus', onFocus);
    };
  }, [clearTicker, enabled, expiresAt, writeAt, serverNow]);

  return {
    remainingSeconds: remaining,
    expired: remaining !== null && remaining <= 0,
    stop,
  };
}
