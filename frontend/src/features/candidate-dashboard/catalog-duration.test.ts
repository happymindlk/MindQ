import { describe, expect, it } from 'vitest';
import {
  catalogDurationSeconds,
  resolveTestDurationSeconds,
} from './catalog-duration';

describe('catalogDurationSeconds', () => {
  it.each([
    ['IPIP Interpersonal Circumplex (IPIP-IPC)', 270],
    ['Personal Initiative Scale', 120],
    ['Situational Judgment Test', 300],
    ['CogniCheck (based on ICAR-16)', 1200],
    ['Cognitive Reflection Test', 180],
    ['Mini-IPIP (Big Five, 20 items)', 240],
    ['IPIP-HEXACO Honesty-Humility', 330],
  ])('maps %s → %i s', (title, seconds) => {
    expect(catalogDurationSeconds(title)).toBe(seconds);
  });

  it('returns null for unknown titles', () => {
    expect(catalogDurationSeconds('Custom SQL Screen')).toBeNull();
    expect(catalogDurationSeconds(null)).toBeNull();
  });
});

describe('resolveTestDurationSeconds', () => {
  it('prefers API duration_seconds over catalog fallback', () => {
    expect(
      resolveTestDurationSeconds({
        title: 'Mini-IPIP',
        duration_seconds: 99,
      }),
    ).toBe(99);
  });

  it('accepts time_limit_seconds and minute aliases', () => {
    expect(resolveTestDurationSeconds({ time_limit_seconds: '180' })).toBe(180);
    expect(resolveTestDurationSeconds({ time_limit_minutes: 5 })).toBe(300);
    expect(resolveTestDurationSeconds({ duration_minutes: 20 })).toBe(1200);
  });

  it('falls back to catalog title defaults when API fields are null', () => {
    expect(
      resolveTestDurationSeconds({
        title: 'CogniCheck (based on ICAR-16)',
        duration_seconds: null,
        time_limit_seconds: null,
      }),
    ).toBe(1200);
  });
});
