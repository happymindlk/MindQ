import { useCallback } from 'react';
import { useCachedQuery } from '../../../hooks/use-cached-query';
import { adminApi } from '../../../lib/adminApi';

/**
 * @param {string | undefined} corporateId
 * @returns {string | null}
 */
export function corporatePackagesQueryKey(corporateId) {
  return corporateId ? `admin:corporate-packages:${corporateId}` : null;
}

/**
 * @typedef {object} CorporatePackage
 * @property {string} id
 * @property {string} title
 * @property {string | null} target_role
 * @property {'draft' | 'published' | 'archived'} status
 * @property {string} access_code
 * @property {number} invited_count
 * @property {number} completed_count
 * @property {string | null} published_at
 * @property {string | null} created_at
 * @property {string | null} open_time ISO instant; null = open immediately.
 * @property {string | null} close_time ISO instant; null = no deadline.
 * @property {string | null} candidate_link Present only when published.
 * @property {string | null} hr_login_link Present only when published.
 */

/**
 * Packages for one corporate, newest first.
 *
 * @param {string | undefined} corporateId
 * @returns {{
 *   packages: CorporatePackage[],
 *   isLoading: boolean,
 *   error: string | null,
 *   reload: () => Promise<void>,
 *   patchPackage: (id: string, patch: Partial<CorporatePackage>) => void,
 *   removePackage: (id: string) => void,
 * }}
 */
export function useCorporatePackages(corporateId) {
  const key = corporatePackagesQueryKey(corporateId);
  const fetcher = useCallback(
    async () => (corporateId ? (await adminApi.listCorporatePackages(corporateId)) || [] : []),
    [corporateId],
  );
  const { data, error, isLoading, reload, mutate } = useCachedQuery(key, fetcher, {
    enabled: Boolean(corporateId),
  });

  const patchPackage = useCallback(
    (id, patch) => {
      mutate((prev) => (Array.isArray(prev) ? prev.map((p) => (p.id === id ? { ...p, ...patch } : p)) : prev));
    },
    [mutate],
  );

  const removePackage = useCallback(
    (id) => {
      mutate((prev) => (Array.isArray(prev) ? prev.filter((p) => p.id !== id) : prev));
    },
    [mutate],
  );

  return {
    packages: Array.isArray(data) ? data : [],
    isLoading,
    error,
    reload,
    patchPackage,
    removePackage,
  };
}
