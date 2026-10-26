import {
  clearClientSession,
  readClientSession,
  writeClientSession,
} from '../pages/client/client-session';
import { API_ORIGIN as API_BASE } from './api-origin';

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
  /**
   * Ask the backend to email a one-time code (FastAPI + AWS SES; no
   * Supabase Auth email is involved).
   *
   * @param {string} email Registered corporate email.
   * @returns {Promise<string>} Temp token that must accompany the code at verify.
   */
  async requestOtp(email) {
    // #region agent log
    if (import.meta.env.MODE !== 'test') {
      fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'410e50'},body:JSON.stringify({sessionId:'410e50',runId:'pre-fix',hypothesisId:'F',location:'clientApi.js:requestOtp',message:'hr_otp_send_start',data:{apiBase:API_BASE||'(same-origin)',emailDomain:(email||'').split('@')[1]||'',emailLen:(email||'').length},timestamp:Date.now()})}).catch(()=>{});
    }
    // #endregion
    const res = await fetch(`${API_BASE}/api/v1/hr/auth/otp/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    // #region agent log
    if (import.meta.env.MODE !== 'test') {
      fetch('http://127.0.0.1:7914/ingest/7b7bc9f0-a919-4525-9fab-35a7604b1d30',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'410e50'},body:JSON.stringify({sessionId:'410e50',runId:'pre-fix',hypothesisId:'F',location:'clientApi.js:requestOtp',message:'hr_otp_send_result',data:{apiBase:API_BASE||'(same-origin)',status:res.status,ok:res.ok},timestamp:Date.now()})}).catch(()=>{});
    }
    // #endregion
    if (!res.ok) throw new Error(await readError(res, 'Could not send code'));
    const payload = await res.json();
    if (!payload?.temp_token) {
      throw new Error('Verification did not return a session. Request a new code.');
    }
    return payload.temp_token;
  },

  /**
   * Verify the emailed code against the backend challenge. The response is
   * the backend-minted client JWT session directly; there is no Supabase
   * session to exchange or discard.
   *
   * @param {string} email Corporate email the code was sent to.
   * @param {string} token Six-digit code from the email.
   * @param {string} tempToken Temp token returned by {@link clientApi.requestOtp}.
   * @returns {Promise<import('../pages/client/client-session').ClientSession>}
   */
  async verifyOtp(email, token, tempToken) {
    const res = await fetch(`${API_BASE}/api/v1/hr/auth/otp/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, otp_code: token, temp_token: tempToken }),
    });
    if (!res.ok) throw new Error(await readError(res, 'Could not start client session'));
    return writeClientSession(await res.json());
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
