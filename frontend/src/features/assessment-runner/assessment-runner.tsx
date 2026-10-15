import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { AlarmClock, CheckCircle2, ChevronLeft, ChevronRight, Cloud, Loader2, Timer } from 'lucide-react';
import type { RunnerTest } from '../assessment-builder/api/library-api';
import { MarkdownText } from '../assessment-builder/components/markdown-preview';
import type { AnswerValue, ResponseSavePayload, ResponseSubmitPayload } from '../assessment-builder/types/telemetry';
import { RunnerQuestionInput } from './runner-question-input';
import { buildResponses, hasContent, isAnswered, isAttemptLocked, isTimeExpired } from './runner-logic';
import { formatClock, timerTone, useModuleTimer } from './use-module-timer';
import { useQuestionTelemetry } from './use-question-telemetry';

export interface RunnerTransport {
  autosave: (payload: ResponseSavePayload) => Promise<void>;
  submit: (body: ResponseSubmitPayload) => Promise<void>;
}

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

interface AssessmentRunnerProps {
  test: RunnerTest;
  mode: 'live' | 'preview';
  initialAnswers: Record<string, AnswerValue>;
  transport: RunnerTransport;
  onAnswersChange?: (answers: Record<string, AnswerValue>) => void;
  onSubmitted: () => void;
  onLocked: (message: string) => void;
  onExit: () => void;
  exitLabel?: string;
  /** Rendered under the card; preview mode uses it for the telemetry strip. */
  renderFooter?: (api: { elapsedFor: (id: string) => number; totalSeconds: () => number; answers: Record<string, AnswerValue> }) => ReactNode;
}

const AUTOSAVE_DELAY_MS = 2000;
const WARNING_SECONDS = 60;

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
  onLocked,
  onExit,
  exitLabel = 'Back to dashboard',
  renderFooter,
}: AssessmentRunnerProps) {
  const questions = test.questions;
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>(initialAnswers);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [timeUp, setTimeUp] = useState(false);

  const current = questions[index];
  const telemetry = useQuestionTelemetry(current?.id ?? null);
  const answersRef = useRef(answers);
  answersRef.current = answers;
  const dirtyRef = useRef<Set<string>>(new Set());
  const debounceRef = useRef<number | null>(null);
  const submittedRef = useRef(false);

  const submit = useCallback(
    async (reason: 'manual' | 'expired') => {
      if (submittedRef.current) return;
      submittedRef.current = true;
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
      setSubmitting(true);
      setSubmitError(null);
      try {
        await transport.submit({
          responses: buildResponses(test.id, answersRef.current, telemetry.elapsedFor),
          total_module_duration_seconds: telemetry.totalModuleSeconds(),
        });
        setConfirmOpen(false);
        onSubmitted();
      } catch (err) {
        submittedRef.current = false;
        if (isAttemptLocked(err)) {
          setConfirmOpen(false);
          onLocked(errorMessage(err, 'Assessment already completed. Modifications are locked.'));
          return;
        }
        setSubmitError(
          reason === 'expired'
            ? `${errorMessage(err, 'Submit failed')}. Your saved answers are kept; retry below.`
            : errorMessage(err, 'Submit failed'),
        );
      } finally {
        setSubmitting(false);
      }
    },
    [onLocked, onSubmitted, telemetry, test.id, transport],
  );

  const onExpire = useCallback(() => {
    setTimeUp(true);
    void submit('expired');
  }, [submit]);

  const timer = useModuleTimer({
    durationSeconds: test.duration_seconds,
    timerMode: test.timer_mode,
    startedAt: test.started_at,
    onExpire,
    enabled: !timeUp,
  });

  const saveQuestion = useCallback(
    async (questionId: string) => {
      const answer = answersRef.current[questionId];
      if (!hasContent(answer)) return;
      dirtyRef.current.delete(questionId);
      setSaveStatus('saving');
      try {
        await transport.autosave({
          assessment_id: test.id,
          question_id: questionId,
          response: { answer },
          elapsed_seconds: telemetry.elapsedFor(questionId),
        });
        setSaveStatus('saved');
      } catch (err) {
        dirtyRef.current.add(questionId);
        setSaveStatus('error');
        if (isTimeExpired(err)) {
          setTimeUp(true);
          void submit('expired');
        } else if (isAttemptLocked(err)) {
          onLocked(errorMessage(err, 'Assessment already completed. Modifications are locked.'));
        }
      }
    },
    [onLocked, submit, telemetry, test.id, transport],
  );

  const flushDirty = useCallback(async () => {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    // Draft lives in localStorage; a failed save must never block navigation.
    await Promise.allSettled(Array.from(dirtyRef.current).map((id) => saveQuestion(id)));
  }, [saveQuestion]);

  useEffect(
    () => () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    },
    [],
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
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      void saveQuestion(questionId);
    }, AUTOSAVE_DELAY_MS);
  };

  const go = async (nextIndex: number) => {
    await flushDirty();
    setIndex(Math.max(0, Math.min(questions.length - 1, nextIndex)));
  };

  const handleNext = async () => {
    if (index === questions.length - 1) {
      await flushDirty();
      setConfirmOpen(true);
      return;
    }
    await go(index + 1);
  };

  const answeredCount = useMemo(
    () => questions.filter((q) => hasContent(answers[q.id])).length,
    [answers, questions],
  );

  if (!current) return null;

  const value = answers[current.id];
  const canAdvance = isAnswered(current, value);
  const progressPct = Math.round(((index + 1) / questions.length) * 100);
  const remaining = timer.remainingSeconds;
  const strict = test.timer_mode === 'strict';
  const warning = remaining !== null && remaining <= WARNING_SECONDS && remaining > 0;
  const tone = remaining !== null && test.duration_seconds ? timerTone(remaining, test.duration_seconds) : 'safe';

  return (
    <div className="mx-auto w-full max-w-2xl space-y-4 py-6">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => void flushDirty().then(onExit)}
          className="flex items-center rounded text-xs text-muted transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
        >
          <ChevronLeft className="mr-0.5 h-4 w-4" /> {exitLabel}
        </button>

        <div className="flex items-center gap-3 text-xs">
          {remaining !== null && (
            <span
              role="timer"
              aria-live={warning ? 'assertive' : 'off'}
              aria-label={strict ? 'Time remaining' : 'Suggested time remaining'}
              data-tone={tone}
              className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-mono text-sm tabular-nums transition-colors duration-300 ${
                tone === 'urgent'
                  ? 'border-danger/50 bg-danger/15 font-semibold text-danger'
                  : 'border-success/40 bg-success/10 font-medium text-success'
              }`}
            >
              {strict ? <AlarmClock className="h-3.5 w-3.5" aria-hidden /> : <Timer className="h-3.5 w-3.5" aria-hidden />}
              {timer.overtime ? `+${formatClock(-remaining)}` : formatClock(Math.max(0, remaining))}
              {strict && <span className="sr-only"> strict timer</span>}
            </span>
          )}
          {mode === 'live' ? (
            <span className="flex items-center gap-1.5 text-muted" aria-live="polite">
              <Cloud className="h-3.5 w-3.5" aria-hidden />
              {saveStatus === 'saving' ? (
                <span className="text-warning">Saving…</span>
              ) : saveStatus === 'saved' ? (
                <span className="text-success">Saved</span>
              ) : saveStatus === 'error' ? (
                <span className="text-danger">Saved offline</span>
              ) : (
                <span>Ready</span>
              )}
            </span>
          ) : (
            <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 font-semibold text-warning">
              Preview — nothing is saved
            </span>
          )}
        </div>
      </div>

      <div>
        <div className="mb-1.5 flex justify-between text-xs text-muted">
          <span className="tabular-nums">
            Question {index + 1} of {questions.length}
          </span>
          <span className="tabular-nums">{progressPct}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full border border-border bg-surface-raised">
          <div className="h-full bg-primary transition-[width] duration-200 ease-out" style={{ width: `${progressPct}%` }} />
        </div>
      </div>

      <section className="flex min-h-[320px] flex-col rounded-lg border border-border bg-surface p-4 sm:p-5" aria-labelledby={`q-${current.id}`}>
        <div className="flex-1">
          <div id={`q-${current.id}`} className="text-lg font-medium leading-relaxed text-slate-900 dark:text-slate-100">
            <MarkdownText source={current.text} />
          </div>
          {current.media_url && (
            <figure className="mt-4 overflow-hidden rounded-md border border-border bg-canvas">
              <img
                src={current.media_url}
                alt={`Figure for question ${index + 1}`}
                className="mx-auto max-h-80 w-auto object-contain"
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
              onClick={() => void go(index - 1)}
              disabled={index === 0 || timeUp}
              className="inline-flex h-10 items-center gap-1 rounded-md px-3 text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-surface-raised hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              <ChevronLeft className="h-4 w-4" /> Previous
            </button>
            <button
              type="button"
              onClick={() => void handleNext()}
              disabled={!canAdvance || timeUp}
              className="inline-flex h-10 items-center gap-1 rounded-md bg-primary px-4 text-sm font-medium text-primary-fg hover:bg-primary-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:cursor-not-allowed disabled:opacity-50"
            >
              {index === questions.length - 1 ? 'Submit test' : 'Next question'}
              {index < questions.length - 1 && <ChevronRight className="h-4 w-4" />}
            </button>
          </div>
          {!canAdvance && !timeUp && (
            <p className="text-right text-sm text-slate-600 dark:text-slate-300">Please answer to continue.</p>
          )}
        </div>
      </section>

      {renderFooter?.({ elapsedFor: telemetry.elapsedFor, totalSeconds: telemetry.totalModuleSeconds, answers })}

      {timeUp && (
        <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm text-foreground">
          <p className="flex items-center gap-2 font-semibold">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <AlarmClock className="h-4 w-4" aria-hidden />}
            Time is up. {submitting ? 'Submitting your saved answers…' : 'Your answers have been locked.'}
          </p>
          {submitError && (
            <div className="mt-2 flex items-center justify-between gap-2 text-xs text-danger">
              <span>{submitError}</span>
              <button
                type="button"
                onClick={() => void submit('expired')}
                className="rounded-md border border-danger/40 px-2 py-1 font-semibold hover:bg-danger/10"
              >
                Retry submit
              </button>
            </div>
          )}
        </div>
      )}

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
                You answered {answeredCount} of {questions.length} questions. Once submitted, you cannot change your answers.
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
                onClick={() => void submit('manual')}
                disabled={submitting}
                aria-busy={submitting || undefined}
                className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-fg hover:bg-primary-hover disabled:opacity-50"
              >
                {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                Confirm submit
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
