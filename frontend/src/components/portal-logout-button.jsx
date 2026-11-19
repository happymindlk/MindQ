import React, { useCallback, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { clearCandidateSession } from '../features/candidate-auth/candidate-otp-api';
import Button from './ui/Button';
import Modal from './ui/Modal';
import { isPortalTestRunnerPath, portalLoginPathAfterLogout } from './portal-logout-path';

/**
 * Header logout control for the authenticated candidate portal.
 * Hidden on `/portal/test/...` so candidates cannot end the session mid-test.
 */
export default function PortalLogoutButton() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  const hasSession =
    typeof window !== 'undefined' && Boolean(localStorage.getItem('candidateToken'));
  const hideOnRunner = isPortalTestRunnerPath(pathname);

  const handleConfirmLogout = useCallback(async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    const nextPath = portalLoginPathAfterLogout();
    try {
      await clearCandidateSession();
    } finally {
      setConfirmOpen(false);
      setLoggingOut(false);
      navigate(nextPath, { replace: true });
    }
  }, [loggingOut, navigate]);

  if (!hasSession || hideOnRunner) {
    return null;
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setConfirmOpen(true)}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-3 text-xs font-medium text-muted transition-colors hover:bg-surface-raised hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        aria-label="Log out"
      >
        <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
        Log out
      </button>

      <Modal
        isOpen={confirmOpen}
        onClose={() => !loggingOut && setConfirmOpen(false)}
        title="Log out?"
        contentClassName="max-w-sm"
        actions={
          <>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={loggingOut}
              onClick={() => setConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="danger"
              size="sm"
              isLoading={loggingOut}
              onClick={handleConfirmLogout}
            >
              Log out
            </Button>
          </>
        }
      />
    </>
  );
}
