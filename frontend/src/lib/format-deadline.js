/**
 * Format a package close time for invitation copy (matches SES invite email).
 *
 * @param {string | Date | null | undefined} closeTime ISO string, Date, or unset.
 * @returns {string} e.g. ``October 30, 2026 at 11:59 PM UTC`` or ``No fixed deadline``.
 */
export function formatDeadlineTimestamp(closeTime) {
  if (closeTime == null || closeTime === '') return 'No fixed deadline';
  const when = closeTime instanceof Date ? closeTime : new Date(closeTime);
  if (Number.isNaN(when.getTime())) return 'No fixed deadline';

  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'UTC',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).formatToParts(when);

  const get = (type) => parts.find((p) => p.type === type)?.value ?? '';
  return `${get('month')} ${get('day')}, ${get('year')} at ${get('hour')}:${get('minute')} ${get('dayPeriod')} UTC`;
}
