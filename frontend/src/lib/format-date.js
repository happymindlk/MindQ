/**
 * Format an ISO timestamp as a short locale date (e.g. "Mar 14, 2026").
 *
 * @param {string | number | Date | null | undefined} value
 * @returns {string} Formatted date, or an em dash when missing/invalid.
 */
export function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}
