import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  createDraftSaveController,
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
