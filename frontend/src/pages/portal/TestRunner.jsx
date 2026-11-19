import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2 } from 'lucide-react';
import Skeleton from '../../components/ui/Skeleton';
import EmptyState from '../../components/ui/EmptyState';
import Button from '../../components/ui/Button';
import { api } from '../../api/client';
import { readDraft, writeDraft, clearDraft, mergeAnswers } from '../../lib/assessment-draft';
import {
  ASSESSMENT_TIMEOUT_MESSAGE,
  AssessmentRunner,
} from '../../features/assessment-runner/assessment-runner';
import { ModuleReadyScreen } from '../../features/assessment-runner/module-ready-screen';
import PackageCompleteScreen from '../../features/candidate-dashboard/package-complete-screen';
import { candidateTestKey, cachedQuery, invalidateQuery, peekQuery, setQuery } from '../../lib/query-cache';
import {
  patchCandidateDashboardModule,
  remainingSecondsFromExpiry,
} from '../../features/candidate-dashboard/dashboard-cache';
import { CANDIDATE_DASHBOARD_KEY } from '../../features/candidate-dashboard/module-status';

const LOCKED_DETAIL = 'Assessment already completed. Modifications are locked.';

function isAssessmentLocked(err) {
  return (err?.status === 409 && err?.code !== 'TIME_EXPIRED') || err?.message === LOCKED_DETAIL;
}

function deferWork(work) {
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    window.requestAnimationFrame(() => {
      window.setTimeout(work, 0);
    });
    return;
  }
  work();
}

/**
 * Sync the dashboard card for this module before routing so remount paints
 * the correct status/countdown with no full-screen spinner.
 *
 * @param {string} assessmentId
 * @param {'in_progress' | 'completed'} status
 * @param {Record<string, unknown> | null | undefined} test
 */
function syncDashboardModule(assessmentId, status, test) {
  if (!assessmentId || !test) return;
  const serverNow = new Date().toISOString();
  const expiresAt =
    typeof test.expires_at === 'string' && test.expires_at.length > 0 ? test.expires_at : null;
  const startedAt =
    typeof test.started_at === 'string' && test.started_at.length > 0 ? test.started_at : null;
  patchCandidateDashboardModule(assessmentId, {
    status,
    started_at: startedAt,
    expires_at: expiresAt,
    server_now: serverNow,
    remaining_seconds:
      status === 'completed' ? 0 : remainingSecondsFromExpiry(expiresAt, serverNow),
  });
}

/**
 * Live candidate module runner with an explicit ready gate.
 * GET loads questions without starting; POST /start arms the timer.
 */
export default function TestRunner() {
  const { testId } = useParams();
  const navigate = useNavigate();
  const candidateId = typeof window !== 'undefined' ? localStorage.getItem('candidateId') : null;
  const cacheKey = candidateTestKey(testId);

  // A cached payload only paints the instruction screen. Started attempts wait
  // for a fresh GET because a cached remaining_seconds is already stale.
  const peeked = typeof testId === 'string' ? peekQuery(cacheKey) : undefined;
  const cached = peeked && typeof peeked === 'object' && !peeked.started_at ? peeked : null;
  const [test, setTest] = useState(cached);
  const [initialAnswers, setInitialAnswers] = useState(() =>
    cached ? mergeAnswers(cached.answers || {}, readDraft(candidateId, testId)) : {},
  );
  const [isLoading, setIsLoading] = useState(() => !cached);
  const [lockDetail, setLockDetail] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [startError, setStartError] = useState(null);
  const [starting, setStarting] = useState(false);
  const [companyName, setCompanyName] = useState(() => {
    const dash = peekQuery(CANDIDATE_DASHBOARD_KEY);
    return dash && typeof dash === 'object' ? dash.company_name || '' : '';
  });
  // instructions | running | package_complete | expired
  const [phase, setPhase] = useState('instructions');
  const exitHandledRef = useRef(false);
  const startedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    async function loadTest() {
      if (!testId) return;
      try {
        // Always force a network GET: a cached POST /start payload keeps the
        // original server_now / remaining_seconds and would inflate the wall-clock
        // timer back to full duration on leave/re-enter.
        const data = await cachedQuery(cacheKey, () => api.candidate.getTest(testId), {
          force: true,
        });
        // A Start click that resolved first already holds the authoritative timer seed.
        if (cancelled || startedRef.current) return;
        setInitialAnswers(mergeAnswers(data.answers || {}, readDraft(candidateId, testId)));
        setTest(data);
        // Already-started attempts skip the instruction gate and resume in-place.
        setPhase(data.started_at ? 'running' : 'instructions');
        setLoadError(null);
        setLockDetail(null);
      } catch (err) {
        if (cancelled) return;
        const detail = err.message || '';
        if (isAssessmentLocked(err)) {
          setLockDetail(detail || LOCKED_DETAIL);
        } else if (!peekQuery(cacheKey)) {
          setLoadError(detail || 'Failed to load test questions');
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void loadTest();
    return () => {
      cancelled = true;
    };
  }, [testId, candidateId, cacheKey]);

  const transport = useMemo(
    () => ({
      autosave: async (payload) => {
        await api.candidate.autosave(payload);
      },
      submit: async ({ responses, total_module_duration_seconds }) => {
        const result = await api.candidate.submitTest(
          testId,
          responses,
          total_module_duration_seconds ?? null,
        );
        if (result.status === 200) {
          clearDraft(candidateId, testId);
          if (result.company_name) setCompanyName(result.company_name);
          // Optimistic completed card — navigation is owned by onSubmitted /
          // the runner timeout screen so expire UX is not interrupted.
          syncDashboardModule(testId, 'completed', test);
          deferWork(() => invalidateQuery(cacheKey));
          exitHandledRef.current = true;
          if (result.package_complete) {
            setPhase('package_complete');
          }
        }
        return result;
      },
    }),
    [testId, candidateId, cacheKey, test],
  );

  const onAnswersChange = useCallback(
    (next) => writeDraft(candidateId, testId, next),
    [candidateId, testId],
  );

  const backToDashboard = useCallback(() => {
    // Instant route change; autosave flush is already fire-and-forget in the runner.
    if (test?.started_at) {
      syncDashboardModule(testId, 'in_progress', test);
    }
    navigate('/portal/dashboard');
  }, [navigate, test, testId]);

  const beginModule = useCallback(async () => {
    if (!testId || starting) return;
    setStarting(true);
    setStartError(null);
    try {
      const started = await api.candidate.startTest(testId);
      const next = {
        ...test,
        started_at: started.started_at,
        expires_at: started.expires_at ?? test.expires_at,
        write_expires_at: started.write_expires_at ?? test.write_expires_at,
        server_now: started.server_now ?? test.server_now,
        remaining_seconds: started.remaining_seconds,
        write_remaining_seconds: started.write_remaining_seconds,
      };
      startedRef.current = true;
      setTest(next);
      setQuery(cacheKey, next);
      setPhase('running');
      // Keep dashboard cache warm with in_progress timing (do not wipe it).
      syncDashboardModule(testId, 'in_progress', next);
    } catch (err) {
      if (isAssessmentLocked(err)) {
        setLockDetail(err.message || LOCKED_DETAIL);
        return;
      }
      setStartError(err.message || 'Could not start this assessment. Please try again.');
    } finally {
      setStarting(false);
    }
  }, [testId, starting, test, cacheKey]);

  const onTimeExpired = useCallback(() => {
    // AssessmentRunner owns the full-screen timeout UI after a successful
    // expiry submit. Keep the runner mounted; only fall back to the portal
    // expired phase when submit never completed (exitHandled still false).
    if (exitHandledRef.current) return;
    setPhase('expired');
    syncDashboardModule(testId, 'completed', test);
  }, [testId, test]);

  if (isLoading && !test) {
    return (
      <div
        className="w-full max-w-2xl mx-auto py-6 space-y-4"
        role="status"
        aria-label="Opening assessment"
        aria-busy="true"
      >
        <p className="text-sm font-medium text-muted">Opening assessment…</p>
        <Skeleton className="h-4 w-40 animate-pulse" />
        <Skeleton className="h-2 w-full animate-pulse" />
        <Skeleton className="h-64 w-full animate-pulse" />
      </div>
    );
  }

  if (lockDetail) {
    return (
      <div className="max-w-md mx-auto py-10">
        <EmptyState
          icon={CheckCircle2}
          title="Answers locked"
          description={lockDetail}
          actionLabel="Back to dashboard"
          onAction={backToDashboard}
        />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="max-w-md mx-auto py-10">
        <EmptyState
          title="Unable to open test"
          description={loadError}
          actionLabel="Back to dashboard"
          onAction={backToDashboard}
        />
      </div>
    );
  }

  if (phase === 'package_complete') {
    return <PackageCompleteScreen companyName={companyName} />;
  }

  if (phase === 'expired') {
    return (
      <div
        className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-canvas px-6 text-center"
        role="status"
        aria-live="polite"
        aria-label="Assessment time concluded"
      >
        <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-full border border-success/25 bg-success/15">
          <CheckCircle2 className="h-7 w-7 text-success" aria-hidden />
        </div>
        <p className="max-w-md text-base font-medium leading-relaxed text-foreground sm:text-lg">
          {ASSESSMENT_TIMEOUT_MESSAGE}
        </p>
        <Button variant="primary" size="sm" className="mt-8" onClick={backToDashboard}>
          Return to Dashboard
        </Button>
      </div>
    );
  }

  if (!test || (test.questions || []).length === 0) {
    return (
      <div className="max-w-md mx-auto py-10">
        <EmptyState
          title="No questions found"
          description="This test section doesn't have any questions configured."
          actionLabel="Back to dashboard"
          onAction={backToDashboard}
        />
      </div>
    );
  }

  if (phase === 'instructions') {
    return (
      <ModuleReadyScreen
        title={test.title}
        description={test.description}
        durationSeconds={test.duration_seconds}
        onBegin={() => void beginModule()}
        busy={starting}
        error={startError}
        onExit={backToDashboard}
      />
    );
  }

  // Remount when authoritative timing arrives so the countdown never inherits a
  // stale full-duration deadline from a prior visit or cached /start payload.
  const runnerKey = [
    test.id,
    test.started_at ?? 'idle',
    test.expires_at ?? '',
    test.server_now ?? '',
    String(test.remaining_seconds ?? ''),
  ].join(':');

  return (
    <AssessmentRunner
      key={runnerKey}
      test={test}
      mode="live"
      initialAnswers={initialAnswers}
      transport={transport}
      onAnswersChange={onAnswersChange}
      onSubmitted={() => {
        if (exitHandledRef.current) {
          navigate('/portal/dashboard', { replace: true });
        }
      }}
      onTimeExpired={onTimeExpired}
      onLocked={setLockDetail}
      onExit={backToDashboard}
    />
  );
}
