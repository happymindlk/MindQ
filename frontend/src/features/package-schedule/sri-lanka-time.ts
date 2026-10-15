/**
 * Sri Lanka (GMT+5:30) date helpers for package open/close windows.
 *
 * Sri Lanka observes no daylight saving, so a fixed offset is exact and the
 * output is identical regardless of the admin's or candidate's device timezone.
 */

export const SRI_LANKA_OFFSET_MINUTES = 330;
export const SRI_LANKA_ZONE_LABEL = 'Sri Lanka Time - GMT+5:30';

const OFFSET_MS = SRI_LANKA_OFFSET_MINUTES * 60_000;
const INPUT_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const pad = (value: number) => String(value).padStart(2, '0');

function parseInstant(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Shift an instant so its UTC getters read Sri Lanka wall-clock fields. */
function toWallClock(date: Date): Date {
  return new Date(date.getTime() + OFFSET_MS);
}

/**
 * Convert a stored instant to a `<input type="datetime-local">` value in Sri Lanka time.
 *
 * @returns `YYYY-MM-DDTHH:mm`, or `''` for empty/invalid input.
 */
export function toSriLankaInputValue(iso: string | null | undefined): string {
  const date = parseInstant(iso);
  if (!date) return '';
  const w = toWallClock(date);
  return `${w.getUTCFullYear()}-${pad(w.getUTCMonth() + 1)}-${pad(w.getUTCDate())}T${pad(
    w.getUTCHours(),
  )}:${pad(w.getUTCMinutes())}`;
}

/**
 * Interpret a `datetime-local` value as Sri Lanka wall-clock time.
 *
 * @returns ISO 8601 string with an explicit `+05:30` offset, or `null` when blank/invalid.
 */
export function fromSriLankaInputValue(value: string | null | undefined): string | null {
  const match = INPUT_PATTERN.exec((value ?? '').trim());
  if (!match) return null;
  const [, y, mo, d, h, mi] = match;
  const month = Number(mo);
  const day = Number(d);
  const hour = Number(h);
  const minute = Number(mi);
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59) return null;
  const probe = new Date(Date.UTC(Number(y), month - 1, day));
  if (probe.getUTCMonth() !== month - 1) return null;
  return `${y}-${mo}-${d}T${h}:${mi}:00+05:30`;
}

/**
 * Human-readable Sri Lanka date/time, e.g. `15 Oct 2026, 5:00 PM`.
 *
 * @returns Formatted string, or `''` for empty/invalid input.
 */
export function formatSriLankaDateTime(iso: string | null | undefined): string {
  const date = parseInstant(iso);
  if (!date) return '';
  const w = toWallClock(date);
  const hours24 = w.getUTCHours();
  const hours12 = hours24 % 12 === 0 ? 12 : hours24 % 12;
  const meridiem = hours24 < 12 ? 'AM' : 'PM';
  return `${w.getUTCDate()} ${MONTHS[w.getUTCMonth()]} ${w.getUTCFullYear()}, ${hours12}:${pad(
    w.getUTCMinutes(),
  )} ${meridiem}`;
}

/** True when `iso` is a valid instant at or before `now`. */
export function isPastInstant(iso: string | null | undefined, now: Date = new Date()): boolean {
  const date = parseInstant(iso);
  return date !== null && date.getTime() <= now.getTime();
}
