const PREFIX = 'mindq:suite-builder:draft:';
const NEW_KEY = `${PREFIX}new`;
const DRAFT_VERSION = 1;

/**
 * sessionStorage key for an in-progress suite draft.
 *
 * @param {string | null | undefined} packageId - Null/undefined → create flow key.
 * @returns {string}
 */
export function suiteDraftKey(packageId) {
  return packageId ? `${PREFIX}${packageId}` : NEW_KEY;
}

/**
 * @typedef {object} SuiteDraftPayload
 * @property {number} v
 * @property {number} updatedAt
 * @property {string} corporateId
 * @property {string} title
 * @property {string} description
 * @property {string} targetRole
 * @property {string} openTime
 * @property {string} closeTime
 * @property {string[]} cartIds
 * @property {Record<string, unknown[]>} moduleOverrides
 * @property {unknown[]} customQuestions
 */

/**
 * Read a cached suite draft. Invalid JSON yields null.
 *
 * @param {string | null | undefined} packageId
 * @returns {SuiteDraftPayload | null}
 */
export function readSuiteDraft(packageId) {
  try {
    const raw = sessionStorage.getItem(suiteDraftKey(packageId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    if (parsed.v !== DRAFT_VERSION) return null;
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Persist suite form fields so remounts / tab discard can restore them.
 *
 * @param {string | null | undefined} packageId
 * @param {Omit<SuiteDraftPayload, 'v' | 'updatedAt'>} fields
 */
export function writeSuiteDraft(packageId, fields) {
  try {
    const payload = {
      v: DRAFT_VERSION,
      updatedAt: Date.now(),
      corporateId: fields.corporateId ?? '',
      title: fields.title ?? '',
      description: fields.description ?? '',
      targetRole: fields.targetRole ?? '',
      openTime: fields.openTime ?? '',
      closeTime: fields.closeTime ?? '',
      cartIds: Array.isArray(fields.cartIds) ? fields.cartIds : [],
      moduleOverrides:
        fields.moduleOverrides && typeof fields.moduleOverrides === 'object'
          ? fields.moduleOverrides
          : {},
      customQuestions: Array.isArray(fields.customQuestions) ? fields.customQuestions : [],
    };
    sessionStorage.setItem(suiteDraftKey(packageId), JSON.stringify(payload));
  } catch {
    // Quota or private-mode failures must not block typing.
  }
}

/**
 * Drop a cached draft after publish or discard.
 *
 * @param {string | null | undefined} packageId
 */
export function clearSuiteDraft(packageId) {
  try {
    sessionStorage.removeItem(suiteDraftKey(packageId));
  } catch {
    // Ignore storage failures on cleanup.
  }
}

/**
 * Move the create-flow cache onto an edit key after the first server save.
 *
 * @param {string} packageId
 */
export function migrateSuiteDraft(packageId) {
  if (!packageId) return;
  try {
    const raw = sessionStorage.getItem(NEW_KEY);
    if (!raw) return;
    sessionStorage.setItem(suiteDraftKey(packageId), raw);
    sessionStorage.removeItem(NEW_KEY);
  } catch {
    // Ignore storage failures on migrate.
  }
}

/**
 * Whether a cached draft has any meaningful user input.
 *
 * @param {SuiteDraftPayload | null} draft
 * @returns {boolean}
 */
export function suiteDraftHasContent(draft) {
  if (!draft) return false;
  return Boolean(
    (draft.corporateId && String(draft.corporateId).trim()) ||
      (draft.title && String(draft.title).trim()) ||
      (draft.description && String(draft.description).trim()) ||
      (draft.targetRole && String(draft.targetRole).trim()) ||
      (draft.openTime && String(draft.openTime).trim()) ||
      (draft.closeTime && String(draft.closeTime).trim()) ||
      (Array.isArray(draft.cartIds) && draft.cartIds.length > 0) ||
      (Array.isArray(draft.customQuestions) &&
        draft.customQuestions.some((q) => String(q?.prompt || '').trim())),
  );
}
