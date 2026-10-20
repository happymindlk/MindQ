import { api } from '../../api/client';

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

interface CandidateLoginResponse {
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
 * @param identity - Candidate identity; only access code and email are sent.
 * @returns The temp token that must accompany the code at login.
 */
export async function sendCandidateOtp(identity: CandidateIdentity): Promise<string> {
  const res = (await api.candidate.requestCandidateOtp({
    access_code: identity.accessCode.trim(),
    email: normalizeEmail(identity.email),
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
  const res = (await api.candidate.login({
    access_code: identity.accessCode.trim(),
    first_name: identity.firstName.trim(),
    full_name: fullName,
    email,
    temp_token: tempToken,
    otp_code: code,
  })) as CandidateLoginResponse;
  return {
    token: res.token,
    id: res.id,
    firstName: res.first_name || identity.firstName.trim(),
    fullName: res.full_name,
    accessCode: res.access_code || identity.accessCode.trim(),
  };
}

export function persistCandidateSession(session: CandidateSession): void {
  localStorage.setItem('candidateToken', session.token);
  localStorage.setItem('candidateId', session.id);
  localStorage.setItem('candidateName', session.fullName);
  localStorage.setItem('candidateFirstName', session.firstName);
  localStorage.setItem('candidateAccessCode', session.accessCode);
}
