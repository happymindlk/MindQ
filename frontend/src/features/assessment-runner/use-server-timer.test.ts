import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  computeServerOffsetMs,
  remainingFromDeadline,
  useServerTimer,
} from './use-server-timer';

describe('computeServerOffsetMs / remainingFromDeadline', () => {
  it('computes offset so server_now aligns wall clocks', () => {
    const clientNow = Date.parse('2026-11-13T12:00:00.000Z');
    const serverNow = '2026-11-13T12:00:05.000Z';
    expect(computeServerOffsetMs(serverNow, clientNow)).toBe(5000);
  });

  it('deducts elapsed wall-clock time when re-entering after leaving', () => {
    const expiresAt = '2026-11-13T12:03:00.000Z';
    const offset = 0;
    // Mount at start → 180s left.
    expect(remainingFromDeadline(expiresAt, offset, Date.parse('2026-11-13T12:00:00.000Z'))).toBe(
      180,
    );
    // Leave for 45s and remount → 135s left (not a paused counter).
    expect(remainingFromDeadline(expiresAt, offset, Date.parse('2026-11-13T12:00:45.000Z'))).toBe(
      135,
    );
  });
});

describe('useServerTimer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-13T12:00:00.000Z'));
  });
  afterEach(() => vi.useRealTimers());

  it('counts down from expires_at using wall clock + server offset', () => {
    const onExpire = vi.fn();
    const { result } = renderHook(() =>
      useServerTimer({
        expiresAt: '2026-11-13T12:01:00.000Z',
        writeExpiresAt: '2026-11-13T12:01:30.000Z',
        serverNow: '2026-11-13T12:00:00.000Z',
        onExpire,
      }),
    );
    expect(result.current.remainingSeconds).toBe(60);

    act(() => {
      vi.advanceTimersByTime(15_000);
    });
    expect(result.current.remainingSeconds).toBe(45);
  });

  it('resyncs remaining time on visibilitychange after backgrounding', () => {
    const { result } = renderHook(() =>
      useServerTimer({
        expiresAt: '2026-11-13T12:02:00.000Z',
        serverNow: '2026-11-13T12:00:00.000Z',
      }),
    );
    expect(result.current.remainingSeconds).toBe(120);

    act(() => {
      vi.setSystemTime(new Date('2026-11-13T12:00:40.000Z'));
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(result.current.remainingSeconds).toBe(80);
  });

  it('fires onExpire at write_expires_at (grace) after display hits zero', () => {
    const onExpire = vi.fn();
    const onDisplayExpire = vi.fn();
    renderHook(() =>
      useServerTimer({
        expiresAt: '2026-11-13T12:00:10.000Z',
        writeExpiresAt: '2026-11-13T12:00:20.000Z',
        serverNow: '2026-11-13T12:00:00.000Z',
        onExpire,
        onDisplayExpire,
      }),
    );

    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(onDisplayExpire).toHaveBeenCalledTimes(1);
    expect(onExpire).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(onExpire).toHaveBeenCalledTimes(1);
  });
});
