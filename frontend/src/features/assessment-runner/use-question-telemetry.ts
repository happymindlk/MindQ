import { useCallback, useEffect, useRef } from 'react';
import { clampElapsed } from '../assessment-builder/types/telemetry';
import type { AnswerValue, QuestionTelemetry } from '../assessment-builder/types/telemetry';

interface QuestionClock {
  startedAt: string;
  accumulatedMs: number;
  activeSince: number | null;
}

export interface TelemetryClock {
  /** Monotonic milliseconds (performance.now in browsers). */
  now: () => number;
  /** Wall-clock ISO timestamp for `started_at`. */
  isoNow: () => string;
}

const defaultClock: TelemetryClock = {
  now: () => (typeof performance !== 'undefined' ? performance.now() : Date.now()),
  isoNow: () => new Date().toISOString(),
};

export interface QuestionTelemetryApi {
  elapsedFor: (questionId: string) => number;
  totalModuleSeconds: () => number;
  snapshot: (answers: Record<string, AnswerValue>) => QuestionTelemetry[];
}

/**
 * Silent per-question timing ("cognitive velocity").
 *
 * Uses a monotonic clock so system-clock changes can't skew durations, sums
 * time across revisits, and pauses while the tab is hidden so a candidate who
 * walks away isn't recorded as deliberating. Server-side duration remains the
 * source of truth; these numbers are advisory.
 *
 * @param activeQuestionId - Question currently on screen, or null.
 * @param clock - Injectable clock for tests.
 * @returns Readers for per-question and module durations.
 */
export function useQuestionTelemetry(
  activeQuestionId: string | null,
  clock: TelemetryClock = defaultClock,
): QuestionTelemetryApi {
  const clocksRef = useRef(new Map<string, QuestionClock>());
  const activeRef = useRef<string | null>(null);
  const moduleStartRef = useRef<number | null>(null);
  const clockRef = useRef(clock);
  clockRef.current = clock;

  const pause = useCallback((questionId: string | null) => {
    if (!questionId) return;
    const entry = clocksRef.current.get(questionId);
    if (!entry || entry.activeSince === null) return;
    entry.accumulatedMs += Math.max(0, clockRef.current.now() - entry.activeSince);
    entry.activeSince = null;
  }, []);

  const resume = useCallback((questionId: string | null) => {
    if (!questionId) return;
    const now = clockRef.current.now();
    const entry = clocksRef.current.get(questionId);
    if (entry) {
      if (entry.activeSince === null) entry.activeSince = now;
      return;
    }
    clocksRef.current.set(questionId, {
      startedAt: clockRef.current.isoNow(),
      accumulatedMs: 0,
      activeSince: now,
    });
  }, []);

  useEffect(() => {
    if (moduleStartRef.current === null) moduleStartRef.current = clockRef.current.now();
  }, []);

  useEffect(() => {
    pause(activeRef.current);
    activeRef.current = activeQuestionId;
    if (typeof document === 'undefined' || document.visibilityState !== 'hidden') resume(activeQuestionId);
  }, [activeQuestionId, pause, resume]);

  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') pause(activeRef.current);
      else resume(activeRef.current);
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      pause(activeRef.current);
    };
  }, [pause, resume]);

  const elapsedFor = useCallback((questionId: string): number => {
    const entry = clocksRef.current.get(questionId);
    if (!entry) return 0;
    const live = entry.activeSince === null ? 0 : clockRef.current.now() - entry.activeSince;
    return clampElapsed((entry.accumulatedMs + Math.max(0, live)) / 1000);
  }, []);

  const totalModuleSeconds = useCallback((): number => {
    const start = moduleStartRef.current;
    if (start === null) return 0;
    return clampElapsed((clockRef.current.now() - start) / 1000);
  }, []);

  const snapshot = useCallback(
    (answers: Record<string, AnswerValue>): QuestionTelemetry[] =>
      Array.from(clocksRef.current.entries()).map(([questionId, entry]) => ({
        question_id: questionId,
        selected_option: answers[questionId] ?? null,
        elapsed_seconds: elapsedFor(questionId),
        started_at: entry.startedAt,
      })),
    [elapsedFor],
  );

  return { elapsedFor, totalModuleSeconds, snapshot };
}
