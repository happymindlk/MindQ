import { describe, expect, it } from 'vitest';
import { formatDuration, formatDurationBadge } from './module';

describe('formatDurationBadge', () => {
  it('formats whole minutes without rounding up', () => {
    expect(formatDurationBadge(600)).toBe('⏱ 10 mins');
    expect(formatDurationBadge(60)).toBe('⏱ 1 min');
    expect(formatDurationBadge(240)).toBe('⏱ 4 mins');
  });

  it('keeps exact seconds for fractional minutes (270s → 4m 30s, not 5 mins)', () => {
    expect(formatDurationBadge(270)).toBe('⏱ 4m 30s');
    expect(formatDurationBadge(90)).toBe('⏱ 1m 30s');
    expect(formatDurationBadge(45)).toBe('⏱ 45s');
  });

  it('returns null for untimed / invalid values', () => {
    expect(formatDurationBadge(null)).toBeNull();
    expect(formatDurationBadge(0)).toBeNull();
    expect(formatDurationBadge(undefined)).toBeNull();
  });
});

describe('formatDuration', () => {
  it('matches precise minute/second breakdown', () => {
    expect(formatDuration(270)).toBe('4 min 30 s');
    expect(formatDuration(600)).toBe('10 min');
  });
});
