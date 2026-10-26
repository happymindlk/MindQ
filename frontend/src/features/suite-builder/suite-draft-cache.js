const PREFIX = 'mindq:suite-builder:draft:';
const NEW_KEY = `${PREFIX}new`;
const DRAFT_VERSION = 1;

/**
 * Prefer localStorage so drafts survive tab close; fall back to sessionStorage
 * for private-mode / quota failures and migrate any legacy session entries.
 *
 * @returns {Storage | null}
 */
function primaryStorage() {
  try {
    return localStorage;
  } catch {
    try {
      return sessionStorage;
    } catch {
      return null;
    }
  }
}

/**
 * @param {string} key
 * @returns {string | null}
 */
function readRaw(key) {
  try {
    const primary = primaryStorage();
    const fromPrimary = primary?.getItem(key) ?? null;
    if (fromPrimary != null) return fromPrimary;
    // Migrate legacy sessionStorage drafts once.
    const fromSession = sessionStorage.getItem(key);
    if (fromSession != null && primary && primary !== sessionStorage) {
      primary.setItem(key, fromSession);
      sessionStorage.removeItem(key);
    }
    return fromSession;
  } catch {
    return null;
  }
}

/**
 * @param {string} key
 * @param {string} value
 */
function writeRaw(key, value) {
  try {
    const primary = primaryStorage();
    primary?.setItem(key, value);
    // Keep session in sync when both exist so older tabs still hydrate.
    try {
      if (primary !== sessionStorage) sessionStorage.setItem(key, value);
    } catch {
      // Ignore secondary storage failures.
    }
  } catch {
    // Quota or private-mode failures must not block typing.
  }
}

/**
 * @param {string} key
 */
function removeRaw(key) {
  try {
    primaryStorage()?.removeItem(key);
  } catch {
    // Ignore.
  }
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Ignore.
  }
}

/**
 * Storage key for an in-progress suite draft.
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
    const raw = readRaw(suiteDraftKey(packageId));
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
 * Persist suite form fields so remounts / tab switches can restore them.
 *
 * @param {string | null | undefined} packageId
 * @param {Omit<SuiteDraftPayload, 'v' | 'updatedAt'>} fields
 */
export function writeSuiteDraft(packageId, fields) {
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
  writeRaw(suiteDraftKey(packageId), JSON.stringify(payload));
}

/**
 * Drop a cached draft after publish or discard.
 *
 * @param {string | null | undefined} packageId
 */
export function clearSuiteDraft(packageId) {
  removeRaw(suiteDraftKey(packageId));
}

/**
 * Move the create-flow cache onto an edit key after the first server save.
 *
 * @param {string} packageId
 */
export function migrateSuiteDraft(packageId) {
  if (!packageId) return;
  try {
    const raw = readRaw(NEW_KEY);
    if (!raw) return;
    writeRaw(suiteDraftKey(packageId), raw);
    removeRaw(NEW_KEY);
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
