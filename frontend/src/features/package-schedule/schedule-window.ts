import { fromSriLankaInputValue } from './sri-lanka-time';

/**
 * Validate the Suite Builder's IST open/close inputs before they reach the API.
 *
 * @param openValue - `datetime-local` value in Sri Lanka time (may be blank).
 * @param closeValue - `datetime-local` value in Sri Lanka time (may be blank).
 * @returns Error message, or `null` when valid or both blank.
 */
export function scheduleWindowError(openValue: string, closeValue: string): string | null {
  const openIso = fromSriLankaInputValue(openValue);
  const closeIso = fromSriLankaInputValue(closeValue);
  if (openValue && !openIso) return 'Open time is not a valid date.';
  if (closeValue && !closeIso) return 'Close time is not a valid date.';
  if (openIso && closeIso && Date.parse(closeIso) <= Date.parse(openIso)) {
    return 'Close time must be after open time.';
  }
  return null;
}
