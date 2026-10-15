import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { computeWindowState, lockedReasonFor, usePackageWindow } from './use-package-window';

const NOW = Date.parse('2026-10-15T06:00:00Z');

afterEach(() => vi.useRealTimers());

describe('computeWindowState', () => {
  it('is open with no bounds', () => {
    expect(computeWindowState(null, null, NOW)).toBe('open');
  });

  it('respects open and close boundaries inclusively at close', () => {
    expect(computeWindowState('2026-10-15T07:00:00Z', null, NOW)).toBe('not_open');
    expect(computeWindowState(null, '2026-10-15T06:00:00Z', NOW)).toBe('closed');
    expect(computeWindowState('2026-10-15T06:00:00Z', '2026-10-16T00:00:00Z', NOW)).toBe('open');
  });

  it('ignores unparseable timestamps', () => {
    expect(computeWindowState('garbage', 'also-garbage', NOW)).toBe('open');
  });
});

describe('lockedReasonFor', () => {
  it('never locks completed modules', () => {
    expect(lockedReasonFor('completed', 'closed')).toBeNull();
  });

  it('locks everything before open', () => {
    expect(lockedReasonFor('in_progress', 'not_open')).toBe('Not open yet');
  });

  it('after close only unstarted modules are locked', () => {
    expect(lockedReasonFor('not_started', 'closed')).toBe('Assessment closed');
    expect(lockedReasonFor('in_progress', 'closed')).toBeNull();
  });

  it('nothing is locked while open', () => {
    expect(lockedReasonFor('not_started', 'open')).toBeNull();
  });
});

describe('usePackageWindow', () => {
  it('flips to closed when the deadline passes while the page is open', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const close = new Date(NOW + 60_000).toISOString();
    const { result } = renderHook(() => usePackageWindow('open', null, close));
    expect(result.current).toBe('open');

    act(() => {
      vi.advanceTimersByTime(61_000);
    });
    expect(result.current).toBe('closed');
  });

  it('trusts the server verdict over the local clock on load', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const { result } = renderHook(() =>
      usePackageWindow('closed', null, new Date(NOW + 3_600_000).toISOString()),
    );
    expect(result.current).toBe('closed');
  });

  it('falls back to local computation when the server omits window_state', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const { result } = renderHook(() =>
      usePackageWindow(undefined, null, new Date(NOW - 1000).toISOString()),
    );
    expect(result.current).toBe('closed');
  });
});
