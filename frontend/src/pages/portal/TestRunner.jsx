import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2 } from 'lucide-react';
import Skeleton from '../../components/ui/Skeleton';
import EmptyState from '../../components/ui/EmptyState';
import Button from '../../components/ui/Button';
import { api } from '../../api/client';
import { readDraft, writeDraft, clearDraft, mergeAnswers } from '../../lib/assessment-draft';
import { AssessmentRunner } from '../../features/assessment-runner/assessment-runner';
import { useToast } from '../../components/ui/useToast';
import { candidateTestKey, cachedQuery, invalidateQuery, peekQuery } from '../../lib/query-cache';
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
  const [phase, setPhase] = useState('running'); // running | complete | expired

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
          // Bust caches off the critical path so the submit spinner stays fluid.
          deferWork(() => {
            invalidateQuery(CANDIDATE_DASHBOARD_KEY);
            invalidateQuery(cacheKey);
          });
        }
      },
    }),
    [testId, candidateId, cacheKey],
  );

  const onAnswersChange = useCallback(
    (next) => writeDraft(candidateId, testId, next),
    [candidateId, testId],
  );

  const backToDashboard = useCallback(() => {
    invalidateQuery(CANDIDATE_DASHBOARD_KEY);
    navigate('/portal/dashboard');
  }, [navigate]);

  const onSubmitted = useCallback(() => {
    setPhase('complete');
    deferWork(() => invalidateQuery(CANDIDATE_DASHBOARD_KEY));
  }, []);

  const onTimeExpired = useCallback(() => {
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

  if (phase === 'complete' || phase === 'expired') {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center py-16 text-center">
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full border border-success/25 bg-success/15">
          <CheckCircle2 className="h-7 w-7 text-success" aria-hidden />
        </div>
        <h1 className="text-lg font-semibold text-foreground">
          {phase === 'expired' ? 'Time is up — answers submitted' : 'Assessment submitted'}
        </h1>
        <p className="mt-2 text-sm text-muted">
          {phase === 'expired'
            ? 'Your saved answers were locked when the timer ended.'
            : 'Your responses are saved. You can return to the dashboard to continue other modules.'}
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

  return (
    <AssessmentRunner
      test={test}
      mode="live"
      initialAnswers={initialAnswers}
      transport={transport}
      onAnswersChange={onAnswersChange}
      onSubmitted={onSubmitted}
      onTimeExpired={onTimeExpired}
      onLocked={setLockDetail}
      onExit={backToDashboard}
    />
  );
}
