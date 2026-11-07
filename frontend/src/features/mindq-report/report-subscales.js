/**
 * Single-metric instruments whose lone facet duplicates the module header.
 * Matched against the normalized assessment name (prefix).
 */
const SINGLE_METRIC_MODULES = ['personal initiative', 'cognicheck'];

/**
 * Collapse instrument names for fuzzy equality (strip filler words and punctuation).
 *
 * @param {string} value
 * @returns {string}
 */
function normalizeName(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/\b(scale|test|assessment|inventory|questionnaire)\b/g, '')
    .replace(/[^a-z0-9]/g, '');
}

/**
 * Drop a redundant single subscale when it repeats the module name.
 * Multi-facet modules and unrelated single facets are left unchanged.
 *
 * @template {{ name: string }} T
 * @param {string} assessmentName
 * @param {T[]} subscales
 * @returns {T[]}
 */
export function visibleSubscales(assessmentName, subscales) {
  if (!Array.isArray(subscales) || subscales.length !== 1) {
    return Array.isArray(subscales) ? subscales : [];
  }
  const mod = normalizeName(assessmentName);
  const sub = normalizeName(subscales[0]?.name);
  if (!mod || !sub) return subscales;
  const known = SINGLE_METRIC_MODULES.some((key) => mod.startsWith(normalizeName(key)));
  if (mod === sub || mod.includes(sub) || sub.includes(mod) || known) {
    return [];
  }
  return subscales;
}
