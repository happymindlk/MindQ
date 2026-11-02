import React, { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw, FileText } from 'lucide-react';
import StatusTile from '../../components/ui/StatusTile';
import PageHeader from '../../components/ui/PageHeader';
import EmptyState from '../../components/ui/EmptyState';
import Button from '../../components/ui/Button';
import Skeleton from '../../components/ui/Skeleton';
import { api } from '../../api/client';
import DeadlineNotice from '../../features/candidate-dashboard/deadline-notice';
import {
  lockedReasonFor,
  usePackageWindow,
} from '../../features/candidate-dashboard/use-package-window';
import { formatDurationBadge } from '../../features/assessment-builder/types/module';
import { useCachedQuery } from '../../hooks/use-cached-query';

const CANDIDATE_DASHBOARD_KEY = 'portal:candidate-dashboard';

export default function TestDashboard() {
  const navigate = useNavigate();
  const fetcher = useCallback(() => api.candidate.getDashboard(), []);
  const {
    data: dashboardData,
    error: loadError,
    isLoading,
    reload: loadDashboard,
  } = useCachedQuery(CANDIDATE_DASHBOARD_KEY, fetcher);

  const windowState = usePackageWindow(
    dashboardData?.window_state,
    dashboardData?.open_time,
    dashboardData?.close_time,
  );

  if (isLoading) {
    return (
      <div className="w-full py-6 space-y-4" role="status" aria-label="Loading assessments">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-4 w-72" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-2">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
      </div>
    );
  }

  if (loadError || !dashboardData) {
    return (
      <div className="w-full py-6">
        <div className="rounded-lg border border-danger/30 bg-danger/5 px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-foreground">Could not load assessments</p>
            <p className="text-xs text-muted mt-0.5">{loadError || 'Please check your connection.'}</p>
          </div>
          <Button variant="secondary" size="sm" onClick={loadDashboard}>
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const { candidate_name, tests } = dashboardData;
  const remainingTests = tests.filter((t) => t.status !== 'completed').length;

  return (
    <div className="w-full py-6 space-y-4">
      <DeadlineNotice
        windowState={windowState}
        openTime={dashboardData.open_time}
        closeTime={dashboardData.close_time}
      />

      <PageHeader title={`Hello, ${candidate_name}`} />

      <div className="rounded-lg border border-border bg-surface px-4 py-3">
        <h3 className="text-sm font-semibold text-foreground">Before You Begin</h3>
        <ul className="mt-2 text-xs text-muted space-y-1.5 list-disc list-inside leading-relaxed">
          <li>Ensure you have a stable internet connection.</li>
          <li>Choose a quiet place where you can concentrate without interruptions.</li>
          <li>
            Each assessment is timed and the timer keeps running if you leave the page, so finish
            it in one sitting.
          </li>
          <li>
            Answer each question honestly and based on your own abilities, preferences, or typical
            behaviour. There are no right or wrong answers for questions that assess your personality
            or behavioural preferences.
          </li>
        </ul>
      </div>

      <p className="text-xs text-neutral-500 dark:text-neutral-400">
        {remainingTests === 0
          ? 'All assessments in your suite are complete.'
          : `You have ${remainingTests} test${remainingTests !== 1 ? 's' : ''} remaining in your assessment suite.`}
      </p>

      {tests.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No assessments assigned"
          description="Your assessment suite has no tests yet. Contact HR if this looks wrong."
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {tests.map((test) => (
            <StatusTile
              key={test.id}
              title={test.title}
              description={test.description}
              status={test.status}
              durationLabel={formatDurationBadge(
                test.duration_seconds ?? test.time_limit_seconds ?? null,
              )}
              lockedReason={lockedReasonFor(test.status, windowState)}
              onClick={() => navigate(`/portal/test/${test.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
