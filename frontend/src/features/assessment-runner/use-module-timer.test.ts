import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatClock, timerTone, useModuleTimer } from './use-module-timer';

describe('timerTone', () => {
  it.each([
    // 600s total: >400 safe, >200 caution, otherwise urgent.
    [600, 600, 'safe'],
    [401, 600, 'safe'],
    [400, 600, 'caution'],
    [201, 600, 'caution'],
    [200, 600, 'urgent'],
    [1, 600, 'urgent'],
    [0, 600, 'urgent'],
    [-30, 600, 'urgent'],
    // 18-minute (1080s) example: 18–12 min safe, 12–6 min caution, <6 min urgent.
    [1080, 1080, 'safe'],
    [721, 1080, 'safe'],
    [720, 1080, 'caution'],
    [361, 1080, 'caution'],
    [360, 1080, 'urgent'],
    [121, 180, 'safe'],
    [120, 180, 'caution'],
    [61, 180, 'caution'],
    [60, 180, 'urgent'],
  ] as const)('remaining %is of %is is %s', (remaining, total, tone) => {
    expect(timerTone(remaining, total)).toBe(tone);
  });

  it('treats a non-positive duration as urgent', () => {
    expect(timerTone(10, 0)).toBe('urgent');
    expect(timerTone(10, -5)).toBe('urgent');
  });
});

describe('useModuleTimer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-05T12:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  const clock = () => Date.now();

  it('resumes from the server remaining_seconds and fires onExpire exactly once', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() =>
      useModuleTimer({ remainingSeconds: 60, onExpire, now: clock }),
    );
    expect(result.current.remainingSeconds).toBe(60);

    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(result.current.remainingSeconds).toBe(59);

    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(result.current.expired).toBe(true);
    expect(result.current.remainingSeconds).toBe(0);
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it('starts a fresh 3-minute module at exactly 3:00', () => {
    const { result } = renderHook(() => useModuleTimer({ remainingSeconds: 180, now: clock }));
    expect(formatClock(result.current.remainingSeconds ?? -1)).toBe('3:00');
  });

  it('ignores device wall-clock jumps such as a GMT+5:30 offset', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() => useModuleTimer({ remainingSeconds: 180, onExpire }));
    act(() => {
      vi.setSystemTime(new Date('2026-10-05T17:30:00Z'));
      vi.advanceTimersByTime(1_000);
    });
    expect(result.current.remainingSeconds).toBeGreaterThanOrEqual(179);
    expect(onExpire).not.toHaveBeenCalled();
  });

  it('fires onExpire immediately when the server reports zero remaining', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() =>
      useModuleTimer({ remainingSeconds: 0, onExpire, now: clock }),
    );
    expect(result.current.expired).toBe(true);
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it('delays onExpire through the write-grace window while display stays at 0:00', () => {
    const onExpire = vi.fn();
    const onDisplayExpire = vi.fn();
    const { result } = renderHook(() =>
      useModuleTimer({
        remainingSeconds: 0,
        expireRemainingSeconds: 15,
        onExpire,
        onDisplayExpire,
        now: clock,
      }),
    );
    expect(result.current.remainingSeconds).toBe(0);
    expect(result.current.expired).toBe(true);
    expect(onDisplayExpire).toHaveBeenCalledTimes(1);
    expect(onExpire).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(14_000);
    });
    expect(onExpire).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it('hard-cuts flexible timers at 00:00 and fires onExpire (no overtime)', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() =>
      useModuleTimer({ remainingSeconds: 10, onExpire, now: clock }),
    );
    act(() => {
      vi.advanceTimersByTime(15_000);
    });
    expect(result.current.expired).toBe(true);
    expect(result.current.remainingSeconds).toBe(0);
    expect(onExpire).toHaveBeenCalledTimes(1);
  });

  it('returns null remaining when untimed', () => {
    const { result } = renderHook(() => useModuleTimer({ remainingSeconds: null }));
    expect(result.current.remainingSeconds).toBeNull();
    expect(result.current.expired).toBe(false);
  });
});

describe('formatClock', () => {
  it.each([
    [0, '0:00'],
    [65, '1:05'],
    [-7, '0:00'],
  ])('%d -> %s', (seconds, expected) => {
    expect(formatClock(seconds)).toBe(expected);
  });
});
