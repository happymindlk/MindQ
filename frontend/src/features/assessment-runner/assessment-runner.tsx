import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ClipboardEvent, MouseEvent, ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { AlarmClock, CheckCircle2, ChevronLeft, ChevronRight, Info, WifiOff } from 'lucide-react';
import type { RunnerTest } from '../assessment-builder/api/library-api';
import { MarkdownText } from '../assessment-builder/components/markdown-preview';
import type { AnswerValue, ResponseSavePayload, ResponseSubmitPayload } from '../assessment-builder/types/telemetry';
import { GpuSpinner } from '../../components/ui/gpu-spinner';
import { resolveAssessmentMediaUrl } from '../../lib/resolve-assessment-media-url';
import { RunnerQuestionInput } from './runner-question-input';
import {
  buildResponses,
  hasAbsoluteDeadline,
  hasContent,
  isAnswered,
  isAttemptLocked,
  isTerminalSubmitConflict,
  isTimeExpired,
  isUnauthorized,
  resolveRemainingSeconds,
  resolveResumeIndex,
  resolveTopDisclaimer,
} from './runner-logic';
import { formatClock, timerTone, useModuleTimer } from './use-module-timer';
import { useServerTimer } from './use-server-timer';
import { useQuestionTelemetry } from './use-question-telemetry';

/** Exact copy for the full-screen timed-out completion state. */
export const ASSESSMENT_TIMEOUT_MESSAGE =
  'Your time to complete this assessment has concluded. All the completed questions are saved and recorded successfully.';

/** Hold the Submitted confirmation so the overlay never flash-redirects away. */
export const TIMEOUT_AUTO_EXIT_MS = 2000;

/** Leading-edge guard against rapid Next / confirm double-clicks. */
const NAV_DEBOUNCE_MS = 300;
/** Choice / Likert / SJT selections coalesce into one POST after this delay. */
const CHOICE_AUTOSAVE_MS = 300;
/** Free-text typing waits longer so keystrokes do not spam the network. */
const TEXT_AUTOSAVE_MS = 800;

const TEXT_QUESTION_TYPES = new Set(['crt', 'open', 'open_ended']);

/** Background retry for failed autosaves: 2s, 4s, 8s, ... capped at 30s. */
export const SAVE_RETRY_BASE_MS = 2000;
export const SAVE_RETRY_MAX_MS = 30000;

function autosaveDelayForType(questionType: string | undefined): number {
  return questionType && TEXT_QUESTION_TYPES.has(questionType)
    ? TEXT_AUTOSAVE_MS
    : CHOICE_AUTOSAVE_MS;
}

function blockClipboard(event: ClipboardEvent | MouseEvent) {
  event.preventDefault();
}

export interface AutosaveOptions {
  /** Let the request outlive the page (pagehide / tab close flush). */
  keepalive?: boolean;
}

export interface RunnerTransport {
  autosave: (payload: ResponseSavePayload, options?: AutosaveOptions) => Promise<void>;
  submit: (body: ResponseSubmitPayload) => Promise<void>;
}

interface AssessmentRunnerProps {
  test: RunnerTest;
  mode: 'live' | 'preview';
  initialAnswers: Record<string, AnswerValue>;
  transport: RunnerTransport;
  onAnswersChange?: (answers: Record<string, AnswerValue>) => void;
  onSubmitted: () => void;
  /** Called instead of `onSubmitted` when a timed-module expiry submit succeeds. */
  onTimeExpired?: () => void;
  /**
   * Fired synchronously the instant the write deadline hits — before the submit
   * network call — so the parent portal can pin the timeout notice and refuse
   * to unmount / route away while Submitting... is on screen.
   */
  onTimeoutStarted?: () => void;
  onLocked: (message: string) => void;
  /**
   * Fired when autosave or submit returns 401 (session expired / revoked).
   * The local draft is left intact so the attempt resumes after re-login.
   */
  onUnauthorized?: () => void;
  onExit: () => void;
  exitLabel?: string;
  /** Rendered under the card; preview mode uses it for the telemetry strip. */
  renderFooter?: (api: { elapsedFor: (id: string) => number; totalSeconds: () => number; answers: Record<string, AnswerValue> }) => ReactNode;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export function AssessmentRunner({
  test,
  mode,
  initialAnswers,
  transport,
  onAnswersChange,
  onSubmitted,
  onTimeExpired,
  onTimeoutStarted,
  onLocked,
  onUnauthorized,
  onExit,
  exitLabel = 'Back to dashboard',
  renderFooter,
}: AssessmentRunnerProps) {
  const questions = test.questions;
  const [index, setIndex] = useState(() => resolveResumeIndex(questions, initialAnswers));
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>(initialAnswers);
  const [saveError, setSaveError] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [timeUp, setTimeUp] = useState(false);
  const [offline, setOffline] = useState(
    () => (typeof navigator !== 'undefined' ? !navigator.onLine : false),
  );

  const current = questions[index];
  const topDisclaimer = useMemo(() => resolveTopDisclaimer(test), [test]);
  const telemetry = useQuestionTelemetry(current?.id ?? null);
  const answersRef = useRef(answers);
  answersRef.current = answers;
  const dirtyRef = useRef<Set<string>>(new Set());
  const inFlightSaveRef = useRef<Set<string>>(new Set());
  const submittedRef = useRef(false);
  /** Bumped to drop pending / in-flight autosave work before auto-submit. */
  const autosaveEpochRef = useRef(0);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /** Pending background retry after a failed autosave (P1-03). */
  const saveRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveRetryDelayRef = useRef(SAVE_RETRY_BASE_MS);
  /** Latest flushDirty, so the retry timer never calls a stale closure. */
  const flushDirtyRef = useRef<() => Promise<void>>(async () => undefined);
  const timerStopRef = useRef<(() => void) | null>(null);
  const lastAdvanceAtRef = useRef(0);
  const lastOpenConfirmAtRef = useRef(0);
  const lastConfirmSubmitAtRef = useRef(0);
  /** Prevents double navigation from the auto-exit timer and the Back button. */
  const exitFiredRef = useRef(false);

  const clearDebounceTimer = useCallback(() => {
    if (debounceTimerRef.current !== null) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
  }, []);

  const clearSaveRetryTimer = useCallback(() => {
    if (saveRetryTimerRef.current !== null) {
      clearTimeout(saveRetryTimerRef.current);
      saveRetryTimerRef.current = null;
    }
  }, []);

  /**
   * Retry dirty answers on an exponential backoff while saves keep failing,
   * so a brief network drop recovers even if the candidate stays on one
   * question. One timer at a time; reset to 2s after any successful save.
   */
  const scheduleSaveRetry = useCallback(() => {
    if (saveRetryTimerRef.current !== null || submittedRef.current) return;
    const delay = saveRetryDelayRef.current;
    saveRetryDelayRef.current = Math.min(delay * 2, SAVE_RETRY_MAX_MS);
    saveRetryTimerRef.current = setTimeout(() => {
      saveRetryTimerRef.current = null;
      if (submittedRef.current) return;
      void flushDirtyRef.current().catch(() => undefined);
    }, delay);
  }, []);

  const cancelPendingAutosave = useCallback(() => {
    autosaveEpochRef.current += 1;
    dirtyRef.current.clear();
    clearDebounceTimer();
    clearSaveRetryTimer();
  }, [clearDebounceTimer, clearSaveRetryTimer]);

  const allowAction = useCallback((stampRef: { current: number }) => {
    const now = performance.now();
    if (now - stampRef.current < NAV_DEBOUNCE_MS) return false;
    stampRef.current = now;
    return true;
  }, []);

  const markExpiredComplete = useCallback(() => {
    setConfirmOpen(false);
    setSubmitError(null);
    if (onTimeExpired) {
      onTimeExpired();
    } else {
      // Preview / callers without a dedicated expiry handler.
      onSubmitted();
    }
  }, [onSubmitted, onTimeExpired]);

  const exitAfterTimeout = useCallback(() => {
    if (exitFiredRef.current) return;
    exitFiredRef.current = true;
    onExit();
  }, [onExit]);

  const submit = useCallback(
    async (reason: 'manual' | 'expired') => {
      // Idempotency lock: reject concurrent autoSubmit while a submit is in flight.
      if (submittedRef.current) return;
      submittedRef.current = true;
      // Drop any pending autosave so it cannot race the final submit.
      cancelPendingAutosave();
      // Freeze the countdown immediately (before the network round-trip) so a
      // near-zero tick cannot race the in-flight manual submit.
      timerStopRef.current?.();
      // For expiry, onExpire already flushSync'd timeUp + submitting. Manual
      // submit still needs the submitting overlay.
      if (reason !== 'expired') {
        setSubmitting(true);
      }
      setSubmitError(null);
      let expiredSucceeded = false;
      try {
        // Final submit carries every answer; no mid-question autosave required.
        await transport.submit({
          responses: buildResponses(test.id, answersRef.current, telemetry.elapsedFor),
          total_module_duration_seconds: telemetry.totalModuleSeconds(),
        });
        setConfirmOpen(false);
        if (reason === 'expired') {
          markExpiredComplete();
          expiredSucceeded = true;
        } else {
          onSubmitted();
        }
      } catch (err) {
        // Server already auto-submitted / expired: still a successful timeout UX.
        if (reason === 'expired' && isTerminalSubmitConflict(err)) {
          markExpiredComplete();
          expiredSucceeded = true;
        } else {
          submittedRef.current = false;
          if (isUnauthorized(err) && onUnauthorized) {
            setConfirmOpen(false);
            onUnauthorized();
          } else if (isAttemptLocked(err)) {
            setConfirmOpen(false);
            onLocked(errorMessage(err, 'Assessment already completed. Modifications are locked.'));
          } else {
            setSubmitError(
              reason === 'expired'
                ? `${errorMessage(err, 'Submit failed')}. Your saved answers are kept; retry below.`
                : errorMessage(err, 'Submit failed'),
            );
          }
        }
      } finally {
        setSubmitting(false);
        // Hold the Submitted confirmation so the overlay never flash-redirects.
        if (expiredSucceeded) {
          await new Promise<void>((resolve) => {
            window.setTimeout(resolve, TIMEOUT_AUTO_EXIT_MS);
          });
          exitAfterTimeout();
        }
      }
    },
    [
      cancelPendingAutosave,
      exitAfterTimeout,
      markExpiredComplete,
      onLocked,
      onSubmitted,
      onUnauthorized,
      telemetry,
      test.id,
      transport,
    ],
  );

  const canAutoSubmit = hasAbsoluteDeadline(test);

  const onExpire = useCallback(() => {
    // Strict guard: never auto-submit without an absolute display deadline.
    // remaining_seconds === 0 alone (untimed / pre-hydration) must not submit.
    const displayDeadline = test.expires_at;
    if (typeof displayDeadline !== 'string' || displayDeadline.length === 0) {
      return;
    }
    // Very first lines: pin the timeout overlay BEFORE awaiting submit.
    // Do not gate this on submit success — Submitting... must paint at t=0.
    setTimeUp(true);
    setSubmitting(true);
    onTimeoutStarted?.();
    cancelPendingAutosave();
    setConfirmOpen(false);
    void submit('expired');
  }, [cancelPendingAutosave, onTimeoutStarted, submit, test.expires_at]);

  // Prefer absolute expires_at + server_now on resume; fall back to integer
  // remaining_seconds only when the wall-clock fields are absent (preview).
  const hasWallClock =
    typeof test.expires_at === 'string' && test.expires_at.length > 0;
  const moduleRemaining = hasWallClock ? null : resolveRemainingSeconds(test);
  const moduleTimer = useModuleTimer({
    remainingSeconds: moduleRemaining,
    // Expire with the visible countdown — do not wait for write-grace padding.
    expireRemainingSeconds: moduleRemaining,
    // Preview timed modules may lack wall-clock fields; live auto-submit requires them.
    onExpire: hasWallClock
      ? undefined
      : canAutoSubmit || mode === 'preview'
        ? onExpire
        : undefined,
    enabled: !hasWallClock && !submitting && !timeUp,
  });
  const serverTimer = useServerTimer({
    expiresAt: hasWallClock ? test.expires_at : null,
    // Fire popup + submit when the client countdown hits 0 (display expires_at),
    // without waiting for write_expires_at grace / server polling drift.
    writeExpiresAt: hasWallClock ? test.expires_at : null,
    serverNow: test.server_now,
    rttMs: test.client_rtt_ms,
    onExpire: hasWallClock && canAutoSubmit ? onExpire : undefined,
    enabled: hasWallClock && !submitting && !timeUp,
  });
  const timer = hasWallClock ? serverTimer : moduleTimer;
  timerStopRef.current = timer.stop;

  const saveQuestion = useCallback(
    async (questionId: string) => {
      if (submittedRef.current) return;
      const epoch = autosaveEpochRef.current;
      const answer = answersRef.current[questionId];
      if (!hasContent(answer)) return;
      // Concurrent navigation/blur flushes can race for the same question;
      // keep it dirty so the in-flight save's completion (or the next flush)
      // is the single writer instead of posting duplicates.
      if (inFlightSaveRef.current.has(questionId)) {
        if (autosaveEpochRef.current === epoch) dirtyRef.current.add(questionId);
        return;
      }
      inFlightSaveRef.current.add(questionId);
      dirtyRef.current.delete(questionId);
      let failed = false;
      try {
        await transport.autosave({
          assessment_id: test.id,
          question_id: questionId,
          response: { answer },
          elapsed_seconds: telemetry.elapsedFor(questionId),
        });
        if (autosaveEpochRef.current !== epoch || submittedRef.current) return;
        // Successful save clears error-only feedback; routine saves stay silent.
        saveRetryDelayRef.current = SAVE_RETRY_BASE_MS;
        setSaveError(false);
      } catch (err) {
        if (autosaveEpochRef.current !== epoch || submittedRef.current) return;
        failed = true;
        dirtyRef.current.add(questionId);
        setSaveError(true);
        if (isTimeExpired(err)) {
          setTimeUp(true);
          void submit('expired');
        } else if (isUnauthorized(err) && onUnauthorized) {
          // Retrying with a dead token cannot succeed; the draft stays local.
          onUnauthorized();
        } else if (isAttemptLocked(err)) {
          onLocked(errorMessage(err, 'Assessment already completed. Modifications are locked.'));
        } else {
          scheduleSaveRetry();
        }
      } finally {
        inFlightSaveRef.current.delete(questionId);
        if (
          !failed &&
          autosaveEpochRef.current === epoch &&
          !submittedRef.current &&
          dirtyRef.current.has(questionId)
        ) {
          void saveQuestion(questionId);
        }
      }
    },
    [onLocked, onUnauthorized, scheduleSaveRetry, submit, telemetry, test.id, transport],
  );

  const flushDirty = useCallback(async () => {
    if (submittedRef.current) return;
    clearDebounceTimer();
    // Draft lives in localStorage; a failed save must never block navigation.
    await Promise.allSettled(Array.from(dirtyRef.current).map((id) => saveQuestion(id)));
  }, [clearDebounceTimer, saveQuestion]);
  flushDirtyRef.current = flushDirty;

  /**
   * Tab close / refresh / navigation away: send every unsaved answer with
   * ``keepalive`` so the browser finishes the request after the page is gone
   * (a normal fetch is cancelled on unload). In-flight saves are re-sent too,
   * because the browser may cancel those as well. Fire-and-forget.
   */
  const flushOnPageHide = useCallback(() => {
    if (submittedRef.current || mode !== 'live') return;
    clearDebounceTimer();
    const ids = new Set([...dirtyRef.current, ...inFlightSaveRef.current]);
    ids.forEach((questionId) => {
      const answer = answersRef.current[questionId];
      if (!hasContent(answer)) return;
      void transport
        .autosave(
          {
            assessment_id: test.id,
            question_id: questionId,
            response: { answer },
            elapsed_seconds: telemetry.elapsedFor(questionId),
          },
          { keepalive: true },
        )
        .catch(() => undefined);
    });
  }, [clearDebounceTimer, mode, telemetry, test.id, transport]);

  // Debounced answer writes + immediate flush on Next/Prev, exit, hide, reconnect.
  // Rapid clicks reset one timer so the latest answer wins as a single payload.
  const flushDirtyInBackground = useCallback(() => {
    void flushDirty().catch(() => undefined);
  }, [flushDirty]);

  const scheduleAutosave = useCallback(
    (delayMs: number) => {
      clearDebounceTimer();
      const epoch = autosaveEpochRef.current;
      debounceTimerRef.current = setTimeout(() => {
        debounceTimerRef.current = null;
        if (autosaveEpochRef.current !== epoch || submittedRef.current) return;
        flushDirtyInBackground();
      }, delayMs);
    },
    [clearDebounceTimer, flushDirtyInBackground],
  );

  useEffect(() => {
    const onOffline = () => setOffline(true);
    const onOnline = () => {
      setOffline(false);
      void flushDirty().catch(() => undefined);
    };
    const onHidden = () => {
      if (document.visibilityState === 'hidden') flushDirtyInBackground();
    };
    const onPageHide = () => flushOnPageHide();
    window.addEventListener('offline', onOffline);
    window.addEventListener('online', onOnline);
    window.addEventListener('pagehide', onPageHide);
    document.addEventListener('visibilitychange', onHidden);
    return () => {
      window.removeEventListener('offline', onOffline);
      window.removeEventListener('online', onOnline);
      window.removeEventListener('pagehide', onPageHide);
      document.removeEventListener('visibilitychange', onHidden);
    };
  }, [flushDirty, flushDirtyInBackground, flushOnPageHide]);

  // Only clear the debounce timer on unmount — not when flush callbacks change
  // identity, or a pending debounce would be cancelled before it can fire.
  useEffect(
    () => () => {
      clearDebounceTimer();
      clearSaveRetryTimer();
    },
    [clearDebounceTimer, clearSaveRetryTimer],
  );

  const handleChange = (value: AnswerValue) => {
    if (!current || timeUp) return;
    const questionId = current.id;
    setAnswers((prev) => {
      const next = { ...prev, [questionId]: value };
      onAnswersChange?.(next);
      return next;
    });
    dirtyRef.current.add(questionId);
    scheduleAutosave(autosaveDelayForType(current.type));
  };

  const go = (nextIndex: number) => {
    flushDirtyInBackground();
    setIndex(Math.max(0, Math.min(questions.length - 1, nextIndex)));
  };

  const handlePrev = () => {
    go(index - 1);
  };

  const handleNext = () => {
    if (index === questions.length - 1) {
      // Separate stamp so advance → open-confirm is never blocked.
      if (!allowAction(lastOpenConfirmAtRef)) return;
      flushDirtyInBackground();
      setConfirmOpen(true);
      return;
    }
    if (!allowAction(lastAdvanceAtRef)) return;
    go(index + 1);
  };

  const handleConfirmSubmit = () => {
    if (!allowAction(lastConfirmSubmitAtRef)) return;
    void submit('manual');
  };

  const answeredCount = useMemo(
    () => questions.filter((q) => hasContent(answers[q.id])).length,
    [answers, questions],
  );
  const allAnswered = answeredCount === questions.length && questions.length > 0;

  // Timeout overlay mounts the instant the countdown hits 0 (isTimedOut), not
  // after submit resolves. Submitting... stays visible for the whole request.
  if (timeUp) {
    const showSubmitting = submitting && !submitError;
    return (
      <div
        className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-canvas px-6 text-center"
        role="status"
        aria-live={showSubmitting ? 'assertive' : 'polite'}
        aria-label="Assessment time concluded"
      >
        <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-full border border-success/25 bg-success/15">
          <CheckCircle2 className="h-7 w-7 text-success" aria-hidden />
        </div>
        <p className="max-w-md text-base font-medium leading-relaxed text-foreground sm:text-lg">
          {ASSESSMENT_TIMEOUT_MESSAGE}
        </p>
        {showSubmitting ? (
          <div
            className="mt-8 inline-flex items-center gap-3 rounded-lg border border-border bg-surface px-5 py-3 shadow-sm"
            role="status"
            aria-label="Submitting..."
          >
            <GpuSpinner />
            <span className="text-sm font-medium text-foreground">Submitting...</span>
          </div>
        ) : submitError ? (
          <div className="mt-8 flex flex-col items-center gap-3">
            <p role="alert" className="max-w-sm text-xs text-danger">
              {submitError}
            </p>
            <button
              type="button"
              onClick={() => {
                setTimeUp(true);
                setSubmitting(true);
                void submit('expired');
              }}
              className="inline-flex h-10 items-center justify-center rounded-md border border-danger/40 bg-surface px-5 text-sm font-medium text-foreground hover:bg-danger/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              Retry submit
            </button>
          </div>
        ) : (
          <div className="mt-8 flex flex-col items-center gap-4">
            <p
              className="text-sm font-medium text-foreground"
              role="status"
              aria-label="Submitted"
            >
              Submitted
            </p>
            <button
              type="button"
              onClick={exitAfterTimeout}
              className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-5 text-sm font-medium text-primary-fg hover:bg-primary-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
            >
              Return to Dashboard
            </button>
          </div>
        )}
      </div>
    );
  }

  if (!current) return null;

  const value = answers[current.id];
  const canAdvance = isAnswered(current, value);
  const progressPct = Math.round(((index + 1) / questions.length) * 100);
  const remaining = timer.remainingSeconds;
  const tone = remaining !== null && test.duration_seconds ? timerTone(remaining, test.duration_seconds) : 'safe';
  const warning = tone === 'urgent' && remaining !== null && remaining > 0;
  // Hide the clock the moment display hits 0 / submit starts — never leave a blinking 00:00.
  const showCountdown =
    remaining !== null && remaining > 0 && !timeUp && !submitting;
  const mediaSrc = resolveAssessmentMediaUrl(current.media_url);
  const questionLabel = `Question ${index + 1} of ${questions.length}`;
  const submittingLabel = timeUp ? 'Submitting...' : 'Submitting your responses...';

  return (
    <div className="relative mx-auto w-full max-w-2xl space-y-4 py-6">
      {submitting && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-canvas/70"
          role="status"
          aria-live="assertive"
          aria-label={submittingLabel}
        >
          <div className="flex items-center gap-3 rounded-lg border border-border bg-surface px-5 py-4 shadow-sm">
            <GpuSpinner />
            <span className="text-sm font-medium text-foreground">{submittingLabel}</span>
          </div>
        </div>
      )}

      {mode === 'live' && (offline || saveError) && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground"
        >
          <WifiOff className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>Connection issue — retrying save...</span>
        </div>
      )}

      <div className="sticky top-0 z-30 -mx-1 flex items-center justify-between gap-3 rounded-lg border border-border/80 bg-canvas/95 px-2 py-2.5 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-canvas/80 sm:mx-0 sm:px-3 md:top-12 md:z-[9]">
        <button
          type="button"
          onClick={() => {
            flushDirtyInBackground();
            onExit();
          }}
          className="flex items-center rounded text-xs text-muted transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
        >
          <ChevronLeft className="mr-0.5 h-4 w-4" /> {exitLabel}
        </button>

        <div className="flex items-center gap-3 text-xs">
          {showCountdown && (
            <span
              role="timer"
              aria-live={warning ? 'assertive' : 'off'}
              aria-label="Time remaining"
              data-tone={tone}
              className={`inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 font-mono text-xl font-bold tracking-wider tabular-nums shadow-sm transition-colors duration-300 sm:text-2xl ${
                tone === 'urgent'
                  ? 'animate-pulse border-danger/50 bg-danger/15 text-danger'
                  : tone === 'caution'
                    ? 'border-warning/40 bg-warning/10 text-warning'
                    : 'border-success/40 bg-surface-raised text-success'
              }`}
            >
              <AlarmClock className="h-5 w-5 shrink-0 sm:h-6 sm:w-6" aria-hidden />
              {formatClock(remaining)}
              <span className="sr-only"> hard cutoff</span>
            </span>
          )}
          {mode === 'preview' && (
            <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 font-semibold text-warning">
              Preview - nothing is saved
            </span>
          )}
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-end justify-between gap-3">
          <span className="text-sm font-medium tabular-nums text-muted">
            Progress
          </span>
          <span className="pb-0.5 text-sm font-display font-bold tabular-nums text-muted">{progressPct}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full border border-border bg-surface-raised">
          <div className="h-full bg-primary transition-[width] duration-200 ease-out" style={{ width: `${progressPct}%` }} />
        </div>
      </div>

      <section
        className="flex min-h-[320px] flex-col rounded-lg border border-border bg-surface p-4 select-none sm:p-5"
        aria-labelledby={`q-${current.id}`}
        onCopy={blockClipboard}
        onCut={blockClipboard}
        onContextMenu={blockClipboard}
      >
        <div className="flex-1">
          {topDisclaimer && (
            <div
              role="note"
              className="mb-6 rounded-xl border border-slate-200 bg-slate-50 p-4 transition-colors dark:border-slate-800 dark:bg-slate-900/60"
            >
              <div className="flex items-start gap-3">
                <Info
                  className="mt-0.5 h-5 w-5 shrink-0 text-[#7048E2] dark:text-purple-400"
                  aria-hidden
                />
                <p className="text-sm font-medium leading-relaxed text-slate-700 dark:text-slate-300 whitespace-pre-line">
                  {topDisclaimer}
                </p>
              </div>
            </div>
          )}
          {current.show_disclaimer && current.disclaimer_text?.trim() && (
            <p
              role="note"
              className="mb-4 rounded-md border border-border bg-surface-raised px-3 py-2 text-sm leading-relaxed text-slate-600 dark:text-slate-300"
            >
              {current.disclaimer_text}
            </p>
          )}
          <h2 className="mb-2 text-lg font-semibold tabular-nums text-[#7048E2] dark:text-violet-300 sm:text-xl">
            {questionLabel}
          </h2>
          <div id={`q-${current.id}`} className="text-lg font-medium leading-relaxed text-slate-900 dark:text-slate-100">
            <MarkdownText source={current.text} />
          </div>
          {mediaSrc && (
            <figure className="mt-4 overflow-hidden rounded-md border border-border bg-canvas">
              <img
                src={mediaSrc}
                alt={`Figure for question ${index + 1}`}
                className="pointer-events-none mx-auto max-h-80 w-auto object-contain"
                draggable={false}
              />
            </figure>
          )}
          <RunnerQuestionInput question={current} value={value} disabled={timeUp || submitting} onChange={handleChange} />
        </div>

        <div className="mt-8 flex flex-col gap-2 border-t border-border pt-4">
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={handlePrev}
              disabled={index === 0 || timeUp || submitting}
              className="inline-flex h-10 items-center gap-1 rounded-md px-3 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-surface-raised hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              <ChevronLeft className="h-4 w-4" /> Previous
            </button>
            <button
              type="button"
              onClick={() => handleNext()}
              disabled={!canAdvance || timeUp || submitting}
              className="inline-flex h-10 items-center gap-1 rounded-md border-0 bg-[#7048E2] px-4 text-sm font-medium text-white shadow-none transition-colors duration-150 hover:bg-[#5e3cc4] active:bg-[#4f32a6] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#7048E2] focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-[#7048E2]"
            >
              {index === questions.length - 1 ? 'Submit test' : 'Next question'}
              {index < questions.length - 1 && <ChevronRight className="h-4 w-4" aria-hidden />}
            </button>
          </div>
          {!canAdvance && !timeUp && (
            <p className="text-right text-sm text-slate-600 dark:text-slate-300">Please answer to continue.</p>
          )}
          {test.show_confidentiality_notice && test.confidentiality_notice_text?.trim() && (
            <p
              role="note"
              className="mt-6 whitespace-pre-line text-xs text-slate-400 font-bold italic text-left leading-relaxed"
            >
              {test.confidentiality_notice_text}
            </p>
          )}
        </div>
      </section>

      {renderFooter?.({ elapsedFor: telemetry.elapsedFor, totalSeconds: telemetry.totalModuleSeconds, answers })}

      <Dialog.Root open={confirmOpen && !timeUp} onOpenChange={(open) => !submitting && setConfirmOpen(open)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-canvas/80" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface focus:outline-none">
            <div className="border-b border-border px-4 py-3">
              <Dialog.Title className="text-base font-semibold text-foreground">Submit test</Dialog.Title>
            </div>
            <div className="flex flex-col items-center px-4 py-6 text-center">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full border border-success/25 bg-success/15">
                <CheckCircle2 className="h-6 w-6 text-success" />
              </div>
              <Dialog.Description className="max-w-sm text-xs leading-relaxed text-muted">
                You answered {answeredCount} of {questions.length} questions
                {allAnswered ? ' (all complete)' : ''}. Once submitted, you cannot change your answers.
              </Dialog.Description>
              {submitError && (
                <p role="alert" className="mt-3 text-xs text-danger">
                  {submitError}
                </p>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-border bg-surface-raised/50 px-4 py-3">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                disabled={submitting}
                className="inline-flex h-9 items-center rounded-md px-3 text-sm font-medium text-muted hover:bg-surface-raised hover:text-foreground disabled:opacity-50"
              >
                Review answers
              </button>
              <button
                type="button"
                onClick={handleConfirmSubmit}
                disabled={submitting}
                aria-busy={submitting || undefined}
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-fg hover:bg-primary-hover disabled:opacity-50"
              >
                {submitting && <GpuSpinner className="h-3.5 w-3.5" />}
                {submitting ? 'Submitting your responses...' : 'Confirm submit'}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
