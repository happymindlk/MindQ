import { describe, expect, it } from 'vitest';
import { formatDeadlineTimestamp } from './format-deadline';

describe('formatDeadlineTimestamp', () => {
  it('returns No fixed deadline when unset', () => {
    expect(formatDeadlineTimestamp(null)).toBe('No fixed deadline');
    expect(formatDeadlineTimestamp(undefined)).toBe('No fixed deadline');
    expect(formatDeadlineTimestamp('')).toBe('No fixed deadline');
  });

  it('formats a UTC close time like the SES invite email', () => {
    expect(formatDeadlineTimestamp('2026-10-30T23:59:00Z')).toBe(
      'October 30, 2026 at 11:59 PM UTC',
    );
  });

  it('treats invalid input as no deadline', () => {
    expect(formatDeadlineTimestamp('not-a-date')).toBe('No fixed deadline');
  });
});
