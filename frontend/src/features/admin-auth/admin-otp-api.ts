import { ApiError } from '../../lib/api-error';
import { API_ORIGIN } from '../../lib/api-origin';
import { BAD_RESPONSE_MESSAGE, requestJson } from '../../lib/api-request';
import { supabase } from '../../lib/supabaseClient';

export interface AdminOtpChallenge {
  status: 'otp_required';
  temp_token: string;
}

export interface AdminOtpProfile {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  corporate_id: string;
}

export interface AdminOtpSession {
  access_token: string;
  refresh_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: AdminOtpProfile;
}

const LOGIN_URL = `${API_ORIGIN}/api/v1/admin/auth/login`;
const VERIFY_URL = `${API_ORIGIN}/api/v1/admin/auth/verify-otp`;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isChallenge(value: unknown): value is AdminOtpChallenge {
  return (
    isRecord(value) &&
    value.status === 'otp_required' &&
    typeof value.temp_token === 'string' &&
    value.temp_token.length >= 20
  );
}

function isSession(value: unknown): value is AdminOtpSession {
  if (!isRecord(value) || !isRecord(value.user)) return false;
  const user = value.user;
  return (
    typeof value.access_token === 'string' &&
    value.access_token.length > 0 &&
    typeof value.refresh_token === 'string' &&
    value.refresh_token.length > 0 &&
    typeof value.expires_in === 'number' &&
    typeof user.id === 'string' &&
    typeof user.email === 'string' &&
    typeof user.role === 'string' &&
    typeof user.corporate_id === 'string'
  );
}

/**
 * Password step. A match returns a temp token, not an admin session.
 *
 * @param email - Admin email.
 * @param password - Admin password. Sent once; never logged.
 * @returns The OTP challenge.
 */
export async function requestAdminOtp(email: string, password: string): Promise<AdminOtpChallenge> {
  const body = await requestJson<unknown>(
    LOGIN_URL,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    },
    'Sign-in failed. Try again.',
  );
  if (!isChallenge(body)) {
    throw new ApiError(BAD_RESPONSE_MESSAGE, 200, 'BAD_RESPONSE');
  }
  return { status: 'otp_required', temp_token: body.temp_token };
}

/**
 * Exchange the temp token and the emailed code for an admin session.
 *
 * @param tempToken - Token held in memory from {@link requestAdminOtp}.
 * @param otpCode - Six-digit code.
 * @returns Access token, refresh token, and ops profile.
 */
export async function verifyAdminOtp(tempToken: string, otpCode: string): Promise<AdminOtpSession> {
  const body = await requestJson<unknown>(
    VERIFY_URL,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ temp_token: tempToken, otp_code: otpCode }),
    },
    'That code is not valid. Try again.',
  );
  if (!isSession(body)) {
    throw new ApiError(BAD_RESPONSE_MESSAGE, 200, 'BAD_RESPONSE');
  }
  return body;
}

/**
 * Persist the admin session where the ops portal already reads it.
 *
 * Protected routes and API calls use the Supabase client session. A second
 * copy of the JWT in web storage would not sign the admin in.
 *
 * @param session - Tokens returned by {@link verifyAdminOtp}.
 */
export async function establishAdminSession(session: AdminOtpSession): Promise<void> {
  const { error } = await supabase.auth.setSession({
    access_token: session.access_token,
    refresh_token: session.refresh_token,
  });
  if (error) throw error;
}
