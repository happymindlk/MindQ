const DEVICE_ID_KEY = 'mindq_device_id';

const LOGIN_DRAFT_EMAIL_KEY = 'mindq_login_email';
const LOGIN_DRAFT_NAME_KEY = 'mindq_login_name';
const LOGIN_DRAFT_ACCESS_CODE_KEY = 'mindq_login_access_code';

export interface DeviceContext {
  device_id: string;
  browser: string;
  user_agent: string;
  page_url: string;
}

function storageWrite(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
    return;
  } catch {
    // Private mode / quota — fall through to sessionStorage.
  }
  try {
    sessionStorage.setItem(key, value);
  } catch {
    // Both unavailable; caller still gets an in-memory id for this page load.
  }
}

function storageRead(key: string): string | null {
  try {
    const fromLocal = localStorage.getItem(key);
    if (fromLocal) return fromLocal;
  } catch {
    // ignore
  }
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function newDeviceId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `mindq-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Persist a stable anonymous device id and return browser/page context.
 *
 * Uses `localStorage` first, then `sessionStorage`, then an ephemeral id.
 *
 * @returns Device fingerprint fields for support tickets and request headers.
 */
export function getDeviceContext(): DeviceContext {
  let deviceId = storageRead(DEVICE_ID_KEY);
  if (!deviceId) {
    deviceId = newDeviceId();
    storageWrite(DEVICE_ID_KEY, deviceId);
  }
  const userAgent = typeof navigator !== 'undefined' ? navigator.userAgent : '';
  return {
    device_id: deviceId,
    browser: userAgent,
    user_agent: userAgent,
    page_url: typeof window !== 'undefined' ? window.location.href : '',
  };
}

/** Headers for candidate OTP, assessment start, and assessment submit. */
export function getDeviceHeaders(): Record<string, string> {
  const ctx = getDeviceContext();
  return {
    'X-Device-Id': ctx.device_id,
    'X-Browser-Info': ctx.browser.slice(0, 512),
  };
}

/**
 * Mirror in-progress login form fields so Technical Support can prefill.
 *
 * @param draft - Partial identity from the portal login form.
 */
export function persistLoginDraft(draft: {
  email?: string;
  fullName?: string;
  accessCode?: string;
}): void {
  if (draft.email !== undefined) {
    storageWrite(LOGIN_DRAFT_EMAIL_KEY, draft.email.trim());
  }
  if (draft.fullName !== undefined) {
    storageWrite(LOGIN_DRAFT_NAME_KEY, draft.fullName.trim());
  }
  if (draft.accessCode !== undefined) {
    storageWrite(LOGIN_DRAFT_ACCESS_CODE_KEY, draft.accessCode.trim());
  }
}

/** Email typed on the login form (or empty). */
export function readLoginDraftEmail(): string {
  return storageRead(LOGIN_DRAFT_EMAIL_KEY)?.trim() || '';
}

/** Full name typed on the login form (or empty). */
export function readLoginDraftName(): string {
  return (
    storageRead(LOGIN_DRAFT_NAME_KEY)?.trim() ||
    (typeof localStorage !== 'undefined' ? localStorage.getItem('candidateName') : null) ||
    ''
  );
}

/**
 * Access code from invite URL, login draft, or persisted session.
 *
 * @returns Trimmed access code or empty string.
 */
export function readAccessCode(): string {
  if (typeof window !== 'undefined') {
    const fromUrl = new URLSearchParams(window.location.search).get('code');
    if (fromUrl?.trim()) return fromUrl.trim();
  }
  return (
    storageRead(LOGIN_DRAFT_ACCESS_CODE_KEY)?.trim() ||
    (typeof localStorage !== 'undefined'
      ? localStorage.getItem('candidateAccessCode')?.trim() || ''
      : '')
  );
}
