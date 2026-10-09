import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_IDLE_TIMEOUT_MS, LAST_ACTIVITY_STORAGE_KEY, useIdleTimer } from './use-idle-timer';

const MINUTE = 60 * 1000;

function fire(type: string) {
  act(() => {
    document.dispatchEvent(new Event(type));
  });
}

describe('useIdleTimer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-07T09:00:00Z'));
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('fires exactly once after 15 minutes of inactivity', () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleTimer({ onIdle }));

    act(() => {
      vi.advanceTimersByTime(DEFAULT_IDLE_TIMEOUT_MS - 1);
    });
    expect(onIdle).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onIdle).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(DEFAULT_IDLE_TIMEOUT_MS * 3);
    });
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it.each(['mousemove', 'keydown', 'click', 'scroll'])('%s activity pushes the deadline out', (eventName) => {
    const onIdle = vi.fn();
    renderHook(() => useIdleTimer({ onIdle }));

    act(() => {
      vi.advanceTimersByTime(10 * MINUTE);
    });
    fire(eventName);
    act(() => {
      vi.advanceTimersByTime(10 * MINUTE);
    });
    expect(onIdle).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(5 * MINUTE);
    });
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('counts scroll events from nested containers that do not bubble', () => {
    const onIdle = vi.fn();
    const inner = document.createElement('div');
    document.body.appendChild(inner);
    renderHook(() => useIdleTimer({ onIdle, timeoutMs: 2 * MINUTE }));

    act(() => {
      vi.advanceTimersByTime(MINUTE + 30_000);
    });
    act(() => {
      inner.dispatchEvent(new Event('scroll', { bubbles: false }));
    });
    act(() => {
      vi.advanceTimersByTime(MINUTE);
    });
    expect(onIdle).not.toHaveBeenCalled();
    inner.remove();
  });

  it('throttles localStorage writes from high-frequency activity', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    renderHook(() => useIdleTimer({ onIdle: vi.fn() }));
    setItem.mockClear();

    for (let i = 0; i < 50; i += 1) {
      fire('mousemove');
      act(() => {
        vi.advanceTimersByTime(10);
      });
    }
    expect(setItem.mock.calls.length).toBeLessThanOrEqual(1);
    setItem.mockRestore();
  });

  it('activity reported by another tab postpones the lock', () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleTimer({ onIdle }));

    act(() => {
      vi.advanceTimersByTime(14 * MINUTE);
    });
    act(() => {
      window.dispatchEvent(
        new StorageEvent('storage', { key: LAST_ACTIVITY_STORAGE_KEY, newValue: String(Date.now()) }),
      );
    });
    act(() => {
      vi.advanceTimersByTime(2 * MINUTE);
    });
    expect(onIdle).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(13 * MINUTE);
    });
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('ignores malformed cross-tab values', () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleTimer({ onIdle }));

    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: LAST_ACTIVITY_STORAGE_KEY, newValue: 'garbage' }));
      vi.advanceTimersByTime(DEFAULT_IDLE_TIMEOUT_MS);
    });
    expect(onIdle).toHaveBeenCalledTimes(1);
  });

  it('locks on visibilitychange when a throttled tab wakes past the deadline', () => {
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    const onIdle = vi.fn();
    renderHook(() => useIdleTimer({ onIdle }));

    // Simulate a suspended tab: wall clock jumps without timers firing.
    vi.setSystemTime(Date.now() + DEFAULT_IDLE_TIMEOUT_MS + MINUTE);
    fire('visibilitychange');
    expect(onIdle).toHaveBeenCalledTimes(1);
    visibility.mockRestore();
  });

  it('never fires when disabled', () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleTimer({ onIdle, enabled: false }));

    act(() => {
      vi.advanceTimersByTime(DEFAULT_IDLE_TIMEOUT_MS * 2);
    });
    expect(onIdle).not.toHaveBeenCalled();
  });

  it('reset() re-arms the timer after it has fired', () => {
    const onIdle = vi.fn();
    const { result } = renderHook(() => useIdleTimer({ onIdle, timeoutMs: MINUTE }));

    act(() => {
      vi.advanceTimersByTime(MINUTE);
    });
    expect(onIdle).toHaveBeenCalledTimes(1);
    expect(result.current.getRemainingMs()).toBe(0);

    act(() => {
      result.current.reset();
    });
    expect(result.current.getRemainingMs()).toBe(MINUTE);
    act(() => {
      vi.advanceTimersByTime(MINUTE);
    });
    expect(onIdle).toHaveBeenCalledTimes(2);
  });

  it('uses the latest onIdle callback without re-arming', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = renderHook(({ cb }) => useIdleTimer({ onIdle: cb }), {
      initialProps: { cb: first },
    });
    rerender({ cb: second });

    act(() => {
      vi.advanceTimersByTime(DEFAULT_IDLE_TIMEOUT_MS);
    });
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('removes listeners and timers on unmount', () => {
    const onIdle = vi.fn();
    const removeSpy = vi.spyOn(document, 'removeEventListener');
    const { unmount } = renderHook(() => useIdleTimer({ onIdle }));
    unmount();

    const removed = removeSpy.mock.calls.map(([name]) => name);
    expect(removed).toEqual(expect.arrayContaining(['mousemove', 'keydown', 'click', 'scroll', 'visibilitychange']));

    act(() => {
      vi.advanceTimersByTime(DEFAULT_IDLE_TIMEOUT_MS * 2);
    });
    expect(onIdle).not.toHaveBeenCalled();
    removeSpy.mockRestore();
  });

  it('keeps working when localStorage throws', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    const onIdle = vi.fn();
    renderHook(() => useIdleTimer({ onIdle, timeoutMs: MINUTE }));

    fire('click');
    act(() => {
      vi.advanceTimersByTime(MINUTE);
    });
    expect(onIdle).toHaveBeenCalledTimes(1);
    setItem.mockRestore();
  });
});
