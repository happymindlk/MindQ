import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatClock, timerTone, useModuleTimer } from './use-module-timer';

describe('timerTone', () => {
  it.each([
    [600, 600, 'safe'],
    [151, 600, 'safe'],
    [150, 600, 'urgent'],
    [1, 600, 'urgent'],
    [0, 600, 'urgent'],
    [-30, 600, 'urgent'],
    [46, 180, 'safe'],
    [45, 180, 'urgent'],
  ] as const)('remaining %is of %is is %s', (remaining, total, tone) => {
    expect(timerTone(remaining, total)).toBe(tone);
  });

  it('treats a non-positive duration as urgent', () => {
    expect(timerTone(10, 0)).toBe('urgent');
  });
});

describe('useModuleTimer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-05T12:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  it('resumes from the server started_at and fires onExpire exactly once in strict mode', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() =>
      useModuleTimer({
        durationSeconds: 180,
        timerMode: 'strict',
        startedAt: '2026-10-05T11:58:00Z',
        onExpire,
      }),
    );
    expect(result.current.remainingSeconds).toBe(60);

    act(() => {
      vi.advanceTimersByTime(61_000);
    });
    expect(result.current.expired).toBe(true);
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it('counts into overtime in flexible mode without expiring', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() =>
      useModuleTimer({ durationSeconds: 10, timerMode: 'flexible', startedAt: null, onExpire }),
    );
    act(() => {
      vi.advanceTimersByTime(15_000);
    });
    expect(result.current.overtime).toBe(true);
    expect(result.current.expired).toBe(false);
    expect(result.current.remainingSeconds).toBe(-5);
    expect(onExpire).not.toHaveBeenCalled();
  });

  it('returns null remaining when untimed', () => {
    const { result } = renderHook(() =>
      useModuleTimer({ durationSeconds: null, timerMode: 'strict', startedAt: null }),
    );
    expect(result.current.remainingSeconds).toBeNull();
    expect(result.current.expired).toBe(false);
  });
});

describe('formatClock', () => {
  it.each([
    [0, '0:00'],
    [65, '1:05'],
    [-7, '-0:07'],
  ])('%d -> %s', (seconds, expected) => {
    expect(formatClock(seconds)).toBe(expected);
  });
});
