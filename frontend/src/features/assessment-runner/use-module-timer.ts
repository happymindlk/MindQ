import { useEffect, useRef, useState } from 'react';

export interface ModuleTimerState {
  /** Seconds left, clamped at 0. Null when untimed. */
  remainingSeconds: number | null;
  expired: boolean;
}

interface ModuleTimerOptions {
  durationSeconds: number | null;
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
 * real remaining time instead of restarting the clock. Any timed module
 * clamps at 00:00 and fires `onExpire` exactly once (hard cut-off).
 *
 * @param options - Duration, anchor, and expiry callback.
 * @returns Remaining seconds (clamped) plus an expiry flag.
 */
export function useModuleTimer({
  durationSeconds,
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
    const resolved = (Number.isFinite(anchor) ? anchor : nowRef.current()) + durationSeconds * 1000;
    // #region agent log
    fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'5f236f'},body:JSON.stringify({sessionId:'5f236f',runId:'pre-fix',hypothesisId:'A',location:'use-module-timer.ts:deadline',message:'client timer deadline init',data:{startedAt,startedAtParsed:startedAt?Date.parse(startedAt):null,startedAtFinite:startedAt?Number.isFinite(Date.parse(startedAt)):null,durationSeconds,now:nowRef.current(),deadline:resolved,initialRemaining:Math.ceil((resolved-nowRef.current())/1000),tzOffsetMinutes:new Date().getTimezoneOffset()},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    return resolved;
  });
  const [remaining, setRemaining] = useState<number | null>(() => {
    const raw = computeRemaining(deadline, nowRef.current());
    return raw === null ? null : Math.max(0, raw);
  });

  useEffect(() => {
    if (deadline === null || !enabled) return undefined;
    const tick = () => {
      const raw = computeRemaining(deadline, nowRef.current());
      if (raw === null) {
        setRemaining(null);
        return;
      }
      // #region agent log
      if (raw <= 2 || raw % 30 === 0) {
        fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'5f236f'},body:JSON.stringify({sessionId:'5f236f',runId:'pre-fix',hypothesisId:'A',location:'use-module-timer.ts:tick',message:'client timer tick',data:{raw,deadline,now:nowRef.current(),startedAt},timestamp:Date.now()})}).catch(()=>{});
      }
      // #endregion
      setRemaining(Math.max(0, raw));
      if (raw <= 0 && !firedRef.current) {
        firedRef.current = true;
        onExpireRef.current?.();
      }
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [deadline, enabled]);

  return {
    remainingSeconds: remaining,
    expired: remaining !== null && remaining <= 0,
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
