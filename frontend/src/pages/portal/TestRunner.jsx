import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2 } from 'lucide-react';
import Skeleton from '../../components/ui/Skeleton';
import EmptyState from '../../components/ui/EmptyState';
import { api } from '../../api/client';
import { readDraft, writeDraft, clearDraft, mergeAnswers } from '../../lib/assessment-draft';
import { AssessmentRunner } from '../../features/assessment-runner/assessment-runner';

const LOCKED_DETAIL = 'Assessment already completed. Modifications are locked.';

function isAssessmentLocked(err) {
  return (err?.status === 409 && err?.code !== 'TIME_EXPIRED') || err?.message === LOCKED_DETAIL;
}

export default function TestRunner() {
  const { testId } = useParams();
  const navigate = useNavigate();
  const candidateId = typeof window !== 'undefined' ? localStorage.getItem('candidateId') : null;

  const [test, setTest] = useState(null);
  const [initialAnswers, setInitialAnswers] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [lockDetail, setLockDetail] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function loadTest() {
      try {
        const data = await api.candidate.getTest(testId);
        if (cancelled) return;
        setInitialAnswers(mergeAnswers(data.answers || {}, readDraft(candidateId, testId)));
        setTest(data);
      } catch (err) {
        if (cancelled) return;
        const detail = err.message || '';
        if (isAssessmentLocked(err)) {
          setLockDetail(detail || LOCKED_DETAIL);
        } else {
          setLoadError(detail || 'Failed to load test questions');
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    loadTest();
    return () => {
      cancelled = true;
    };
  }, [testId, candidateId]);

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
        if (result.status === 200) clearDraft(candidateId, testId);
      },
    }),
    [testId, candidateId],
  );

  const onAnswersChange = useCallback(
    (next) => writeDraft(candidateId, testId, next),
    [candidateId, testId],
  );

  const backToDashboard = useCallback(() => navigate('/portal/dashboard'), [navigate]);

  if (isLoading) {
    return (
      <div className="w-full max-w-2xl mx-auto py-6 space-y-4" role="status" aria-label="Loading test">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-2 w-full" />
        <Skeleton className="h-64 w-full" />
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
      onSubmitted={backToDashboard}
      onLocked={setLockDetail}
      onExit={backToDashboard}
    />
  );
}
