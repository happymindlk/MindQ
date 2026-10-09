import { useCallback, useEffect, useRef, useState } from 'react';
import { adminApi } from '../../../lib/adminApi';

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
 * }}
 */
export function useCorporatePackages(corporateId) {
  const [packages, setPackages] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const requestIdRef = useRef(0);

  const reload = useCallback(async () => {
    if (!corporateId) return;
    const requestId = ++requestIdRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const rows = await adminApi.listCorporatePackages(corporateId);
      if (requestId === requestIdRef.current) setPackages(rows || []);
    } catch (err) {
      if (requestId === requestIdRef.current) {
        setError(err.message || 'Failed to load packages');
      }
    } finally {
      if (requestId === requestIdRef.current) setIsLoading(false);
    }
  }, [corporateId]);

  useEffect(() => {
    setPackages([]);
    reload();
    return () => {
      requestIdRef.current += 1;
    };
  }, [reload]);

  const patchPackage = useCallback((id, patch) => {
    setPackages((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  }, []);

  return { packages, isLoading, error, reload, patchPackage };
}
