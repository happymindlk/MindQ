import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2 } from 'lucide-react';
import Skeleton from '../../components/ui/Skeleton';
import EmptyState from '../../components/ui/EmptyState';
import Button from '../../components/ui/Button';
import { api } from '../../api/client';
import { readDraft, writeDraft, clearDraft, mergeAnswers } from '../../lib/assessment-draft';
import { AssessmentRunner } from '../../features/assessment-runner/assessment-runner';
import { ModuleReadyScreen } from '../../features/assessment-runner/module-ready-screen';
import PackageCompleteScreen from '../../features/candidate-dashboard/package-complete-screen';
import { useToast } from '../../components/ui/useToast';
import { candidateTestKey, cachedQuery, invalidateQuery, peekQuery, setQuery } from '../../lib/query-cache';
import { CANDIDATE_DASHBOARD_KEY } from '../../features/candidate-dashboard/module-status';

const LOCKED_DETAIL = 'Assessment already completed. Modifications are locked.';
const TEST_STALE_MS = 60000;

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
 * Live candidate module runner with an explicit ready gate.
 * GET loads questions without starting; POST /start arms the timer.
 */
export default function TestRunner() {
  const { testId } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const candidateId = typeof window !== 'undefined' ? localStorage.getItem('candidateId') : null;
  const cacheKey = candidateTestKey(testId);

  const cached = typeof testId === 'string' ? peekQuery(cacheKey) : undefined;
  const [test, setTest] = useState(() => (cached && typeof cached === 'object' ? cached : null));
  const [initialAnswers, setInitialAnswers] = useState(() => {
    if (!cached || typeof cached !== 'object') return {};
    return mergeAnswers(cached.answers || {}, readDraft(candidateId, testId));
  });
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
  const [phase, setPhase] = useState(() =>
    cached && typeof cached === 'object' && cached.started_at ? 'running' : 'instructions',
  );
  const exitHandledRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    async function loadTest() {
      if (!testId) return;
      try {
        const data = await cachedQuery(cacheKey, () => api.candidate.getTest(testId), {
          staleTime: TEST_STALE_MS,
        });
        if (cancelled) return;
        setInitialAnswers(mergeAnswers(data.answers || {}, readDraft(candidateId, testId)));
        setTest(data);
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
          // Bust caches off the critical path so navigation stays fluid.
          deferWork(() => {
            invalidateQuery(CANDIDATE_DASHBOARD_KEY);
            invalidateQuery(cacheKey);
          });
          exitHandledRef.current = true;
          if (result.package_complete) {
            setPhase('package_complete');
          } else {
            // Return to the dashboard immediately; statuses refetch in the background.
            navigate('/portal/dashboard', { replace: true });
          }
        }
        return result;
      },
    }),
    [testId, candidateId, cacheKey, navigate],
  );

  const onAnswersChange = useCallback(
    (next) => writeDraft(candidateId, testId, next),
    [candidateId, testId],
  );

  const backToDashboard = useCallback(() => {
    deferWork(() => invalidateQuery(CANDIDATE_DASHBOARD_KEY));
    navigate('/portal/dashboard');
  }, [navigate]);

  const beginModule = useCallback(async () => {
    if (!testId || starting) return;
    setStarting(true);
    setStartError(null);
    try {
      const started = await api.candidate.startTest(testId);
      const next = {
        ...test,
        started_at: started.started_at || new Date().toISOString(),
      };
      // #region agent log
      fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'5f236f'},body:JSON.stringify({sessionId:'5f236f',runId:'pre-fix',hypothesisId:'E',location:'TestRunner.jsx:beginModule',message:'startTest response applied',data:{testId,status:started.status,started_at_raw:started.started_at,started_at_used:next.started_at,started_at_parsed:Date.parse(next.started_at),duration_seconds:next.duration_seconds,clientNowIso:new Date().toISOString(),tzOffsetMinutes:new Date().getTimezoneOffset()},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      setTest(next);
      setQuery(cacheKey, next);
      setPhase('running');
      deferWork(() => invalidateQuery(CANDIDATE_DASHBOARD_KEY));
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
    // transport.submit already navigated or showed package-complete.
    if (exitHandledRef.current) {
      deferWork(() => {
        toast({
          title: 'Time expired',
          description:
            'Your time for this test has ended. Your answers were automatically submitted.',
          variant: 'warning',
          duration: 6000,
        });
      });
      return;
    }
    setPhase('expired');
    deferWork(() => {
      invalidateQuery(CANDIDATE_DASHBOARD_KEY);
      toast({
        title: 'Time expired',
        description: 'Your time for this test has ended. Your answers were automatically submitted.',
        variant: 'warning',
        duration: 6000,
      });
    });
  }, [toast]);

  if (isLoading && !test) {
    return (
      <div className="w-full max-w-2xl mx-auto py-6 space-y-4" role="status" aria-label="Loading test">
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
      <div className="mx-auto flex w-full max-w-md flex-col items-center py-16 text-center">
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full border border-success/25 bg-success/15">
          <CheckCircle2 className="h-7 w-7 text-success" aria-hidden />
        </div>
        <h1 className="text-lg font-semibold text-foreground">Time is up — answers submitted</h1>
        <p className="mt-2 text-sm text-muted">
          Your saved answers were locked when the timer ended.
        </p>
        <Button variant="primary" size="sm" className="mt-6" onClick={backToDashboard}>
          Back to dashboard
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

  return (
    <AssessmentRunner
      test={test}
      mode="live"
      initialAnswers={initialAnswers}
      transport={transport}
      onAnswersChange={onAnswersChange}
      onSubmitted={() => undefined}
      onTimeExpired={onTimeExpired}
      onLocked={setLockDetail}
      onExit={backToDashboard}
    />
  );
}
