import { useCallback, useEffect, useState } from 'react';
import { adminApi } from '../../lib/adminApi';
import { fromSriLankaInputValue, toSriLankaInputValue } from './sri-lanka-time';

const DAY_MS = 86400000;

/**
 * Input value N days after the later of the current deadline and now, so a
 * quick-extend on an already expired suite never lands in the past.
 *
 * @param {string | null | undefined} closeTime
 * @param {number} days
 * @param {Date} [now]
 * @returns {string} datetime-local value in Sri Lanka time.
 */
export function extendedInputValue(closeTime, days, now = new Date()) {
  const current = closeTime ? new Date(closeTime).getTime() : Number.NaN;
  const base = Number.isNaN(current) ? now.getTime() : Math.max(current, now.getTime());
  return toSriLankaInputValue(new Date(base + days * DAY_MS).toISOString());
}

/**
 * Validate a proposed deadline against the package window.
 *
 * @param {string | null} closeIso Proposed deadline (ISO with offset).
 * @param {string | null | undefined} openTime Package open instant.
 * @param {Date} [now]
 * @returns {string | null} Error message, or null when valid.
 */
export function validateDeadline(closeIso, openTime, now = new Date()) {
  if (!closeIso) return 'Pick a date and time.';
  const close = new Date(closeIso).getTime();
  if (close <= now.getTime()) return 'The new deadline must be in the future.';
  if (openTime && close <= new Date(openTime).getTime()) {
    return 'The deadline must be after the package open time.';
  }
  return null;
}

/**
 * State + submit logic for the Extend Deadline dialog.
 *
 * @param {{ id: string, open_time?: string | null, close_time?: string | null } | null} pkg
 * @param {(updated: { id: string, open_time: string | null, close_time: string | null }) => void} onSaved
 */
export function useExtendDeadline(pkg, onSaved) {
  const [value, setValue] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setValue(toSriLankaInputValue(pkg?.close_time) || extendedInputValue(null, 7));
    setError('');
    setSaving(false);
  }, [pkg?.id, pkg?.close_time]);

  const quickExtend = useCallback(
    (days) => {
      setValue(extendedInputValue(pkg?.close_time, days));
      setError('');
    },
    [pkg?.close_time],
  );

  const persist = useCallback(
    async (closeIso) => {
      if (!pkg) return;
      setSaving(true);
      setError('');
      try {
        const updated = await adminApi.updatePackageSchedule(pkg.id, closeIso);
        onSaved(updated);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update deadline');
      } finally {
        setSaving(false);
      }
    },
    [pkg, onSaved],
  );

  const submit = useCallback(async () => {
    const closeIso = fromSriLankaInputValue(value);
    const problem = validateDeadline(closeIso, pkg?.open_time);
    if (problem) {
      setError(problem);
      return;
    }
    await persist(closeIso);
  }, [value, pkg?.open_time, persist]);

  const removeDeadline = useCallback(() => persist(null), [persist]);

  const onChange = useCallback((next) => {
    setValue(next);
    setError('');
  }, []);

  return { value, onChange, error, saving, quickExtend, submit, removeDeadline };
}
