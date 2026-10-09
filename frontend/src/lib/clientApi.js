import { supabaseOtp } from './supabase-otp-client';
import {
  clearClientSession,
  readClientSession,
  writeClientSession,
} from '../pages/client/client-session';

const API_BASE = import.meta.env.VITE_API_URL || '';

export class ClientAuthError extends Error {
  constructor(message = 'Your session has expired. Please sign in again.') {
    super(message);
    this.name = 'ClientAuthError';
  }
}

async function readError(res, fallback) {
  let detail = fallback;
  try {
    const payload = await res.json();
    detail = payload?.detail || fallback;
  } catch {
    /* non-JSON error body */
  }
  return typeof detail === 'string' ? detail : fallback;
}

/**
 * Authenticated fetch against the client API using the client JWT only.
 * A 401 means the token expired or was revoked: drop it so the route guard
 * sends the user back to /client/login.
 */
async function clientFetch(path, fallback) {
  const session = readClientSession();
  if (!session) throw new ClientAuthError();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      Authorization: `Bearer ${session.token}`,
      'Content-Type': 'application/json',
    },
  });
  if (res.status === 401) {
    clearClientSession();
    window.dispatchEvent(new Event('client-session-expired'));
    throw new ClientAuthError();
  }
  if (!res.ok) throw new Error(await readError(res, fallback));
  return res.json();
}

/**
 * HR client portal API. Scorecards and reports are server-masked
 * (psychometric modules stripped) and tenant-scoped by the client JWT.
 */
export const clientApi = {
  async requestOtp(email) {
    const { error } = await supabaseOtp.auth.signInWithOtp({
      email,
      options: { shouldCreateUser: false },
    });
    if (error) throw new Error(error.message);
  },

  /**
   * Verify the emailed code, then exchange the short-lived Supabase token for a
   * client JWT. The Supabase session is discarded immediately afterwards.
   *
   * @returns {Promise<import('../pages/client/client-session').ClientSession>}
   */
  async verifyOtp(email, token) {
    const { data, error } = await supabaseOtp.auth.verifyOtp({ email, token, type: 'email' });
    if (error) throw new Error(error.message);
    const supabaseToken = data.session?.access_token;
    if (!supabaseToken) throw new Error('Verification did not return a session');

    try {
      const res = await fetch(`${API_BASE}/api/v1/client/auth/session`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${supabaseToken}` },
      });
      if (!res.ok) throw new Error(await readError(res, 'Could not start client session'));
      return writeClientSession(await res.json());
    } finally {
      await supabaseOtp.auth.signOut({ scope: 'local' });
    }
  },

  signOut() {
    clearClientSession();
  },

  getDashboard() {
    return clientFetch('/api/v1/client/dashboard', 'Failed to load dashboard');
  },

  getScorecard(candidateId) {
    return clientFetch(
      `/api/v1/client/candidates/${encodeURIComponent(candidateId)}/scorecard`,
      'Failed to load scorecard',
    );
  },

  /** Technical-only report payload for client-side PDF export. */
  getReportData(candidateId) {
    return clientFetch(
      `/api/v1/client/candidates/${encodeURIComponent(candidateId)}/report-data`,
      'Failed to load report data',
    );
  },

  async getBlindReview(packageToken) {
    const res = await fetch(
      `${API_BASE}/api/v1/packages/review/${encodeURIComponent(packageToken)}`,
    );
    if (!res.ok) throw new Error(await readError(res, 'Review link is invalid or expired'));
    return res.json();
  },

  async approveBlindReview(packageToken) {
    const res = await fetch(
      `${API_BASE}/api/v1/client/review/${encodeURIComponent(packageToken)}/approve`,
      { method: 'POST' },
    );
    if (!res.ok) throw new Error(await readError(res, 'Approval failed'));
    return res.json();
  },
};
