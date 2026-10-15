import { useCallback, useEffect, useMemo, useState } from 'react';
import { clientApi } from '../../lib/clientApi';

/**
 * Loads `GET /client/dashboard` and exposes a memoized, search-filtered view.
 * A package matches on title/role (all candidates kept); otherwise only the
 * matching candidates are kept and empty packages are dropped.
 */
export function useClientDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    clientApi
      .getDashboard()
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load dashboard');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

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
    loading,
    error,
    search,
    setSearch,
    refetch,
  };
}
