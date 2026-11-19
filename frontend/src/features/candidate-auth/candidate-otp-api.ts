import { api } from '../../api/client';
import { ApiError } from '../../lib/api-error';
import { CANDIDATE_DASHBOARD_KEY } from '../candidate-dashboard/module-status';
import { invalidateQuery } from '../../lib/query-cache';

/** Identity the candidate enters before an OTP is sent. */
export interface CandidateIdentity {
  accessCode: string;
  firstName: string;
  lastName: string;
  email: string;
}

/** Backend-minted candidate session persisted for the portal. */
export interface CandidateSession {
  token: string;
  id: string;
  firstName: string;
  fullName: string;
  accessCode: string;
}

const CANDIDATE_SESSION_KEYS = [
  'candidateToken',
  'candidateId',
  'candidateName',
  'candidateFirstName',
  'candidateAccessCode',
] as const;

interface CandidateVerifyResponse {
  token: string;
  id: string;
  first_name?: string | null;
  full_name: string;
  access_code?: string | null;
}

interface CandidateOtpChallengeResponse {
  status: string;
  temp_token: string;
}

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

/**
 * Ask the backend to email a one-time code for this access code + email.
 *
 * @param identity - Candidate identity; the names are validated by the
 * backend but only the access code and email bind the challenge.
 * @returns The temp token that must accompany the code at verify.
 */
export async function sendCandidateOtp(identity: CandidateIdentity): Promise<string> {
  const firstName = identity.firstName.trim();
  const res = (await api.candidate.sendCandidateOtp({
    access_code: identity.accessCode.trim(),
    email: normalizeEmail(identity.email),
    first_name: firstName,
    full_name: `${firstName} ${identity.lastName.trim()}`,
    terms_accepted: true,
  })) as CandidateOtpChallengeResponse;
  if (!res?.temp_token) throw new Error('Verification did not return a session. Request a new code.');
  return res.temp_token;
}

/**
 * Verify the emailed code by completing the candidate login.
 *
 * @param identity - Candidate identity from the details step.
 * @param code - Six-digit code from the email.
 * @param tempToken - Temp token returned when the code was requested.
 * @returns The persisted candidate session payload.
 */
export async function verifyCandidateOtp(
  identity: CandidateIdentity,
  code: string,
  tempToken: string,
): Promise<CandidateSession> {
  const email = normalizeEmail(identity.email);
  // Backend contract requires both first_name and full_name; derive the
  // latter from the two fields the candidate actually typed.
  const fullName = `${identity.firstName.trim()} ${identity.lastName.trim()}`;
  const res = (await api.candidate.verifyCandidateOtp({
    access_code: identity.accessCode.trim(),
    first_name: identity.firstName.trim(),
    full_name: fullName,
    email,
    temp_token: tempToken,
    otp_code: code,
    terms_accepted: true,
  })) as CandidateVerifyResponse;
  return {
    token: res.token,
    id: res.id,
    firstName: res.first_name ?? '',
    fullName: res.full_name,
    accessCode: res.access_code ?? '',
  };
}

export function persistCandidateSession(session: CandidateSession): void {
  localStorage.setItem('candidateToken', session.token);
  localStorage.setItem('candidateId', session.id);
  localStorage.setItem('candidateName', session.fullName);
  localStorage.setItem('candidateFirstName', session.firstName);
  localStorage.setItem('candidateAccessCode', session.accessCode);
}

/** Drop portal session keys without calling the server (expired JWT path). */
export function clearLocalCandidateSession(): void {
  for (const key of CANDIDATE_SESSION_KEYS) {
    localStorage.removeItem(key);
  }
  invalidateQuery(CANDIDATE_DASHBOARD_KEY);
}

/**
 * When a stored candidate JWT is already invalid/expired, clear it quietly.
 *
 * Used on `/portal?code=…` entry so returning candidates see Email + OTP
 * instead of a dashboard "Invalid or expired token" error.
 *
 * @returns `true` when a stale token was cleared.
 */
export async function clearStaleCandidateSessionIfExpired(): Promise<boolean> {
  const token = localStorage.getItem('candidateToken');
  if (!token) return false;
  try {
    await api.candidate.getDashboard();
    return false;
  } catch (err) {
    const status =
      err instanceof ApiError
        ? err.status
        : typeof err === 'object' && err && 'status' in err
          ? Number((err as { status: unknown }).status)
          : 0;
    if (status === 401) {
      clearLocalCandidateSession();
      return true;
    }
    return false;
  }
}

/** Clear portal session keys after a best-effort server logout. */
export async function clearCandidateSession(): Promise<void> {
  try {
    await api.candidate.logout();
  } catch {
    // Local clear must still happen if the lock release request fails.
  }
  clearLocalCandidateSession();
}
