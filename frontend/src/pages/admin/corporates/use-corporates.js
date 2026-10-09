import { useCallback, useEffect, useRef, useState } from 'react';
import { adminApi } from '../../../lib/adminApi';

/**
 * @typedef {object} CorporateRow
 * @property {string} id
 * @property {string} name
 * @property {string} slug
 * @property {string | null} contact_email
 * @property {string | null} logo_url
 * @property {number} [package_count]
 * @property {number} [candidate_count]
 * @property {string | null} [created_at] ISO timestamp.
 */

/**
 * @typedef {object} SaveCorporateInput
 * @property {string} [id] Present when editing an existing corporate.
 * @property {string} name
 * @property {string} contactEmail Empty string clears the HR email on edit.
 * @property {File | null} [logoFile]
 */

/**
 * @typedef {object} SaveCorporateResult
 * @property {CorporateRow} corporate
 * @property {string | null} logoError Set when the record saved but the logo upload failed.
 */

function sortByName(rows) {
  return [...rows].sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Case-insensitive keyword match on name, slug, and HR contact email.
 *
 * @param {CorporateRow[]} rows
 * @param {string} keyword
 * @returns {CorporateRow[]} The input array untouched when the keyword is blank.
 */
export function filterCorporates(rows, keyword) {
  const q = (keyword || '').trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((row) =>
    [row.name, row.slug, row.contact_email].some((field) =>
      (field || '').toLowerCase().includes(q),
    ),
  );
}

/**
 * Ops corporate directory: list, create, edit, and logo upload.
 *
 * @returns {{
 *   corporates: CorporateRow[],
 *   isLoading: boolean,
 *   error: string | null,
 *   reload: () => Promise<void>,
 *   saveCorporate: (input: SaveCorporateInput) => Promise<SaveCorporateResult>,
 * }}
 */
export function useCorporates() {
  const [corporates, setCorporates] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const rows = await adminApi.listCorporates();
      if (mountedRef.current) setCorporates(sortByName(rows || []));
    } catch (err) {
      if (mountedRef.current) setError(err.message || 'Failed to load corporates');
    } finally {
      if (mountedRef.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const saveCorporate = useCallback(async ({ id, name, contactEmail, logoFile }) => {
    const saved = id
      ? await adminApi.updateCompany(id, { name, contact_email: contactEmail })
      : await adminApi.createCompany({ name, contactEmail });

    const corporate = { ...saved };
    let logoError = null;
    if (logoFile) {
      try {
        corporate.logo_url = await adminApi.uploadCompanyLogo(saved.id, logoFile);
      } catch (err) {
        logoError = err.message || 'Logo upload failed';
      }
    }

    if (mountedRef.current) {
      setCorporates((prev) => {
        const existing = prev.find((c) => c.id === corporate.id);
        const merged = { package_count: 0, candidate_count: 0, ...existing, ...corporate };
        return sortByName([...prev.filter((c) => c.id !== corporate.id), merged]);
      });
    }
    return { corporate, logoError };
  }, []);

  return { corporates, isLoading, error, reload, saveCorporate };
}
