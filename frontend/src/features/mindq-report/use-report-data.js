import { useCallback, useEffect, useState } from 'react';

/**
 * Load a candidate's MindQ Report payload.
 *
 * @param {string | undefined} candidateId
 * @param {(candidateId: string) => Promise<Record<string, any>>} fetchReportData
 */
export function useReportData(candidateId, fetchReportData) {
  const [data, setData] = useState(/** @type {Record<string, any> | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!candidateId) return undefined;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchReportData(candidateId)
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Report unavailable');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [candidateId, fetchReportData, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  return { data, error, loading, retry };
}
