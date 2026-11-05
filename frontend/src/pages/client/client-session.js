const STORAGE_KEY = 'mindq.client.session';
const LEGACY_STORAGE_KEY = 'assesspulse.client.session';
const EXPIRY_SKEW_MS = 30000;

/**
 * @typedef {{ id: string, name: string, logo_url: string | null }} ClientCorporate
 * @typedef {{ token: string, expiresAt: number, corporate: ClientCorporate }} ClientSession
 */

/** @param {ClientSession | null} session */
export function isExpired(session) {
  return !session?.token || !session.expiresAt || Date.now() >= session.expiresAt - EXPIRY_SKEW_MS;
}

/** @returns {ClientSession | null} Valid stored session, or null (expired ones are purged). */
export function readClientSession() {
  try {
    let raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      raw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
      if (raw) {
        window.localStorage.setItem(STORAGE_KEY, raw);
        window.localStorage.removeItem(LEGACY_STORAGE_KEY);
      }
    }
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (isExpired(parsed)) {
      clearClientSession();
      return null;
    }
    return parsed;
  } catch {
    clearClientSession();
    return null;
  }
}

/**
 * Persist the session response from `POST /api/v1/hr/auth/otp/verify`.
 *
 * @param {{ access_token: string, expires_in: number, corporate: ClientCorporate }} response
 * @returns {ClientSession}
 */
export function writeClientSession(response) {
  const session = {
    token: response.access_token,
    expiresAt: Date.now() + response.expires_in * 1000,
    corporate: response.corporate,
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  window.localStorage.removeItem(LEGACY_STORAGE_KEY);
  return session;
}

export function clearClientSession() {
  window.localStorage.removeItem(STORAGE_KEY);
  window.localStorage.removeItem(LEGACY_STORAGE_KEY);
}
