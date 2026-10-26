const STORAGE_KEY = 'mindq_builder_draft_v1';
const DRAFT_VERSION = 1;

export interface AssessmentBuilderDraft {
  v: number;
  updatedAt: number;
  kind: 'psychometric' | 'technical';
  category: string | null;
  title: string;
  description: string;
  minutes: number;
  timerMode: 'strict' | 'flexible';
  shuffle: boolean;
  showTopDisclaimer: boolean;
  topDisclaimerText: string;
  showConfidentialityNotice: boolean;
  confidentialityNoticeText: string;
}

/**
 * Read the Standard Library create-module draft from localStorage.
 *
 * @returns Draft payload or null when missing/invalid.
 */
export function readBuilderDraft(): AssessmentBuilderDraft | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AssessmentBuilderDraft;
    if (!parsed || parsed.v !== DRAFT_VERSION) return null;
    if (parsed.kind !== 'psychometric' && parsed.kind !== 'technical') return null;
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Persist create-module form fields so tab switches restore the dialog.
 *
 * @param fields - Draft fields excluding version metadata.
 */
export function writeBuilderDraft(
  fields: Omit<AssessmentBuilderDraft, 'v' | 'updatedAt'>,
): void {
  try {
    const payload: AssessmentBuilderDraft = {
      v: DRAFT_VERSION,
      updatedAt: Date.now(),
      ...fields,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Quota / private mode must not block typing.
  }
}

/** Clear the create-module draft after save or explicit discard. */
export function clearBuilderDraft(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore cleanup failures.
  }
}

/**
 * Whether the draft has meaningful user input beyond the kind picker.
 *
 * @param draft - Cached draft or null.
 * @returns True when title/description/settings differ from empty defaults.
 */
export function builderDraftHasContent(draft: AssessmentBuilderDraft | null): boolean {
  if (!draft) return false;
  return Boolean(
    String(draft.title || '').trim() ||
      String(draft.description || '').trim() ||
      draft.minutes > 0 ||
      draft.shuffle ||
      draft.showTopDisclaimer,
  );
}
