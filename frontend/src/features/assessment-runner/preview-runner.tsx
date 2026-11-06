import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, CheckCircle2, Loader2, RotateCcw } from 'lucide-react';
import type { RunnerTest } from '../assessment-builder/api/library-api';
import { PREVIEW_CONFIG, PREVIEW_READY, readPreviewMessage } from '../assessment-builder/lib/preview-protocol';
import type { PreviewReadyMessage } from '../assessment-builder/lib/preview-protocol';
import type { AnswerValue } from '../assessment-builder/types/telemetry';
import { AssessmentRunner } from './assessment-runner';
import type { RunnerTransport } from './assessment-runner';
import { ModuleReadyScreen } from './module-ready-screen';
import { formatClock } from './use-module-timer';

type PreviewPhase =
  | { status: 'standalone' }
  | { status: 'waiting' }
  | { status: 'ready'; title: string; tests: RunnerTest[]; index: number; run: number }
  | { status: 'running'; title: string; tests: RunnerTest[]; index: number; run: number; startedAt: string }
  | { status: 'done'; title: string; tests: RunnerTest[]; run: number };

const NO_OP_TRANSPORT: RunnerTransport = {
  autosave: async () => undefined,
  submit: async () => undefined,
};

const EMPTY_ANSWERS: Record<string, AnswerValue> = {};

function TelemetryStrip({
  test,
  elapsedFor,
  totalSeconds,
}: {
  test: RunnerTest;
  elapsedFor: (id: string) => number;
  totalSeconds: () => number;
}) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <aside aria-label="Telemetry debug" className="rounded-lg border border-dashed border-border bg-surface-raised/60 p-3 text-xs">
      <p className="mb-2 flex items-center gap-1.5 font-semibold text-foreground">
        <Activity className="h-3.5 w-3.5" aria-hidden /> Telemetry (preview only)
        <span className="ml-auto font-mono tabular-nums text-muted">module {formatClock(Math.floor(totalSeconds()))}</span>
      </p>
      <ol className="grid grid-cols-4 gap-1 sm:grid-cols-6">
        {test.questions.map((q, i) => (
          <li key={q.id} className="rounded border border-border px-1.5 py-1 font-mono tabular-nums text-muted">
            Q{i + 1} {elapsedFor(q.id).toFixed(1)}s
          </li>
        ))}
      </ol>
    </aside>
  );
}

/**
 * Candidate runner fed by the Suite Builder over same-origin postMessage.
 * It performs no API calls, so preview answers and telemetry never persist.
 */
export function PreviewRunner() {
  const [phase, setPhase] = useState<PreviewPhase>(() =>
    typeof window !== 'undefined' && window.parent !== window ? { status: 'waiting' } : { status: 'standalone' },
  );

  const standalone = phase.status === 'standalone';

  useEffect(() => {
    if (standalone) return undefined;
    const onMessage = (event: MessageEvent) => {
      const message = readPreviewMessage(event, window.parent);
      if (message?.type !== PREVIEW_CONFIG) return;
      const tests = message.tests.filter((t) => Array.isArray(t.questions) && t.questions.length > 0);
      setPhase((prev) => ({
        status: 'ready',
        title: message.packageTitle,
        tests,
        index: 0,
        run: 'run' in prev ? prev.run + 1 : 0,
      }));
    };
    window.addEventListener('message', onMessage);
    const ready: PreviewReadyMessage = { type: PREVIEW_READY };
    window.parent.postMessage(ready, window.location.origin);
    return () => window.removeEventListener('message', onMessage);
  }, [standalone]);

  const beginModule = useCallback(() => {
    setPhase((prev) =>
      prev.status === 'ready'
        ? {
            status: 'running',
            title: prev.title,
            tests: prev.tests,
            index: prev.index,
            run: prev.run,
            startedAt: new Date().toISOString(),
          }
        : prev,
    );
  }, []);

  const advance = useCallback(() => {
    setPhase((prev) => {
      if (prev.status !== 'running') return prev;
      if (prev.index + 1 >= prev.tests.length) {
        return { status: 'done', title: prev.title, tests: prev.tests, run: prev.run };
      }
      return {
        status: 'ready',
        title: prev.title,
        tests: prev.tests,
        index: prev.index + 1,
        run: prev.run,
      };
    });
  }, []);

  const restart = useCallback(() => {
    setPhase((prev) =>
      prev.status === 'running' || prev.status === 'done' || prev.status === 'ready'
        ? { status: 'ready', title: prev.title, tests: prev.tests, index: 0, run: prev.run + 1 }
        : prev,
    );
  }, []);

  const current =
    phase.status === 'running' || phase.status === 'ready' ? phase.tests[phase.index] : undefined;
  const header = useMemo(() => {
    if (phase.status !== 'running' && phase.status !== 'ready') return null;
    return (
      <div className="mx-auto flex w-full max-w-2xl items-center justify-between gap-2 pt-4 text-xs text-muted">
        <span className="truncate font-semibold text-foreground">{phase.title}</span>
        <span className="font-mono tabular-nums">
          Module {phase.index + 1} / {phase.tests.length}
          {current ? ` · ${current.title}` : ''}
        </span>
      </div>
    );
  }, [current, phase]);

  const banner = (
    <div
      role="status"
      className="sticky top-0 z-20 border-b border-amber-500/40 bg-amber-500/15 px-3 py-2 text-center text-xs font-medium text-amber-950 dark:text-amber-100"
    >
      Preview Mode — Responses and timers are not recorded
    </div>
  );

  if (phase.status === 'standalone') {
    return (
      <div className="w-full">
        {banner}
        <div className="mx-auto max-w-md py-16 text-center text-sm text-muted">
          Preview mode is only available from the Suite Builder&apos;s Live Preview panel.
        </div>
      </div>
    );
  }

  if (phase.status === 'waiting') {
    return (
      <div className="w-full">
        {banner}
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Waiting for preview configuration…
        </div>
      </div>
    );
  }

  if (phase.status === 'done' || !current) {
    return (
      <div className="w-full">
        {banner}
        <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
          <CheckCircle2 className="h-8 w-8 text-success" aria-hidden />
          <p className="text-sm font-semibold text-foreground">Preview complete</p>
          <p className="text-xs text-muted">Candidates would now return to their dashboard. Nothing was saved.</p>
          <button
            type="button"
            onClick={restart}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-medium text-foreground hover:bg-surface-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Restart preview
          </button>
        </div>
      </div>
    );
  }

  if (phase.status === 'ready' && current) {
    return (
      <div className="w-full">
        {banner}
        {header}
        <ModuleReadyScreen
          title={current.title}
          description={current.description}
          durationSeconds={current.duration_seconds}
          onBegin={beginModule}
        />
      </div>
    );
  }

  if (phase.status !== 'running' || !current) return null;

  return (
    <div className="w-full">
      {banner}
      {header}
      <AssessmentRunner
        key={`${phase.run}-${current.id}-${phase.startedAt}`}
        test={{ ...current, started_at: phase.startedAt }}
        mode="preview"
        initialAnswers={EMPTY_ANSWERS}
        transport={NO_OP_TRANSPORT}
        onSubmitted={advance}
        onLocked={advance}
        onExit={restart}
        exitLabel="Restart preview"
        renderFooter={({ elapsedFor, totalSeconds }) => (
          <TelemetryStrip test={current} elapsedFor={elapsedFor} totalSeconds={totalSeconds} />
        )}
      />
    </div>
  );
}
