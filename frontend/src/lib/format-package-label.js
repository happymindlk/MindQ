/**
 * Normalize a package/role title for invite copy and email previews.
 *
 * Ensures every reference ends with ``Assessment`` without doubling when the
 * title already ends with ``Assessment``, ``Package``, or ``Assessment Package``.
 *
 * @param {string | null | undefined} title Raw package or role title.
 * @returns {string} Display label suitable for subjects and body copy.
 */
export function formatPackageLabel(title) {
  let cleaned = String(title ?? '').trim();
  if (!cleaned) return 'Assessment';

  let lower = cleaned.toLowerCase();
  while (true) {
    if (lower.endsWith('assessment package')) {
      cleaned = cleaned.slice(0, -'assessment package'.length).replace(/[\s\-–—:]+$/u, '');
      lower = cleaned.toLowerCase();
      continue;
    }
    if (lower.endsWith('package')) {
      cleaned = cleaned.slice(0, -'package'.length).replace(/[\s\-–—:]+$/u, '');
      lower = cleaned.toLowerCase();
      continue;
    }
    if (lower.endsWith('assessment')) {
      cleaned = cleaned.slice(0, -'assessment'.length).replace(/[\s\-–—:]+$/u, '');
      lower = cleaned.toLowerCase();
      continue;
    }
    break;
  }

  return cleaned ? `${cleaned} Assessment` : 'Assessment';
}
