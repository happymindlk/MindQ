import React from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/useAuth';
import SessionLockModal from './session-lock-modal';

/**
 * Gates the internal ops portal on a Supabase session with an ops role.
 * The HR client portal uses its own token and guard (`pages/client/client-route`).
 */
export default function ProtectedRoute({ children }) {
  const { session, corporateId, loading, isOps, locked, lockedEmail, unlockSession, clearLock } =
    useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  if (locked && !session) {
    return (
      <div className="min-h-screen bg-canvas">
        <SessionLockModal
          variant="password"
          email={lockedEmail}
          onUnlock={unlockSession}
          onSwitchAccount={() => {
            clearLock();
            navigate('/admin/login', { replace: true, state: { from: location } });
          }}
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas text-muted">
        Loading...
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/admin/login" replace state={{ from: location }} />;
  }

  if (!corporateId) {
    return <Navigate to="/pending-approval" replace />;
  }

  if (!isOps) {
    return <Navigate to="/client/login" replace />;
  }

  return children;
}
