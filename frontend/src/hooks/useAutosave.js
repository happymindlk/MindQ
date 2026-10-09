import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * Debounced remote save with an explicit flush for question navigation.
 *
 * `enabled` stays false during hydration so mounting with recovered answers
 * does not fire a write. `flush` cancels the timer and saves the *current*
 * data immediately — callers must invoke it before changing the active question.
 *
 * @param {(data: unknown) => Promise<void>} saveFunction
 * @param {unknown} data
 * @param {number} delay
 * @param {boolean} enabled
 */
export function useAutosave(saveFunction, data, delay = 5000, enabled = true) {
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);
  const skipNext = useRef(true);
  const saveFnRef = useRef(saveFunction);
  const dataRef = useRef(data);

  saveFnRef.current = saveFunction;
  dataRef.current = data;

  const runSave = useCallback(async () => {
    setIsSaving(true);
    setError(null);
    try {
      await saveFnRef.current(dataRef.current);
      setLastSaved(new Date());
    } catch (err) {
      setError(err.message || 'Failed to save');
      throw err;
    } finally {
      setIsSaving(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      skipNext.current = true;
      return undefined;
    }
    if (skipNext.current) {
      skipNext.current = false;
      return undefined;
    }

    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    timerRef.current = setTimeout(() => {
      runSave().catch(() => {
        // Error is stored on the hook; callers of flush rethrow separately.
      });
    }, delay);

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [data, delay, enabled, runSave]);

  const flush = useCallback(async () => {
    if (!enabled) return;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    await runSave();
  }, [enabled, runSave]);

  return { isSaving, lastSaved, error, flush };
}
