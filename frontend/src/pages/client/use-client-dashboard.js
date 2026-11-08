import { useCallback, useMemo, useState } from 'react';
import { useCachedQuery } from '../../hooks/use-cached-query';
import { clientApi } from '../../lib/clientApi';

/** Cache key for the HR client portal dashboard payload. */
export const CLIENT_DASHBOARD_KEY = 'client:dashboard';

/**
 * Loads `GET /client/dashboard` and exposes a memoized, search-filtered view.
 * A package matches on title/role (all candidates kept); otherwise only the
 * matching candidates are kept and empty packages are dropped.
 *
 * Remounts (including React StrictMode) paint from cache / share one inflight GET.
 */
export function useClientDashboard() {
  const fetcher = useCallback(() => clientApi.getDashboard(), []);
  const {
    data,
    error,
    isLoading,
    reload,
  } = useCachedQuery(CLIENT_DASHBOARD_KEY, fetcher);
  const [search, setSearch] = useState('');

  const packages = useMemo(() => {
    const all = data?.packages ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return all;
    return all
      .map((pkg) => {
        const pkgMatch = `${pkg.title} ${pkg.target_role ?? ''}`.toLowerCase().includes(q);
        if (pkgMatch) return pkg;
        const candidates = pkg.candidates.filter((c) =>
          `${c.name} ${c.email}`.toLowerCase().includes(q),
        );
        return candidates.length ? { ...pkg, candidates } : null;
      })
      .filter(Boolean);
  }, [data, search]);

  const totals = useMemo(() => {
    const all = data?.packages ?? [];
    return {
      packages: all.length,
      invited: all.reduce((sum, p) => sum + p.total_invited, 0),
      completed: all.reduce((sum, p) => sum + p.total_completed, 0),
    };
  }, [data]);

  return {
    corporate: data?.corporate ?? null,
    packages,
    totals,
    hasPackages: (data?.packages?.length ?? 0) > 0,
    loading: isLoading,
    error,
    search,
    setSearch,
    refetch: reload,
  };
}
