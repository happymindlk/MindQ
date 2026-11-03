/**
 * Lightweight stale-while-revalidate cache for route remounts.
 * Avoids a TanStack Query dependency while giving tabs instant paint.
 */

/** @type {Map<string, { data: unknown, at: number }>} */
const store = new Map();

/** @type {Map<string, Promise<unknown>>} */
const inflight = new Map();

export const DEFAULT_STALE_TIME_MS = 5 * 60 * 1000;

/** Cache key for a candidate assessment runner payload. */
export function candidateTestKey(testId) {
  return `candidate-test:${testId}`;
}

/**
 * Read a cached value without fetching.
 *
 * @param {string} key
 * @returns {unknown | undefined}
 */
export function peekQuery(key) {
  return store.get(key)?.data;
}

/**
 * Whether the cache entry is still within ``staleTime``.
 *
 * @param {string} key
 * @param {number} [staleTime]
 * @returns {boolean}
 */
export function isQueryFresh(key, staleTime = DEFAULT_STALE_TIME_MS) {
  const hit = store.get(key);
  if (!hit) return false;
  return Date.now() - hit.at < staleTime;
}

/**
 * Write a cache entry.
 *
 * @param {string} key
 * @param {unknown} data
 */
export function setQuery(key, data) {
  store.set(key, { data, at: Date.now() });
}

/**
 * Drop one key or every key with a prefix.
 *
 * @param {string} [keyOrPrefix]
 */
export function invalidateQuery(keyOrPrefix) {
  if (!keyOrPrefix) {
    store.clear();
    inflight.clear();
    return;
  }
  if (store.has(keyOrPrefix)) {
    store.delete(keyOrPrefix);
    inflight.delete(keyOrPrefix);
    return;
  }
  for (const key of store.keys()) {
    if (key.startsWith(keyOrPrefix)) store.delete(key);
  }
  for (const key of inflight.keys()) {
    if (key.startsWith(keyOrPrefix)) inflight.delete(key);
  }
}

/**
 * Fetch with SWR semantics: return fresh cache immediately, else await network.
 * Always kicks a background revalidation when serving a fresh hit.
 *
 * @template T
 * @param {string} key
 * @param {() => Promise<T>} fetcher
 * @param {{ staleTime?: number, force?: boolean }} [options]
 * @returns {Promise<T>}
 */
export async function cachedQuery(key, fetcher, { staleTime = DEFAULT_STALE_TIME_MS, force = false } = {}) {
  const hit = store.get(key);
  const fresh = Boolean(hit) && !force && Date.now() - hit.at < staleTime;
  if (fresh) {
    return /** @type {T} */ (hit.data);
  }

  if (inflight.has(key)) {
    return /** @type {Promise<T>} */ (inflight.get(key));
  }

  const pending = Promise.resolve()
    .then(fetcher)
    .then((data) => {
      setQuery(key, data);
      return data;
    })
    .finally(() => {
      inflight.delete(key);
    });
  inflight.set(key, pending);
  return pending;
}
