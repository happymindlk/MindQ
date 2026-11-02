import { ApiError } from '../../lib/api-error';
import { API_ORIGIN } from '../../lib/api-origin';
import { BAD_RESPONSE_MESSAGE, requestJson } from '../../lib/api-request';
import { supabase } from '../../lib/supabaseClient';

const FORGOT_URL = `${API_ORIGIN}/api/v1/admin/auth/forgot-password`;
const CHANGE_URL = `${API_ORIGIN}/api/v1/admin/auth/change-password`;

const DEFAULT_RESET_CONFIRMATION =
  'If an account exists for this email, a reset link has been sent.';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Request a password-reset email. Always resolves with the server confirmation
 * copy — never reveals whether the address exists.
 *
 * @param email - Admin email from the forgot-password form.
 * @returns Confirmation detail string.
 */
export async function requestAdminPasswordReset(email: string): Promise<string> {
  const payload = await requestJson<unknown>(
    FORGOT_URL,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase() }),
    },
    'Could not send a reset link. Try again.',
  );
  if (isRecord(payload) && typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail.trim();
  }
  return DEFAULT_RESET_CONFIRMATION;
}

/**
 * Change the signed-in admin password after verifying the current one.
 *
 * @param currentPassword - Existing password.
 * @param newPassword - Replacement password (min 8 chars, validated by caller).
 */
export async function changeAdminPassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  if (!token) {
    throw new ApiError('Your session expired. Sign in again and retry.', 401);
  }

  await requestJson(
    CHANGE_URL,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    },
    'Could not update password. Try again.',
  );
}

export { BAD_RESPONSE_MESSAGE, DEFAULT_RESET_CONFIRMATION };
