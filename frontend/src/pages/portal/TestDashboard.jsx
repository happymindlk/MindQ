import React, { useCallback, useEffect, useState } from 'react';
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

export default function TestDashboard() {
  const navigate = useNavigate();
  const [dashboardData, setDashboardData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  const loadDashboard = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const data = await api.candidate.getDashboard();
      setDashboardData(data);
    } catch (err) {
      console.error('Failed to load dashboard:', err);
      setLoadError(err.message || 'Failed to load assessment data');
      setDashboardData(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

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

      <PageHeader
        title={`Hello, ${candidate_name}`}
        description={
          remainingTests === 0
            ? 'All assessments in your suite are complete.'
            : `You have ${remainingTests} test${remainingTests !== 1 ? 's' : ''} remaining in your assessment suite.`
        }
      />

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
              lockedReason={lockedReasonFor(test.status, windowState)}
              onClick={() => navigate(`/portal/test/${test.id}`)}
            />
          ))}
        </div>
      )}

      <div className="rounded-lg border border-border bg-surface px-4 py-3">
        <h3 className="text-sm font-semibold text-foreground">Before you start</h3>
        <ul className="mt-2 text-xs text-muted space-y-1.5 list-disc list-inside leading-relaxed">
          <li>Ensure you have a stable internet connection.</li>
          <li>Find a quiet place where you won&apos;t be interrupted.</li>
          <li>
            Each assessment is timed and the timer keeps running if you leave the page, so finish
            it in one sitting.
          </li>
        </ul>
      </div>
    </div>
  );
}
