import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createDraftSaveController,
  flushDraftForPublish,
  isAbortError,
  isPackageSaveAllowed,
} from './package-draft-autosave';

describe('isPackageSaveAllowed', () => {
  it('allows draft packages', () => {
    expect(isPackageSaveAllowed({ status: 'draft' })).toBe(true);
    expect(isPackageSaveAllowed({ status: 'DRAFT' })).toBe(true);
    expect(isPackageSaveAllowed({})).toBe(true);
  });

  it('blocks published status regardless of casing', () => {
    expect(isPackageSaveAllowed({ status: 'published' })).toBe(false);
    expect(isPackageSaveAllowed({ status: 'PUBLISHED' })).toBe(false);
  });

  it('blocks when isLocked is true even if status is draft', () => {
    expect(isPackageSaveAllowed({ status: 'draft', isLocked: true })).toBe(false);
  });
});

describe('createDraftSaveController', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('cancels a pending debounced callback', () => {
    vi.useFakeTimers();
    const ctrl = createDraftSaveController();
    const fn = vi.fn();
    ctrl.schedule(fn, 900);
    ctrl.cancelAll();
    vi.advanceTimersByTime(2000);
    expect(fn).not.toHaveBeenCalled();
  });

  it('clearScheduled only drops the timer, not the in-flight signal', () => {
    vi.useFakeTimers();
    const ctrl = createDraftSaveController();
    const fn = vi.fn();
    ctrl.schedule(fn, 900);
    const signal = ctrl.beginRequest();
    ctrl.clearScheduled();
    vi.advanceTimersByTime(2000);
    expect(fn).not.toHaveBeenCalled();
    expect(signal.aborted).toBe(false);
  });

  it('aborts the in-flight request signal on cancelAll', () => {
    const ctrl = createDraftSaveController();
    const signal = ctrl.beginRequest();
    expect(signal.aborted).toBe(false);
    ctrl.cancelAll();
    expect(signal.aborted).toBe(true);
  });

  it('replaces the previous AbortController on beginRequest', () => {
    const ctrl = createDraftSaveController();
    const first = ctrl.beginRequest();
    const second = ctrl.beginRequest();
    expect(first.aborted).toBe(true);
    expect(second.aborted).toBe(false);
  });

  it('disarms the debounce before a publish flush so the timer cannot abort it', async () => {
    vi.useFakeTimers();
    const ctrl = createDraftSaveController();
    /** @type {AbortSignal[]} */
    const signals = [];

    const persist = vi.fn(
      () =>
        new Promise((resolve) => {
          const signal = ctrl.beginRequest();
          signals.push(signal);
          const timeoutId = window.setTimeout(() => {
            resolve(signal.aborted ? null : { id: 'pkg-1' });
          }, 1000);
          signal.addEventListener('abort', () => {
            window.clearTimeout(timeoutId);
            resolve(null);
          });
        }),
    );

    ctrl.schedule(() => {
      persist().catch(() => {});
    }, 900);

    const flushPromise = flushDraftForPublish(ctrl, persist);
    await vi.advanceTimersByTimeAsync(1000);

    await expect(flushPromise).resolves.toEqual({ id: 'pkg-1' });
    expect(persist).toHaveBeenCalledTimes(1);
    expect(signals[0].aborted).toBe(false);
  });
});

describe('isAbortError', () => {
  it('detects DOMException AbortError', () => {
    expect(isAbortError(new DOMException('Aborted', 'AbortError'))).toBe(true);
  });

  it('ignores unrelated errors', () => {
    expect(isAbortError(new Error('network'))).toBe(false);
    expect(isAbortError(null)).toBe(false);
  });
});
