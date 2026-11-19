import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import BrandLogo from './BrandLogo';
import PortalFooter from './PortalFooter';
import SupportModal from './SupportModal';
import ToastProvider from './ui/Toast';
import RouteErrorBoundary from './route-error-boundary';
import ThemeToggle from './ThemeToggle';
import PortalLogoutButton from './portal-logout-button';
import KeepAliveOutlet from './keep-alive-outlet';
import { PORTAL_KEEP_PATTERNS } from './keep-alive-routes';
import { api } from '../api/client';
import {
  clearLocalCandidateSession,
} from '../features/candidate-auth/candidate-otp-api';
import { CANDIDATE_DASHBOARD_KEY } from '../features/candidate-dashboard/module-status';
import { ApiError } from '../lib/api-error';
import { cachedQuery } from '../lib/query-cache';

/**
 * Candidate assessment shell. Shares Design System tokens with admin Operate surfaces.
 */
export default function PortalLayout() {
  const [hasSession, setHasSession] = useState(
    () => typeof window !== 'undefined' && Boolean(localStorage.getItem('candidateToken')),
  );
  const brandTo = hasSession ? '/portal/dashboard' : '/portal';

  // Warm the candidate dashboard once at the shell so remounts hit cache.
  // A 401 from an expired JWT clears local session quietly (no toast).
  useEffect(() => {
    if (!hasSession) return undefined;
    void cachedQuery(CANDIDATE_DASHBOARD_KEY, () => api.candidate.getDashboard()).catch(
      (err) => {
        const status = err instanceof ApiError ? err.status : err?.status;
        if (status === 401) {
          clearLocalCandidateSession();
          setHasSession(false);
        }
      },
    );
    return undefined;
  }, [hasSession]);

  return (
    <ToastProvider>
      <div className="min-h-screen bg-canvas flex flex-col text-foreground">
        <header className="border-b border-border bg-surface sticky top-0 z-10">
          <div className="max-w-4xl mx-auto px-3 sm:px-4 h-12 flex items-center justify-between gap-3">
            <Link
              to={brandTo}
              aria-label="MindQ home"
              className="flex items-center min-w-0 focus-visible:ring-2 focus-visible:ring-primary rounded-md"
            >
              <BrandLogo collapsed={false} className="h-7 w-auto" />
            </Link>
            <div className="flex items-center gap-2 shrink-0">
              <p className="text-xs font-medium text-muted hidden sm:block">Assessment Portal</p>
              <ThemeToggle />
              <PortalLogoutButton />
            </div>
          </div>
        </header>

        <main className="flex-1 flex flex-col items-center p-3 sm:p-4">
          <div className="w-full max-w-3xl flex-1 flex flex-col">
            <RouteErrorBoundary>
              <KeepAliveOutlet patterns={PORTAL_KEEP_PATTERNS} />
            </RouteErrorBoundary>
          </div>
        </main>

        <PortalFooter />
        <SupportModal />
      </div>
    </ToastProvider>
  );
}
