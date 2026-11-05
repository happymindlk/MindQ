import {
  SRI_LANKA_ZONE_LABEL,
  formatSriLankaDateTime,
} from '../features/package-schedule/sri-lanka-time';

/**
 * Format a package close time for invitation copy (matches SES invite email).
 *
 * Renders in Sri Lanka time so the calendar day and clock match what admins
 * configure in Suite Builder and what candidates see on the portal.
 *
 * @param {string | Date | null | undefined} closeTime ISO string, Date, or unset.
 * @returns {string} e.g. ``31 Oct 2026, 5:29 AM (Sri Lanka Time - GMT+5:30)``
 *   or ``No fixed deadline``.
 */
export function formatDeadlineTimestamp(closeTime) {
  if (closeTime == null || closeTime === '') return 'No fixed deadline';
  const iso = closeTime instanceof Date ? closeTime.toISOString() : closeTime;
  const formatted = formatSriLankaDateTime(iso);
  if (!formatted) return 'No fixed deadline';
  return `${formatted} (${SRI_LANKA_ZONE_LABEL})`;
}
