import { describe, expect, it } from 'vitest';
import { extendedInputValue, validateDeadline } from './use-extend-deadline';

const NOW = new Date('2026-10-15T06:00:00Z');

describe('extendedInputValue', () => {
  it('extends from the current deadline when it is in the future', () => {
    expect(extendedInputValue('2026-10-20T11:30:00Z', 3, NOW)).toBe('2026-10-23T17:00');
  });

  it('extends from now when the deadline already passed', () => {
    expect(extendedInputValue('2026-10-01T00:00:00Z', 1, NOW)).toBe('2026-10-16T11:30');
  });

  it('extends from now when no deadline exists', () => {
    expect(extendedInputValue(null, 7, NOW)).toBe('2026-10-22T11:30');
  });
});

describe('validateDeadline', () => {
  it('requires a value', () => {
    expect(validateDeadline(null, null, NOW)).toMatch(/pick a date/i);
  });

  it('rejects past deadlines', () => {
    expect(validateDeadline('2026-10-15T11:00:00+05:30', null, NOW)).toMatch(/future/);
  });

  it('rejects a deadline before the open time', () => {
    expect(
      validateDeadline('2026-10-16T09:00:00+05:30', '2026-10-17T00:00:00Z', NOW),
    ).toMatch(/after the package open time/);
  });

  it('accepts a future deadline after open', () => {
    expect(validateDeadline('2026-10-18T09:00:00+05:30', '2026-10-10T00:00:00Z', NOW)).toBeNull();
  });
});
