/**
 * Derive a two-letter mark from a company name.
 *
 * @param {string | null | undefined} name
 * @returns {string}
 */
export function companyInitials(name) {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return 'CO';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}
