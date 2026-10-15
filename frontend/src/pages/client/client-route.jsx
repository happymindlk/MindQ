import React from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useClientSession } from './use-client-session';
import { isExpired } from './client-session';
import SessionLockModal from '../../components/session-lock-modal';

/** Gates `/client/*` on a valid client JWT; the Supabase ops session is ignored. */
export default function ClientRoute({ children }) {
  const { session, locked, clearLock } = useClientSession();
  const location = useLocation();
  const navigate = useNavigate();

  if (locked && isExpired(session)) {
    return (
      <div className="min-h-screen bg-canvas">
        <SessionLockModal
          variant="redirect"
          onContinue={() => {
            clearLock();
            navigate('/client/login', { replace: true, state: { from: location } });
          }}
        />
      </div>
    );
  }

  if (isExpired(session)) {
    return <Navigate to="/client/login" replace state={{ from: location }} />;
  }
  return children;
}
