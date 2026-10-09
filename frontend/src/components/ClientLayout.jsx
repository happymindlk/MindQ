import React from 'react';
import { Outlet, Link, useNavigate } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import ToastProvider from './ui/Toast';
import ThemeToggle from './ThemeToggle';
import CorporateLogo from '../pages/admin/corporates/corporate-logo';
import { useClientSession } from '../pages/client/use-client-session';
import { useIdleTimer } from '../hooks/use-idle-timer';

export default function ClientLayout() {
  const navigate = useNavigate();
  const { corporate, signOut, lock } = useClientSession();

  useIdleTimer({ onIdle: lock });

  const handleSignOut = () => {
    signOut();
    navigate('/client/login', { replace: true });
  };

  return (
    <ToastProvider>
      <div className="flex min-h-screen flex-col bg-canvas text-foreground">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-4 border-b border-border bg-surface/95 px-4 backdrop-blur sm:px-6">
          <Link
            to="/client/dashboard"
            className="flex min-w-0 items-center gap-3 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <CorporateLogo name={corporate?.name ?? ''} logoUrl={corporate?.logo_url} size="sm" />
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold text-foreground">
                {corporate?.name ?? 'Client Portal'}
              </span>
              <span className="block text-[11px] uppercase tracking-wider text-muted">
                MindQ Client Portal
              </span>
            </span>
          </Link>
          <div className="flex shrink-0 items-center gap-2">
            <ThemeToggle />
            <button
              type="button"
              onClick={handleSignOut}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-medium text-muted transition-colors hover:bg-surface-raised hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
              Sign Out
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </ToastProvider>
  );
}
