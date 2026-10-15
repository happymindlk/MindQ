import { describe, expect, it } from 'vitest';
import { scheduleWindowError } from './schedule-window';

describe('scheduleWindowError', () => {
  it('allows both blank or only one bound', () => {
    expect(scheduleWindowError('', '')).toBeNull();
    expect(scheduleWindowError('2026-10-15T09:00', '')).toBeNull();
    expect(scheduleWindowError('', '2026-10-20T17:00')).toBeNull();
  });

  it('rejects close at or before open', () => {
    expect(scheduleWindowError('2026-10-15T09:00', '2026-10-15T09:00')).toMatch(/after open/);
    expect(scheduleWindowError('2026-10-15T09:00', '2026-10-14T09:00')).toMatch(/after open/);
  });

  it('flags partially typed or impossible dates', () => {
    expect(scheduleWindowError('2026-02-30T09:00', '')).toMatch(/open time is not a valid/i);
    expect(scheduleWindowError('', '2026-13-01T09:00')).toMatch(/close time is not a valid/i);
  });

  it('accepts a valid window', () => {
    expect(scheduleWindowError('2026-10-15T09:00', '2026-10-20T17:00')).toBeNull();
  });
});
