import {
  clearClientSession,
  readClientSession,
  writeClientSession,
} from '../pages/client/client-session';
import { API_ORIGIN as API_BASE } from './api-origin';
import { saveAttachmentResponse, saveReportResponse } from './download-response';
import { reportsZipFilename } from '../features/mindq-report/report-filename';

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
 * Authenticated request against the client API using the client JWT only.
 * A 401 means the token expired or was revoked: drop it so the route guard
 * sends the user back to /client/login.
 *
 * @param {string} path Path starting with `/api`.
 * @param {string} fallback Message used when the error body carries nothing readable.
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<Response>} A successful (2xx) response.
 */
async function clientRequest(path, fallback, { signal } = {}) {
  const session = readClientSession();
  if (!session) throw new ClientAuthError();
  const res = await fetch(`${API_BASE}${path}`, {
    signal,
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
  return res;
}

async function clientFetch(path, fallback) {
  return (await clientRequest(path, fallback)).json();
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
    const res = await fetch(`${API_BASE}/api/v1/hr/auth/otp/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
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

  /** Report payload for the on-screen preview. */
  getReportData(candidateId) {
    return clientFetch(
      `/api/v1/client/candidates/${encodeURIComponent(candidateId)}/report-data`,
      'Failed to load report data',
    );
  },

  /**
   * Download the server-rendered (WeasyPrint, cached) report PDF — the same
   * file admins get from `adminApi.downloadReport`.
   *
   * @param {string} candidateId
   * @returns {Promise<import('./download-response').ReportDownloadResult>}
   */
  async downloadReport(candidateId) {
    const res = await clientRequest(
      `/api/v1/client/candidates/${encodeURIComponent(candidateId)}/report`,
      'Failed to download report',
    );
    return saveReportResponse(res, `MindQ Report - ${candidateId}`);
  },

  /**
   * Download every completed MindQ Report in a package as one server-built ZIP.
   *
   * @param {string} packageId
   * @param {string} [packageTitle] Fallback filename stem when the response
   *   omits `Content-Disposition`.
   * @param {{ signal?: AbortSignal }} [options]
   * @returns {Promise<import('./download-response').ZipDownloadResult>}
   */
  async downloadPackageReportsZip(packageId, packageTitle = '', { signal } = {}) {
    const res = await clientRequest(
      `/api/v1/client/packages/${encodeURIComponent(packageId)}/reports-zip`,
      'Failed to download reports',
      { signal },
    );
    const filename = await saveAttachmentResponse(res, reportsZipFilename(packageTitle));
    return {
      filename,
      succeeded: Number(res.headers.get('x-report-zip-count') || 0),
      failed: Number(res.headers.get('x-report-zip-failed') || 0),
    };
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
