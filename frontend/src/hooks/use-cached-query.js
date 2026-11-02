import { useCallback, useEffect, useRef, useState } from 'react';
import {
  DEFAULT_STALE_TIME_MS,
  cachedQuery,
  peekQuery,
  setQuery,
} from '../lib/query-cache';

/**
 * Subscribe to a cached async resource. Remounts paint instantly from cache.
 *
 * @template T
 * @param {string | null} key
 * @param {() => Promise<T>} fetcher
 * @param {{ staleTime?: number, enabled?: boolean }} [options]
 * @returns {{
 *   data: T | null,
 *   error: string | null,
 *   isLoading: boolean,
 *   isValidating: boolean,
 *   reload: () => Promise<void>,
 *   mutate: (next: T | ((prev: T | null) => T)) => void,
 * }}
 */
export function useCachedQuery(key, fetcher, { staleTime = DEFAULT_STALE_TIME_MS, enabled = true } = {}) {
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const initial = key ? peekQuery(key) : undefined;
  const [data, setData] = useState(() => (initial === undefined ? null : /** @type {T} */ (initial)));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [isLoading, setIsLoading] = useState(() => enabled && key != null && initial === undefined);
  const [isValidating, setIsValidating] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(
    async ({ force = false } = {}) => {
      if (!enabled || !key) return;
      const hadCache = peekQuery(key) !== undefined;
      if (!hadCache) setIsLoading(true);
      setIsValidating(true);
      try {
        const next = await cachedQuery(key, () => fetcherRef.current(), { staleTime, force });
        if (!mountedRef.current) return;
        setData(next);
        setError(null);
      } catch (err) {
        if (!mountedRef.current) return;
        if (!hadCache) {
          setError(err instanceof Error && err.message ? err.message : 'Failed to load');
        }
      } finally {
        if (!mountedRef.current) return;
        setIsLoading(false);
        setIsValidating(false);
      }
    },
    [enabled, key, staleTime],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const reload = useCallback(async () => {
    await load({ force: true });
  }, [load]);

  const mutate = useCallback(
    (next) => {
      setData((prev) => {
        const value = typeof next === 'function' ? next(prev) : next;
        if (key) setQuery(key, value);
        return value;
      });
    },
    [key],
  );

  return {
    data,
    error,
    isLoading: Boolean(isLoading && data == null),
    isValidating,
    reload,
    mutate,
  };
}
