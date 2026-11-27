/**
 * Candidate identity for client-side keys (draft backups).
 *
 * The signed candidate token is the source of truth: its ``sub`` claim is the
 * candidate id. Reading it here means the draft backup still works when the
 * separate ``candidateId`` localStorage key is missing or stale. The token is
 * only decoded, not verified; the server verifies it on every request.
 */

const TOKEN_KEY = 'candidateToken';
const LEGACY_ID_KEY = 'candidateId';

/**
 * Decode a JWT payload (base64url) without verifying it.
 *
 * @param {string | null | undefined} token
 * @returns {Record<string, unknown> | null}
 */
export function decodeTokenClaims(token) {
  if (typeof token !== 'string') return null;
  const parts = token.split('.');
  if (parts.length !== 3) return null;
  try {
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    const json = decodeURIComponent(
      Array.from(atob(padded), (c) => `%${c.charCodeAt(0).toString(16).padStart(2, '0')}`).join(''),
    );
    const claims = JSON.parse(json);
    return claims && typeof claims === 'object' ? claims : null;
  } catch {
    return null;
  }
}

/**
 * Current candidate id: token ``sub`` first, legacy localStorage key second.
 *
 * @returns {string | null}
 */
export function getCandidateId() {
  if (typeof window === 'undefined') return null;
  let token = null;
  let legacy = null;
  try {
    token = window.localStorage.getItem(TOKEN_KEY);
    legacy = window.localStorage.getItem(LEGACY_ID_KEY);
  } catch {
    return null;
  }
  const sub = decodeTokenClaims(token)?.sub;
  if (typeof sub === 'string' && sub.length > 0) return sub;
  return legacy || null;
}
