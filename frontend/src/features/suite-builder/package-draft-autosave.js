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
 * Create a timer + AbortController pair for debounced draft saves.
 * Debounce cleanup should only call `clearScheduled` so an in-flight save can
 * finish while the user keeps typing. Publish must call `flushDraftForPublish`
 * so a pending debounce cannot start a second save and abort the flush.
 * Call `cancelAll` on publish success and on unmount so leftover timers or
 * fetches cannot fire a PUT after the editor is gone.
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
 * Save the latest draft once before publish.
 *
 * `beginRequest` aborts whatever save is already in flight. If the 900ms
 * debounce is still armed when publish starts, that timer can call persist
 * again mid-flush, abort the flush, and leave publish with a stale package id.
 * Clearing the timer first keeps this flush as the only request.
 *
 * @template T
 * @param {{ clearScheduled: () => void }} controller
 * @param {() => Promise<T>} persist
 * @returns {Promise<T>}
 */
export function flushDraftForPublish(controller, persist) {
  controller.clearScheduled();
  return persist();
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
