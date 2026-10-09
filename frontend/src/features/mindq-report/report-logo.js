/**
 * Accept only absolute https URLs or inlined image data URLs; localhost URLs
 * would never resolve for the HR recipient of an exported PDF.
 *
 * @param {string | null | undefined} url
 * @returns {string | null}
 */
export function safeLogoUrl(url) {
  if (!url || typeof url !== 'string') return null;
  const trimmed = url.trim();
  const lower = trimmed.toLowerCase();
  if (lower.startsWith('data:image/')) return trimmed;
  if (!lower.startsWith('https://')) return null;
  if (lower.includes('127.0.0.1') || lower.includes('localhost')) return null;
  return trimmed;
}
