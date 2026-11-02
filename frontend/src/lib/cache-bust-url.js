/**
 * Append a cache-busting query param so browsers/CDNs refetch after a logo replace.
 *
 * Existing query strings are preserved; a prior ``t`` value is replaced.
 *
 * @param {string | null | undefined} url
 * @param {number} [token=Date.now()]
 * @returns {string} Empty string when ``url`` is blank.
 */
export function cacheBustUrl(url, token = Date.now()) {
  const raw = typeof url === 'string' ? url.trim() : '';
  if (!raw) return '';
  try {
    const parsed = new URL(raw, typeof window !== 'undefined' ? window.location.origin : 'https://local.invalid');
    parsed.searchParams.set('t', String(token));
    // Absolute http(s) URLs stay absolute; relative paths stay path+search+hash.
    if (/^https?:\/\//i.test(raw)) {
      return parsed.toString();
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    const joiner = raw.includes('?') ? '&' : '?';
    return `${raw}${joiner}t=${token}`;
  }
}
