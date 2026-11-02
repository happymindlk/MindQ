import { matchPath } from 'react-router-dom';

/**
 * Primary admin nav routes that are safe to keep mounted across tab switches.
 * Parameterized detail/edit routes are excluded so they remount cleanly.
 */
export const ADMIN_KEEP_PATTERNS = [
  { key: 'admin-home', path: '/admin', end: true },
  { key: 'admin-home', path: '/admin/dashboard', end: true },
  { key: 'admin-library', path: '/admin/library', end: false },
  { key: 'admin-suite-create', path: '/admin/packages/create', end: true },
  { key: 'admin-history', path: '/admin/history', end: false },
];

export const PORTAL_KEEP_PATTERNS = [
  // Dashboard remounts so post-submit status is never served from a frozen tree.
  { key: 'portal-guidelines', path: '/portal/guidelines', end: true },
];

export const CLIENT_KEEP_PATTERNS = [
  { key: 'client-dashboard', path: '/client/dashboard', end: true },
];

/**
 * @param {string} pathname
 * @param {{ key: string, path: string, end: boolean }[]} patterns
 * @returns {string | null}
 */
export function resolveKeepAliveKey(pathname, patterns) {
  for (const pattern of patterns) {
    if (matchPath({ path: pattern.path, end: pattern.end }, pathname)) {
      return pattern.key;
    }
  }
  return null;
}
