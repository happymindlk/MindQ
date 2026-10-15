import { describe, expect, it } from 'vitest';
import {
  formatSriLankaDateTime,
  fromSriLankaInputValue,
  isPastInstant,
  toSriLankaInputValue,
} from './sri-lanka-time';

describe('sri-lanka-time', () => {
  it('converts a UTC instant to a +05:30 datetime-local value', () => {
    expect(toSriLankaInputValue('2026-10-15T11:30:00Z')).toBe('2026-10-15T17:00');
  });

  it('rolls over to the next Sri Lanka day', () => {
    expect(toSriLankaInputValue('2026-12-31T18:30:00Z')).toBe('2027-01-01T00:00');
  });

  it('round-trips an input value through an explicit offset', () => {
    const iso = fromSriLankaInputValue('2026-10-15T17:00');
    expect(iso).toBe('2026-10-15T17:00:00+05:30');
    expect(new Date(iso as string).toISOString()).toBe('2026-10-15T11:30:00.000Z');
    expect(toSriLankaInputValue(iso)).toBe('2026-10-15T17:00');
  });

  it('returns null or empty for blank and malformed input', () => {
    expect(fromSriLankaInputValue('')).toBeNull();
    expect(fromSriLankaInputValue(undefined)).toBeNull();
    expect(fromSriLankaInputValue('2026-02-30T10:00')).toBeNull();
    expect(fromSriLankaInputValue('2026-10-15T24:00')).toBeNull();
    expect(fromSriLankaInputValue('15/10/2026 10:00')).toBeNull();
    expect(toSriLankaInputValue(null)).toBe('');
    expect(toSriLankaInputValue('not-a-date')).toBe('');
  });

  it('formats midday, midnight and afternoon in 12-hour clock', () => {
    expect(formatSriLankaDateTime('2026-10-15T11:30:00Z')).toBe('15 Oct 2026, 5:00 PM');
    expect(formatSriLankaDateTime('2026-10-14T18:30:00Z')).toBe('15 Oct 2026, 12:00 AM');
    expect(formatSriLankaDateTime('2026-10-15T06:35:00Z')).toBe('15 Oct 2026, 12:05 PM');
    expect(formatSriLankaDateTime(null)).toBe('');
  });

  it('detects past instants inclusively', () => {
    const now = new Date('2026-10-15T06:00:00Z');
    expect(isPastInstant('2026-10-15T06:00:00Z', now)).toBe(true);
    expect(isPastInstant('2026-10-15T06:00:01Z', now)).toBe(false);
    expect(isPastInstant(null, now)).toBe(false);
  });
});
