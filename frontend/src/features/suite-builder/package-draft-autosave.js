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
