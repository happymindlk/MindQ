import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ClientSessionContext } from './client-session-context';
import { clearClientSession, readClientSession } from './client-session';

/**
 * Client-portal session state. Deliberately independent of the Supabase-backed
 * AuthProvider so ops and HR sessions can coexist in one browser without
 * cross-authenticating.
 */
export default function ClientSessionProvider({ children }) {
  const [session, setSession] = useState(() => readClientSession());
  const [locked, setLocked] = useState(false);

  useEffect(() => {
    const sync = () => setSession(readClientSession());
    window.addEventListener('client-session-expired', sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener('client-session-expired', sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  const signIn = useCallback((next) => {
    setLocked(false);
    setSession(next);
  }, []);

  const signOut = useCallback(() => {
    clearClientSession();
    setSession(null);
  }, []);

  /** Idle lock: the token is purged immediately; `locked` keeps the lock screen up. */
  const lock = useCallback(() => {
    setLocked(true);
    clearClientSession();
    setSession(null);
  }, []);

  const clearLock = useCallback(() => setLocked(false), []);

  const value = useMemo(
    () => ({
      session,
      corporate: session?.corporate ?? null,
      isAuthenticated: Boolean(session),
      locked,
      signIn,
      signOut,
      lock,
      clearLock,
    }),
    [session, locked, signIn, signOut, lock, clearLock],
  );

  return <ClientSessionContext.Provider value={value}>{children}</ClientSessionContext.Provider>;
}
