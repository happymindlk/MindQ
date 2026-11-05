import { describe, expect, it } from 'vitest';
import { formatDeadlineTimestamp } from './format-deadline';

describe('formatDeadlineTimestamp', () => {
  it('returns No fixed deadline when unset', () => {
    expect(formatDeadlineTimestamp(null)).toBe('No fixed deadline');
    expect(formatDeadlineTimestamp(undefined)).toBe('No fixed deadline');
    expect(formatDeadlineTimestamp('')).toBe('No fixed deadline');
  });

  it('formats a close time in Sri Lanka time like the SES invite email', () => {
    // 23:59 UTC → 05:29 next day in GMT+5:30
    expect(formatDeadlineTimestamp('2026-10-30T23:59:00Z')).toBe(
      '31 Oct 2026, 5:29 AM (Sri Lanka Time - GMT+5:30)',
    );
  });

  it('preserves the Sri Lanka calendar day for a late-evening local deadline', () => {
    // Admin picks Nov 12, 2026 11:59 PM SLT → stored as 18:29 UTC same day
    expect(formatDeadlineTimestamp('2026-11-12T18:29:00Z')).toBe(
      '12 Nov 2026, 11:59 PM (Sri Lanka Time - GMT+5:30)',
    );
  });

  it('treats invalid input as no deadline', () => {
    expect(formatDeadlineTimestamp('not-a-date')).toBe('No fixed deadline');
  });
});
