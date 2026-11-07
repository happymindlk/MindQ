import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../lib/api-error';
import {
  createDraftIdGate,
  createDraftSaveController,
  createPendingWriteTracker,
  isAbortError,
  isPackageLockedError,
  isPackageSaveAllowed,
} from './package-draft-autosave';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('isPackageLockedError', () => {
  it('matches the 409 lock raised by draft saves and add-template', () => {
    expect(isPackageLockedError(new ApiError('Package is published and locked', 409))).toBe(true);
  });

  it('matches the 409 raised by a duplicate publish', () => {
    expect(isPackageLockedError(new ApiError('Package is already published', 409))).toBe(true);
  });

  it('ignores the add-template "already attached" 409', () => {
    expect(isPackageLockedError(new ApiError('Template already attached to package', 409))).toBe(
      false,
    );
  });

  it('ignores lock wording on non-409 statuses', () => {
    expect(isPackageLockedError(new ApiError('Package is published and locked', 503))).toBe(false);
    expect(isPackageLockedError(new ApiError('Package is published and locked', 0, 'NETWORK'))).toBe(
      false,
    );
  });

  it('ignores non-error values', () => {
    expect(isPackageLockedError(null)).toBe(false);
    expect(isPackageLockedError(undefined)).toBe(false);
    expect(isPackageLockedError('Package is published and locked')).toBe(false);
    expect(isPackageLockedError(new Error('Package is published and locked'))).toBe(false);
  });
});

describe('createPendingWriteTracker', () => {
  it('settles immediately with nothing pending', async () => {
    const tracker = createPendingWriteTracker();
    await expect(tracker.settle()).resolves.toBeUndefined();
    expect(tracker.size).toBe(0);
  });

  it('waits for every in-flight write, including rejected ones', async () => {
    const tracker = createPendingWriteTracker();
    const save = deferred();
    const addTemplate = deferred();
    const saveResult = tracker.track(save.promise);
    const addResult = tracker.track(addTemplate.promise).catch((err) => err);

    let settled = false;
    const settling = tracker.settle().then(() => {
      settled = true;
    });

    save.resolve({ id: 'pkg-1' });
    await saveResult;
    expect(settled).toBe(false);

    const failure = new ApiError('Service unavailable', 503);
    addTemplate.reject(failure);
    await settling;
    expect(settled).toBe(true);
    expect(tracker.size).toBe(0);
    await expect(addResult).resolves.toBe(failure);
  });

  it('returns the original promise so callers still see rejections', async () => {
    const tracker = createPendingWriteTracker();
    const err = new ApiError('Package is published and locked', 409);
    await expect(tracker.track(Promise.reject(err))).rejects.toBe(err);
    await tracker.settle();
    expect(tracker.size).toBe(0);
  });

  it('also waits for writes enqueued while settling', async () => {
    const tracker = createPendingWriteTracker();
    const first = deferred();
    const followUp = deferred();
    tracker.track(first.promise);

    let settled = false;
    const settling = tracker.settle().then(() => {
      settled = true;
    });

    first.promise.then(() => tracker.track(followUp.promise));
    first.resolve();
    await first.promise;
    await Promise.resolve();
    expect(settled).toBe(false);

    followUp.resolve();
    await settling;
    expect(settled).toBe(true);
  });
});

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

describe('createDraftIdGate', () => {
  it('runs create only once when ensureCreated is called concurrently', async () => {
    const gate = createDraftIdGate(null);
    const createFn = vi.fn(async () => {
      await new Promise((r) => setTimeout(r, 20));
      return { id: 'draft-1' };
    });

    const [a, b] = await Promise.all([gate.ensureCreated(createFn), gate.ensureCreated(createFn)]);
    expect(a).toBe('draft-1');
    expect(b).toBe('draft-1');
    expect(createFn).toHaveBeenCalledTimes(1);
    expect(gate.getId()).toBe('draft-1');
  });

  it('skips create when an id is already known', async () => {
    const gate = createDraftIdGate('existing');
    const createFn = vi.fn(async () => ({ id: 'new' }));
    await expect(gate.ensureCreated(createFn)).resolves.toBe('existing');
    expect(createFn).not.toHaveBeenCalled();
  });
});
