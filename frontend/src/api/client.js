// Thin FastAPI service client for the candidate flow, reports, and chat.
// HR admin data access lives in src/lib/adminApi.js (supabase-js + RLS).
import { API_ORIGIN } from '../lib/api-origin';
import { requestJson } from '../lib/api-request';
import { getDeviceHeaders } from '../lib/device';

const API_BASE = `${API_ORIGIN}/api/v1`;

/**
 * @param {{ json?: boolean }} [options] Set `json` when the request carries a JSON body.
 * @returns {Record<string, string>}
 */
const getAuthHeaders = ({ json = false } = {}) => {
  const token = localStorage.getItem('candidateToken');
  return {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(token && { Authorization: `Bearer ${token}` }),
    ...getDeviceHeaders(),
  };
};

const handleResponse = async (response) => {
  if (!response.ok) {
    let errorMessage = 'An error occurred';
    let errorCode = null;
    try {
      const errorData = await response.json();
      // FastAPI returns errors under `detail`; structured ones carry {code, message}.
      if (typeof errorData.detail === 'string') {
        errorMessage = errorData.detail;
      } else if (Array.isArray(errorData.detail) && errorData.detail[0]?.msg) {
        errorMessage = errorData.detail[0].msg;
      } else if (errorData.detail && typeof errorData.detail === 'object') {
        errorMessage = errorData.detail.message || errorMessage;
        errorCode = errorData.detail.code || null;
      } else if (errorData.message) {
        errorMessage = errorData.message;
      }
    } catch {
      // non-JSON error body; keep default
    }
    const error = new Error(errorMessage);
    error.status = response.status;
    error.code = errorCode;
    throw error;
  }
  return response.json();
};

/** Hard cap per exam-path request; a stalled socket must not hang the runner. */
export const EXAM_REQUEST_TIMEOUT_MS = 15000;

/** Thrown when an exam-path request is aborted by {@link EXAM_REQUEST_TIMEOUT_MS}. */
export const TIMEOUT_CODE = 'TIMEOUT';
/** Thrown when fetch itself rejects (offline, DNS, captive portal, CORS). */
export const NETWORK_CODE = 'NETWORK';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * fetch() with an AbortController deadline. Timeouts and network failures are
 * normalized to Errors carrying ``code`` + ``retryable`` so callers can retry.
 *
 * @param {string} url
 * @param {RequestInit} init
 * @param {number} [timeoutMs]
 * @returns {Promise<Response>}
 */
export async function fetchWithTimeout(url, init = {}, timeoutMs = EXAM_REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err) {
    const timedOut = controller.signal.aborted;
    const error = new Error(
      timedOut
        ? 'The server took too long to respond.'
        : 'Network connection lost. Check your connection and try again.',
    );
    error.status = 0;
    error.code = timedOut ? TIMEOUT_CODE : NETWORK_CODE;
    error.retryable = true;
    error.cause = err;
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Whether an exam-path failure is worth retrying automatically.
 * Only transport failures and gateway/overload statuses: a 4xx is a real
 * answer from the server and retrying cannot change it.
 *
 * @param {unknown} err
 * @returns {boolean}
 */
export function isRetryableRequestError(err) {
  if (!err || typeof err !== 'object') return false;
  if (err.retryable) return true;
  return err.status === 502 || err.status === 503 || err.status === 504;
}

/**
 * Run ``attempt`` with exponential backoff (``baseMs``, 2x, ...) on retryable errors.
 *
 * @template T
 * @param {() => Promise<T>} attempt
 * @param {{ retries?: number, baseMs?: number }} [options]
 * @returns {Promise<T>}
 */
export async function withRetry(attempt, { retries = 2, baseMs = 1000 } = {}) {
  for (let i = 0; ; i += 1) {
    try {
      return await attempt();
    } catch (err) {
      if (i >= retries || !isRetryableRequestError(err)) throw err;
      await sleep(baseMs * 2 ** i);
    }
  }
}

const monotonicNow = () =>
  typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now();

/**
 * Run one request and stamp ``client_rtt_ms`` on an object payload so the
 * runner timer can correct ``server_now`` by RTT/2. Measured per attempt, so a
 * retried request reports the round trip of the attempt that succeeded.
 *
 * @template T
 * @param {() => Promise<T>} send
 * @returns {Promise<T>}
 */
async function withClientRtt(send) {
  const started = monotonicNow();
  const data = await send();
  const rtt = monotonicNow() - started;
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    return { ...data, client_rtt_ms: Math.max(0, Math.round(rtt)) };
  }
  return data;
}

export const api = {
  candidate: {
    /**
     * @param {{ access_code: string, email: string, first_name: string, full_name: string, terms_accepted: true }} target
     * @returns {Promise<{ status: string, temp_token: string }>}
     */
    sendCandidateOtp: async (target) => {
      const res = await fetch(`${API_BASE}/candidates/auth/otp/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getDeviceHeaders() },
        body: JSON.stringify(target),
      });
      return handleResponse(res);
    },
    /**
     * @param {{ access_code: string, first_name: string, full_name: string, email: string, temp_token: string, otp_code: string, terms_accepted: true }} credentials
     */
    verifyCandidateOtp: async (credentials) => {
      const res = await fetch(`${API_BASE}/candidates/auth/otp/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getDeviceHeaders() },
        body: JSON.stringify(credentials),
      });
      return handleResponse(res);
    },
    getDashboard: async () => {
      return requestJson(`${API_BASE}/candidate/dashboard`, { headers: getAuthHeaders() }, 'Failed to load dashboard');
    },
    getTest: async (assessmentId) =>
      withClientRtt(() =>
        requestJson(
          `${API_BASE}/candidate/test/${assessmentId}`,
          { headers: getAuthHeaders() },
          'Failed to load test',
        ),
      ),
    // POST /start is idempotent server-side (returns the existing attempt).
    startTest: async (assessmentId) =>
      withRetry(() =>
        withClientRtt(async () => {
          const res = await fetchWithTimeout(`${API_BASE}/candidate/test/${assessmentId}/start`, {
            method: 'POST',
            headers: getAuthHeaders(),
          });
          return handleResponse(res);
        }),
      ),
    /**
     * @param {object} data ResponseSave payload.
     * @param {{ keepalive?: boolean }} [options] ``keepalive`` lets the request
     *   outlive the page (pagehide flush); it is sent once, without retries.
     */
    autosave: async (data, { keepalive = false } = {}) => {
      const send = async () => {
        const res = await fetchWithTimeout(`${API_BASE}/candidate/autosave`, {
          method: 'POST',
          headers: getAuthHeaders({ json: true }),
          body: JSON.stringify(data),
          keepalive,
        });
        return handleResponse(res);
      };
      // Autosave is an idempotent upsert; the runner adds a slower background
      // backoff on top of these quick retries.
      return keepalive ? send() : withRetry(send, { retries: 1 });
    },
    // Submit is idempotent: a retry after a lost 200 gets 409 ALREADY_SUBMITTED,
    // which TestRunner confirms before treating it as success.
    submitTest: async (assessmentId, responses = [], totalModuleDurationSeconds = null) =>
      withRetry(async () => {
        const res = await fetchWithTimeout(`${API_BASE}/candidate/test/${assessmentId}/submit`, {
          method: 'POST',
          headers: getAuthHeaders({ json: true }),
          body: JSON.stringify({
            responses,
            total_module_duration_seconds: totalModuleDurationSeconds,
          }),
        });
        const data = await handleResponse(res);
        return { ...data, status: res.status };
      }),
    logout: async () => {
      const token = localStorage.getItem('candidateToken');
      if (!token) return { ok: true };
      const res = await fetch(`${API_BASE}/candidate/logout`, {
        method: 'POST',
        headers: getAuthHeaders(),
      });
      // Always clear local session; best-effort server release of the device lock.
      if (!res.ok && res.status !== 401) {
        await handleResponse(res);
      }
      return { ok: true };
    },
  },
  chat: {
    sendMessage: async (message) => {
      const res = await fetch(`${API_BASE}/chat/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });
      return handleResponse(res);
    },
  },
};
