import React, { useEffect, useMemo, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Clock3, LogOut, RefreshCw, ShieldCheck } from 'lucide-react';
import Button from '../components/ui/Button';
import ThemeToggle from '../components/ThemeToggle';
import { useAuth } from '../context/useAuth';
import { isOpsRole } from '../lib/auth-role';
import { supabase } from '../lib/supabaseClient';

const API_BASE = import.meta.env.VITE_API_URL || '';

function requestKey(userId) {
  return `beta-access-requested:${userId}`;
}

/**
 * Waitlist screen for authenticated HR users who are not yet tenant-provisioned.
 */
export default function PendingApproval() {
  const navigate = useNavigate();
  const { session, user, corporateId, loading, isOps, signOut, refreshMembership } = useAuth();
  const [sent, setSent] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState(null);
  const [statusNote, setStatusNote] = useState(null);

  const userId = user?.id;

  useEffect(() => {
    if (!userId) return;
    try {
      if (localStorage.getItem(requestKey(userId)) === '1') {
        setSent(true);
      }
    } catch {
      /* ignore */
    }
  }, [userId]);

  const email = useMemo(() => user?.email || session?.user?.email || '', [user, session]);

  if (loading && !isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas text-muted">
        Loading...
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/admin/login" replace />;
  }

  if (corporateId) {
    return <Navigate to={isOps ? '/admin/history' : '/client/dashboard'} replace />;
  }

  const handleRequest = async () => {
    setError(null);
    setStatusNote(null);
    setIsSending(true);
    try {
      const { data: { session: active } } = await supabase.auth.getSession();
      const res = await fetch(`${API_BASE}/api/request-beta-access`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${active?.access_token ?? ''}`,
          'Content-Type': 'application/json',
        },
      });
      let payload = {};
      try {
        payload = await res.json();
      } catch {
        /* ignore */
      }
      if (!res.ok) {
        throw new Error(
          typeof payload?.detail === 'string' ? payload.detail : 'Failed to send access request',
        );
      }
      if (!payload.success && !payload.already_provisioned) {
        throw new Error(payload.message || 'Failed to send access request');
      }
      if (payload.auto_approved || payload.already_provisioned) {
        const membership = await refreshMembership();
        if (membership?.corporateId) {
          navigate(isOpsRole(membership.role) ? '/admin/history' : '/client/dashboard', { replace: true });
          return;
        }
        throw new Error(
          payload.auto_approved
            ? 'Auto-approved, but membership is not visible yet. Try Check Approval Status.'
            : 'Workspace is provisioned, but membership is not visible yet. Try Check Approval Status.',
        );
      }
      setSent(true);
      if (userId) {
        try {
          localStorage.setItem(requestKey(userId), '1');
        } catch {
          /* ignore */
        }
      }
    } catch (err) {
      setSent(false);
      setError(err.message || 'Failed to send access request');
    } finally {
      setIsSending(false);
    }
  };

  const handleCheckStatus = async () => {
    setError(null);
    setStatusNote(null);
    setIsChecking(true);
    try {
      const membership = await refreshMembership();
      if (membership?.corporateId) {
        navigate(isOpsRole(membership.role) ? '/admin/history' : '/client/dashboard', { replace: true });
        return;
      }
      setStatusNote('Still pending — your admin has not provisioned a corporate workspace yet.');
    } catch (err) {
      setError(err.message || 'Could not refresh approval status');
    } finally {
      setIsChecking(false);
    }
  };

  const handleSignOut = async () => {
    await signOut();
    navigate('/admin/login', { replace: true });
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-[#0A0A0A] text-gray-900 dark:text-white flex flex-col">
      <header className="h-12 flex items-center justify-between px-4 border-b border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-900">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-violet-600/15 flex items-center justify-center border border-violet-600/25">
            <ShieldCheck className="w-3.5 h-3.5 text-violet-600 dark:text-violet-400" />
          </div>
          <span className="text-sm font-semibold">MindQ</span>
        </div>
        <div className="flex items-center gap-1">
          <ThemeToggle />
          <button
            type="button"
            onClick={handleSignOut}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white px-2 py-1.5 rounded-md"
          >
            <LogOut className="w-3.5 h-3.5" />
            Sign out
          </button>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-md rounded-xl bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 px-6 py-8 shadow-sm">
          <div className="w-11 h-11 rounded-full bg-violet-600/10 text-violet-600 dark:text-violet-400 flex items-center justify-center mb-5">
            <Clock3 className="w-5 h-5" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-gray-900 dark:text-white">
            Pending approval
          </h1>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
            Your account is pending approval. Request beta access to set up your corporate workspace.
          </p>
          {email ? (
            <p className="mt-4 text-xs text-gray-500 dark:text-gray-400 font-mono break-all">
              Signed in as {email}
            </p>
          ) : null}

          {error ? (
            <p className="mt-4 text-sm text-danger" role="alert">
              {error}
            </p>
          ) : null}
          {statusNote ? (
            <p className="mt-4 text-sm text-gray-500 dark:text-gray-400" role="status">
              {statusNote}
            </p>
          ) : null}

          <div className="mt-6 space-y-3">
            <Button
              type="button"
              className="w-full !bg-violet-600 hover:!bg-violet-500 !text-white"
              isLoading={isSending}
              disabled={sent || isChecking}
              onClick={handleRequest}
            >
              {sent ? 'Request Sent' : 'Request Access'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="w-full"
              isLoading={isChecking}
              disabled={isSending}
              onClick={handleCheckStatus}
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Check Approval Status
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              disabled={isSending || isChecking}
              onClick={handleSignOut}
            >
              <LogOut className="w-3.5 h-3.5" />
              Sign Out
            </Button>
            {sent ? (
              <p className="pt-1 text-xs text-center text-gray-500 dark:text-gray-400">
                We notified the MindQ team. You&apos;ll regain access once your tenant is
                provisioned — then tap Check Approval Status.
              </p>
            ) : null}
          </div>
        </div>
      </main>
    </div>
  );
}
