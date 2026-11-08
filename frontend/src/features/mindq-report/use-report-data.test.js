import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NARRATIVE_POLL_BUDGET_MS, narrativePollDelay, useReportData } from './use-report-data';

const GENERATING = { synthesis_status: 'generating', executive_summary: '' };
const READY = { synthesis_status: 'ok', executive_summary: 'Strong analytical candidate.' };

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function advance(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function setHidden(hidden) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
}

beforeEach(() => {
  vi.useFakeTimers();
  setHidden(false);
});

afterEach(() => {
  vi.useRealTimers();
  setHidden(false);
});

describe('useReportData narrative polling', () => {
  it('renders scores immediately and polls until the narrative arrives', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(GENERATING)
      .mockResolvedValueOnce(GENERATING)
      .mockResolvedValueOnce(READY);
    const { result } = renderHook(() => useReportData('cand-1', fetch));
    await flush();

    expect(result.current.loading).toBe(false);
    expect(result.current.data).toEqual(GENERATING);
    expect(result.current.narrativeLoading).toBe(true);

    await advance(narrativePollDelay(0));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.loading).toBe(false);

    await advance(narrativePollDelay(1));
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(result.current.data).toEqual(READY);
    expect(result.current.narrativeLoading).toBe(false);

    await advance(60000);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it.each(['ok', 'pending', 'failed', 'skipped'])('does not poll when status is %s', async (status) => {
    const fetch = vi.fn().mockResolvedValue({ synthesis_status: status });
    const { result } = renderHook(() => useReportData('cand-1', fetch));
    await flush();
    await advance(60000);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(result.current.narrativeLoading).toBe(false);
  });

  it('gives up after the poll budget so a stuck job cannot poll forever', async () => {
    const fetch = vi.fn().mockResolvedValue(GENERATING);
    const { result } = renderHook(() => useReportData('cand-1', fetch));
    await flush();

    for (let waited = 0; waited < NARRATIVE_POLL_BUDGET_MS + 30000; waited += 1000) {
      await advance(1000);
    }
    const callsAtBudget = fetch.mock.calls.length;
    expect(callsAtBudget).toBeGreaterThan(5);
    expect(callsAtBudget).toBeLessThan(25);
    expect(result.current.narrativeLoading).toBe(false);
    expect(result.current.data).toEqual(GENERATING);

    for (let waited = 0; waited < 120000; waited += 1000) {
      await advance(1000);
    }
    expect(fetch).toHaveBeenCalledTimes(callsAtBudget);
  });

  it('pauses while the tab is hidden without spending the budget', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(GENERATING).mockResolvedValueOnce(READY);
    const { result } = renderHook(() => useReportData('cand-1', fetch));
    await flush();

    setHidden(true);
    for (let waited = 0; waited < NARRATIVE_POLL_BUDGET_MS * 2; waited += 1000) {
      await advance(1000);
    }
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(result.current.narrativeLoading).toBe(true);

    setHidden(false);
    await advance(narrativePollDelay(0));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(result.current.data).toEqual(READY);
  });

  it('stops polling on a failed re-fetch but keeps the loaded scores', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(GENERATING)
      .mockRejectedValueOnce(new Error('Too many requests. Try again later.'));
    const { result } = renderHook(() => useReportData('cand-1', fetch));
    await flush();

    await advance(narrativePollDelay(0));
    await flush();
    expect(result.current.error).toBeNull();
    expect(result.current.data).toEqual(GENERATING);
    expect(result.current.narrativeLoading).toBe(false);

    await advance(60000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('restarts polling on manual retry', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(GENERATING).mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useReportData('cand-1', fetch));
    await flush();
    await advance(narrativePollDelay(0));
    await flush();
    expect(result.current.narrativeLoading).toBe(false);

    fetch.mockResolvedValueOnce(GENERATING).mockResolvedValueOnce(READY);
    act(() => result.current.retry());
    await flush();
    expect(result.current.narrativeLoading).toBe(true);
    await advance(narrativePollDelay(0));
    expect(result.current.data).toEqual(READY);
  });
});
