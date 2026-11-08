import { useCallback, useEffect, useRef, useState } from 'react';

const POLL_DELAYS_MS = [3000, 3000, 5000, 5000, 8000, 8000, 13000, 13000];
const POLL_MAX_DELAY_MS = 15000;
/**
 * Stop polling after this much waiting. Kept below the backend's 5-minute
 * retry cooldown so a failed background run surfaces as `failed` instead of
 * re-queuing Gemini on every poll.
 */
export const NARRATIVE_POLL_BUDGET_MS = 3 * 60 * 1000;

/**
 * Backoff before the n-th narrative re-fetch (0-based).
 *
 * @param {number} pollIndex
 * @returns {number}
 */
export function narrativePollDelay(pollIndex) {
  return POLL_DELAYS_MS[pollIndex] ?? POLL_MAX_DELAY_MS;
}

/**
 * Load a candidate's MindQ Report payload.
 *
 * Scores render from the first response. While the backend reports
 * `synthesis_status === 'generating'` the payload is silently re-fetched with
 * backoff (paused while the tab is hidden) until the narrative arrives, the
 * status changes, a re-fetch fails, or the poll budget is spent.
 *
 * @param {string | undefined} candidateId
 * @param {(candidateId: string) => Promise<Record<string, any>>} fetchReportData
 */
export function useReportData(candidateId, fetchReportData) {
  const [data, setData] = useState(/** @type {Record<string, any> | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [pollTick, setPollTick] = useState(0);
  const [pollStopped, setPollStopped] = useState(false);
  const pollRef = useRef({ count: 0, waitedMs: 0 });

  useEffect(() => {
    if (!candidateId) return undefined;
    let cancelled = false;
    pollRef.current = { count: 0, waitedMs: 0 };
    setPollStopped(false);
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

  const generating = data?.synthesis_status === 'generating';

  useEffect(() => {
    if (!candidateId || !generating || pollStopped) return undefined;
    const poll = pollRef.current;
    if (poll.waitedMs >= NARRATIVE_POLL_BUDGET_MS) {
      setPollStopped(true);
      return undefined;
    }
    const delay = narrativePollDelay(poll.count);
    let cancelled = false;
    const timer = setTimeout(() => {
      if (typeof document !== 'undefined' && document.hidden) {
        setPollTick((n) => n + 1);
        return;
      }
      poll.count += 1;
      poll.waitedMs += delay;
      fetchReportData(candidateId)
        .then((payload) => {
          if (cancelled) return;
          setData(payload);
          setPollTick((n) => n + 1);
        })
        .catch(() => {
          if (!cancelled) setPollStopped(true);
        });
    }, delay);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [candidateId, fetchReportData, generating, pollStopped, pollTick]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  return { data, error, loading, retry, narrativeLoading: generating && !pollStopped };
}
