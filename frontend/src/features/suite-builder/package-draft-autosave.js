/**
 * Guards and controllers for suite-builder draft auto-save.
 * Published / locked packages must never schedule or fire PUT updates.
 */

/**
 * Whether a package may be auto-saved or manually persisted as a draft.
 *
 * @param {{ status?: string | null, isLocked?: boolean | null }} packageState
 * @returns {boolean}
 */
export function isPackageSaveAllowed({ status, isLocked } = {}) {
  if (isLocked === true) return false;
  const normalized = String(status ?? '').trim().toUpperCase();
  if (normalized === 'PUBLISHED') return false;
  return true;
}

/**
 * Single-draft retention gate: concurrent first-saves share one POST, then reuse the id.
 *
 * Tab blur / visibility races used to fire multiple POSTs with the same title because
 * React state `packageId` was still null while the first create was in flight.
 *
 * @param {string | null} [initialId]
 * @returns {{
 *   getId: () => string | null,
 *   setId: (id: string | null) => void,
 *   ensureCreated: (createFn: () => Promise<{ id: string }>) => Promise<string>,
 * }}
 */
export function createDraftIdGate(initialId = null) {
  /** @type {string | null} */
  let currentId = initialId || null;
  /** @type {Promise<string> | null} */
  let createPromise = null;

  return {
    getId() {
      return currentId;
    },

    setId(id) {
      currentId = id || null;
    },

    /**
     * Return the existing draft id, or run ``createFn`` once and cache its id.
     *
     * @param {() => Promise<{ id: string }>} createFn
     * @returns {Promise<string>}
     */
    async ensureCreated(createFn) {
      if (currentId) return currentId;
      if (createPromise) return createPromise;
      createPromise = Promise.resolve()
        .then(createFn)
        .then((saved) => {
          const id = saved?.id ? String(saved.id) : '';
          if (!id) throw new Error('Draft save returned no id');
          currentId = id;
          return id;
        })
        .finally(() => {
          createPromise = null;
        });
      return createPromise;
    },
  };
}

/**
 * Create a timer + AbortController pair for debounced draft saves.
 * Debounce cleanup should only call `clearScheduled` so an in-flight save can
 * finish while the user keeps typing. Call `cancelAll` on publish success and
 * on unmount so leftover timers/fetches cannot fire a PUT after the editor is gone.
 *
 * @returns {{
 *   schedule: (fn: () => void, delayMs: number) => void,
 *   clearScheduled: () => void,
 *   beginRequest: () => AbortSignal,
 *   cancelAll: () => void,
 * }}
 */
export function createDraftSaveController() {
  let timerId = null;
  /** @type {AbortController | null} */
  let abortController = null;

  const clearTimer = () => {
    if (timerId != null) {
      window.clearTimeout(timerId);
      timerId = null;
    }
  };

  const abortInFlight = () => {
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
  };

  return {
    schedule(fn, delayMs) {
      clearTimer();
      timerId = window.setTimeout(() => {
        timerId = null;
        fn();
      }, delayMs);
    },

    clearScheduled() {
      clearTimer();
    },

    beginRequest() {
      abortInFlight();
      abortController = new AbortController();
      return abortController.signal;
    },

    cancelAll() {
      clearTimer();
      abortInFlight();
    },
  };
}

/**
 * Tracks in-flight draft writes (PUT saves, add-template calls) so publish can
 * wait for every one of them to land before locking the package server-side.
 *
 * @returns {{
 *   track: <T>(promise: Promise<T>) => Promise<T>,
 *   settle: () => Promise<void>,
 *   readonly size: number,
 * }}
 */
export function createPendingWriteTracker() {
  /** @type {Set<Promise<unknown>>} */
  const pending = new Set();

  return {
    track(promise) {
      pending.add(promise);
      const remove = () => {
        pending.delete(promise);
      };
      promise.then(remove, remove);
      return promise;
    },

    async settle() {
      // Loop: a settling write can enqueue a follow-up (e.g. PUT after first create).
      while (pending.size > 0) {
        await Promise.allSettled(Array.from(pending));
      }
    },

    get size() {
      return pending.size;
    },
  };
}

// 409 is shared with "template already attached", so match the lock wording too.
const PACKAGE_LOCKED_PATTERN = /published and locked|already published/i;

/**
 * True when the backend rejected a write because the package is already published.
 *
 * @param {unknown} err
 * @returns {boolean}
 */
export function isPackageLockedError(err) {
  if (!err || typeof err !== 'object') return false;
  if (!('status' in err) || err.status !== 409) return false;
  const message = 'message' in err ? String(err.message ?? '') : '';
  return PACKAGE_LOCKED_PATTERN.test(message);
}

/**
 * True when a rejected save should be ignored (user navigated away / publish locked).
 *
 * @param {unknown} err
 * @returns {boolean}
 */
export function isAbortError(err) {
  return (
    (typeof DOMException !== 'undefined' && err instanceof DOMException && err.name === 'AbortError') ||
    (Boolean(err) && typeof err === 'object' && 'name' in err && err.name === 'AbortError')
  );
}
