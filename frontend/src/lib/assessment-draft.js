const STORAGE_PREFIX = 'assessment_attempt';

/**
 * Build the localStorage key for one candidate assessment attempt.
 *
 * @param {string} candidateId
 * @param {string} assessmentId
 * @returns {string}
 */
export function draftKey(candidateId, assessmentId) {
  return `${STORAGE_PREFIX}_${candidateId}_${assessmentId}`;
}

/**
 * Read a locally persisted answer map. Invalid JSON yields an empty object.
 *
 * @param {string | null} candidateId
 * @param {string | null} assessmentId
 * @returns {Record<string, unknown>}
 */
export function readDraft(candidateId, assessmentId) {
  if (!candidateId || !assessmentId) return {};
  try {
    const raw = localStorage.getItem(draftKey(candidateId, assessmentId));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * Persist the live answer map so a refresh can restore unsynced keystrokes.
 *
 * @param {string | null} candidateId
 * @param {string | null} assessmentId
 * @param {Record<string, unknown>} answers
 */
export function writeDraft(candidateId, assessmentId, answers) {
  if (!candidateId || !assessmentId) return;
  try {
    localStorage.setItem(draftKey(candidateId, assessmentId), JSON.stringify(answers));
  } catch {
    // Quota or private-mode failures must not block typing.
  }
}

/**
 * Drop the attempt draft after a successful final submit.
 *
 * @param {string | null} candidateId
 * @param {string | null} assessmentId
 */
export function clearDraft(candidateId, assessmentId) {
  if (!candidateId || !assessmentId) return;
  try {
    localStorage.removeItem(draftKey(candidateId, assessmentId));
  } catch {
    // Ignore storage failures on cleanup.
  }
  try {
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.removeItem(draftKey(candidateId, assessmentId));
    }
  } catch {
    // Ignore storage failures on cleanup.
  }
}

/**
 * Overlay a local draft on server-hydrated answers. Local wins for the same key
 * because it is the more recent unsynced keystroke.
 *
 * @param {Record<string, unknown>} serverAnswers
 * @param {Record<string, unknown>} localDraft
 * @returns {Record<string, unknown>}
 */
export function mergeAnswers(serverAnswers, localDraft) {
  return { ...(serverAnswers || {}), ...(localDraft || {}) };
}

/**
 * Whether cached local answers should be restored for this attempt.
 *
 * Admin reset leaves the module as ``NOT_STARTED`` with ``started_at`` null;
 * stale browser drafts must never resurrect answers in that state. Resume
 * (``IN_PROGRESS`` / non-null ``started_at``) still merges the local draft.
 *
 * @param {{ startedAt?: string | null, status?: string | null }} [meta]
 * @returns {boolean}
 */
export function shouldRestoreDraft(meta = {}) {
  const status =
    typeof meta.status === 'string' && meta.status.trim()
      ? meta.status.trim().toUpperCase().replace(/-/g, '_')
      : null;
  if (status === 'IN_PROGRESS') return true;
  if (status === 'NOT_STARTED') return false;
  return Boolean(meta.startedAt);
}

/**
 * Hydrate runner answers from the server payload, clearing stale drafts when
 * the attempt is not in progress (never started or admin-reset).
 *
 * @param {Record<string, unknown> | null | undefined} serverAnswers
 * @param {string | null} candidateId
 * @param {string | null} assessmentId
 * @param {{ startedAt?: string | null, status?: string | null }} [meta]
 * @returns {Record<string, unknown>}
 */
export function hydrateAttemptAnswers(serverAnswers, candidateId, assessmentId, meta = {}) {
  if (!shouldRestoreDraft(meta)) {
    clearDraft(candidateId, assessmentId);
    return { ...(serverAnswers || {}) };
  }
  return mergeAnswers(serverAnswers || {}, readDraft(candidateId, assessmentId));
}
