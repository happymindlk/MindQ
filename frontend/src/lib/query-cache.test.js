import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  cachedQuery,
  invalidateQuery,
  isQueryFresh,
  peekQuery,
  setQuery,
} from './query-cache';

describe('query-cache', () => {
  afterEach(() => {
    invalidateQuery();
    vi.useRealTimers();
  });

  it('returns cached data within staleTime without awaiting a second network call', async () => {
    const fetcher = vi.fn(async () => ({ ok: true }));
    const first = await cachedQuery('k1', fetcher, { staleTime: 60000 });
    const second = await cachedQuery('k1', fetcher, { staleTime: 60000 });
    expect(first).toEqual({ ok: true });
    expect(second).toEqual({ ok: true });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('dedupes concurrent fetches for the same key', async () => {
    /** @type {(value: unknown) => void} */
    let resolve = () => undefined;
    const fetcher = vi.fn(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    const a = cachedQuery('parallel', fetcher);
    const b = cachedQuery('parallel', fetcher);
    await Promise.resolve();
    resolve({ n: 1 });
    await expect(Promise.all([a, b])).resolves.toEqual([{ n: 1 }, { n: 1 }]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('exposes peek/fresh helpers', () => {
    setQuery('peek', 42);
    expect(peekQuery('peek')).toBe(42);
    expect(isQueryFresh('peek', 60000)).toBe(true);
  });
});
