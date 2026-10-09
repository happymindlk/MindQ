import React from 'react';
import { Outlet, Link } from 'react-router-dom';
import { Brain } from 'lucide-react';
import SupportModal from './SupportModal';
import ToastProvider from './ui/Toast';
import ThemeToggle from './ThemeToggle';

/**
 * Candidate assessment shell. Shares Design System tokens with admin Operate surfaces.
 */
export default function PortalLayout() {
  const hasSession =
    typeof window !== 'undefined' && Boolean(localStorage.getItem('candidateToken'));
  const brandTo = hasSession ? '/portal/dashboard' : '/portal';

  return (
    <ToastProvider>
      <div className="min-h-screen bg-canvas flex flex-col text-foreground">
        <header className="border-b border-border bg-surface sticky top-0 z-10">
          <div className="max-w-4xl mx-auto px-3 sm:px-4 h-12 flex items-center justify-between gap-3">
            <Link
              to={brandTo}
              aria-label="MindQ home"
              className="flex items-center gap-2 min-w-0 focus-visible:ring-2 focus-visible:ring-primary rounded-md"
            >
              <div className="w-7 h-7 rounded-md bg-indigo-600 flex items-center justify-center shrink-0">
                <Brain className="w-3.5 h-3.5 text-white" aria-hidden />
              </div>
              <span className="font-semibold text-sm text-foreground truncate">MindQ</span>
            </Link>
            <div className="flex items-center gap-2 shrink-0">
              <p className="text-xs font-medium text-muted hidden sm:block">Assessment Portal</p>
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main className="flex-1 flex flex-col items-center p-3 sm:p-4">
          <div className="w-full max-w-3xl flex-1 flex flex-col">
            <Outlet />
          </div>
        </main>

        <SupportModal />
      </div>
    </ToastProvider>
  );
}
