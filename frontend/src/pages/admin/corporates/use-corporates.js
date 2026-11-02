import { useCallback, useEffect, useRef } from 'react';
import { adminApi } from '../../../lib/adminApi';
import { useCachedQuery } from '../../../hooks/use-cached-query';

export const CORPORATES_QUERY_KEY = 'admin:corporates';

/**
 * @typedef {object} CorporateRow
 * @property {string} id
 * @property {string} name
 * @property {string} slug
 * @property {string | null} contact_email
 * @property {string[]} [allowed_hr_emails]
 * @property {boolean} [is_active]
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
 * @property {string[]} [allowedHrEmails] HR portal whitelist for this company.
 * @property {File | null} [logoFile]
 */

/**
 * @typedef {object} SaveCorporateResult
 * @property {CorporateRow} corporate
 * @property {string | null} logoError Set when the record saved but the logo upload failed.
 */

function sortByName(rows) {
  return [...rows].sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''));
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
    [row.name, row.slug, row.contact_email, ...(row.allowed_hr_emails || [])].some((field) =>
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
 *   deleteCorporate: (corporate: CorporateRow) => Promise<void>,
 * }}
 */
export function useCorporates() {
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fetcher = useCallback(async () => sortByName(await adminApi.listCorporates()), []);
  const { data, error, isLoading, reload, mutate } = useCachedQuery(CORPORATES_QUERY_KEY, fetcher);

  const saveCorporate = useCallback(
    async ({ id, name, contactEmail, allowedHrEmails, logoFile }) => {
      const saved = id
        ? await adminApi.updateCompany(id, {
            name,
            contact_email: contactEmail,
            allowed_hr_emails: allowedHrEmails || [],
          })
        : await adminApi.createCompany({ name, contactEmail, allowedHrEmails });

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
        mutate((prev) => {
          const rows = Array.isArray(prev) ? prev : [];
          const existing = rows.find((c) => c.id === corporate.id);
          const merged = { package_count: 0, candidate_count: 0, ...existing, ...corporate };
          return sortByName([...rows.filter((c) => c.id !== corporate.id), merged]);
        });
      }
      return { corporate, logoError };
    },
    [mutate],
  );

  const deleteCorporate = useCallback(
    async (corporate) => {
      await adminApi.deleteCompany(corporate.id);
      if (mountedRef.current) {
        mutate((prev) => (Array.isArray(prev) ? prev.filter((c) => c.id !== corporate.id) : []));
      }
    },
    [mutate],
  );

  return {
    corporates: Array.isArray(data) ? data : [],
    isLoading,
    error,
    reload,
    saveCorporate,
    deleteCorporate,
  };
}
