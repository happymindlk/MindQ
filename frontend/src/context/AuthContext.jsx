import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { supabase } from '../lib/supabaseClient';
import { isOpsRole, resolveRole } from '../lib/auth-role';
import { AuthContext } from './auth-context';

function readJwtCorporateId(session) {
  return session?.user?.app_metadata?.corporate_id ?? null;
}

function claimsAreStale(session, membership) {
  if (!membership) return false;
  const meta = session?.user?.app_metadata ?? {};
  const jwtRole = meta.corporate_role ?? meta.role ?? null;
  return (
    (membership.role ?? null) !== jwtRole
    || (membership.corporate_id ?? null) !== (meta.corporate_id ?? null)
  );
}

/**
 * Source of truth for tenant membership is public.hr_users (RLS: user_id = auth.uid()).
 * JWT app_metadata.corporate_id is a cache populated by the custom access token hook
 * and can be stale until refreshSession() after SQL provisioning.
 */
async function fetchHrMembership(userId) {
  if (!userId) return null;
  const { data, error } = await supabase
    .from('hr_users')
    .select('user_id, corporate_id, role, full_name')
    .eq('user_id', userId)
    .maybeSingle();
  if (error) {
    console.error('hr_users membership fetch failed:', error.message);
    throw error;
  }
  return data;
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [corporateId, setCorporateId] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [locked, setLocked] = useState(false);
  const [lockedEmail, setLockedEmail] = useState(null);
  const staleRefreshKey = useRef(null);

  const applyMembership = useCallback(async (nextSession) => {
    setSession(nextSession);
    if (!nextSession?.user?.id) {
      setCorporateId(null);
      setProfile(null);
      return null;
    }

    const jwtCorp = readJwtCorporateId(nextSession);
    try {
      const membership = await fetchHrMembership(nextSession.user.id);
      setProfile(membership);
      const resolved = membership?.corporate_id || jwtCorp || null;
      setCorporateId(resolved);

      // The API and RLS authorize from JWT claims, so a role change in hr_users
      // (e.g. hr -> admin) yields 403s until the access-token hook re-mints the
      // token. One attempt per user+role avoids a loop if the hook is disabled.
      const key = `${nextSession.user.id}:${membership?.role}:${membership?.corporate_id}`;
      if (claimsAreStale(nextSession, membership) && staleRefreshKey.current !== key) {
        staleRefreshKey.current = key;
        const { error: refreshError } = await supabase.auth.refreshSession();
        if (refreshError) {
          console.warn('Session refresh for stale role claims failed:', refreshError.message);
        }
      }
      return resolved;
    } catch {
      // Fall back to JWT claim if the table query fails (network / RLS misconfig).
      setProfile(null);
      setCorporateId(jwtCorp);
      return jwtCorp;
    }
  }, []);

  const refreshMembership = useCallback(async () => {
    const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
    if (sessionError) throw sessionError;
    const active = sessionData.session;
    if (!active?.user?.id) {
      await applyMembership(null);
      return { corporateId: null, role: null };
    }

    // Re-read hr_users first (works even when JWT claims are stale).
    const membership = await fetchHrMembership(active.user.id);
    if (membership?.corporate_id) {
      // Refresh so the custom access token hook injects corporate_id into the JWT
      // (required for RLS on corporates / packages / candidates).
      const { data: refreshed, error: refreshError } = await supabase.auth.refreshSession();
      if (refreshError) {
        console.warn('Session refresh after provisioning failed:', refreshError.message);
        setSession(active);
        setProfile(membership);
        setCorporateId(membership.corporate_id);
        return { corporateId: membership.corporate_id, role: membership.role ?? null };
      }
      await applyMembership(refreshed.session ?? active);
      // Prefer DB membership if JWT hook is not yet enabled.
      if (membership.corporate_id) {
        setCorporateId(membership.corporate_id);
        setProfile(membership);
      }
      return { corporateId: membership.corporate_id, role: membership.role ?? null };
    }

    await applyMembership(active);
    return { corporateId: null, role: membership?.role ?? resolveRole(active, membership) };
  }, [applyMembership]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      setLoading(true);
      const { data } = await supabase.auth.getSession();
      if (cancelled) return;
      await applyMembership(data.session);
      if (!cancelled) setLoading(false);
    })();

    const { data: listener } = supabase.auth.onAuthStateChange((event, newSession) => {
      // Defer so we don't deadlock with other supabase-js auth calls.
      queueMicrotask(async () => {
        const gate =
          event === 'SIGNED_IN' || event === 'SIGNED_OUT' || event === 'USER_UPDATED';
        if (gate) setLoading(true);
        await applyMembership(newSession);
        if (gate) setLoading(false);
      });
    });

    return () => {
      cancelled = true;
      listener.subscription.unsubscribe();
    };
  }, [applyMembership]);

  /**
   * Idle lock: remember who was signed in, then drop this tab's tokens. The flag is
   * set before signOut so ProtectedRoute renders the lock screen instead of
   * redirecting to /admin/login when the SIGNED_OUT event lands.
   */
  const lockSession = useCallback(async () => {
    const email = session?.user?.email ?? null;
    if (!email) return;
    setLockedEmail(email);
    setLocked(true);
    const { error } = await supabase.auth.signOut({ scope: 'local' });
    if (error) console.error('Idle lock sign-out failed:', error.message);
  }, [session]);

  const unlockSession = useCallback(
    async (password) => {
      if (!lockedEmail) throw new Error('No locked account to unlock.');
      const { error } = await supabase.auth.signInWithPassword({ email: lockedEmail, password });
      if (error) throw error;
      setLocked(false);
      setLockedEmail(null);
    },
    [lockedEmail],
  );

  const clearLock = useCallback(() => {
    setLocked(false);
    setLockedEmail(null);
  }, []);

  const value = useMemo(
    () => ({
      session,
      user: session?.user ?? null,
      corporateId,
      profile,
      loading,
      refreshMembership,
      role: resolveRole(session, profile),
      isOps: isOpsRole(resolveRole(session, profile)),
      locked,
      lockedEmail,
      lockSession,
      unlockSession,
      clearLock,
      signIn: (email, password) => supabase.auth.signInWithPassword({ email, password }),
      signOut: () => {
        clearLock();
        return supabase.auth.signOut();
      },
    }),
    [
      session,
      corporateId,
      profile,
      loading,
      refreshMembership,
      locked,
      lockedEmail,
      lockSession,
      unlockSession,
      clearLock,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
