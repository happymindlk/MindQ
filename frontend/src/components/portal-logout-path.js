/**
 * Build the post-logout portal login path, keeping the invite code when known.
 *
 * @returns {string}
 */
export function portalLoginPathAfterLogout() {
  const code = localStorage.getItem('candidateAccessCode')?.trim();
  return code ? `/portal?code=${encodeURIComponent(code)}` : '/portal';
}

/**
 * True while the candidate is on the timed assessment runner.
 *
 * @param {string} pathname
 * @returns {boolean}
 */
export function isPortalTestRunnerPath(pathname) {
  return /^\/portal\/test(\/|$)/.test(pathname);
}
