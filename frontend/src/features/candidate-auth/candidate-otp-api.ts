import { api } from '../../api/client';
import { supabaseOtp } from '../../lib/supabase-otp-client';

/** Identity the candidate enters before an OTP is sent. */
export interface CandidateIdentity {
  accessCode: string;
  firstName: string;
  fullName: string;
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

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

/**
 * Email a one-time code. Candidates are not pre-provisioned in Supabase Auth,
 * so the first request creates a bare auth user that only ever proves inbox
 * ownership; it carries no tenant claims and RLS grants it nothing.
 */
export async function sendCandidateOtp(email: string): Promise<void> {
  const { error } = await supabaseOtp.auth.signInWithOtp({
    email: normalizeEmail(email),
    options: { shouldCreateUser: true },
  });
  if (error) throw new Error(error.message);
}

/**
 * Verify the emailed code and exchange the short-lived Supabase token for a
 * candidate session. The Supabase session is discarded either way.
 */
export async function verifyCandidateOtp(identity: CandidateIdentity, code: string): Promise<CandidateSession> {
  const email = normalizeEmail(identity.email);
  const { data, error } = await supabaseOtp.auth.verifyOtp({ email, token: code, type: 'email' });
  if (error) throw new Error(error.message);
  const verificationToken = data.session?.access_token;
  if (!verificationToken) throw new Error('Verification did not return a session. Request a new code.');

  try {
    const res = (await api.candidate.login(
      {
        access_code: identity.accessCode.trim(),
        first_name: identity.firstName.trim(),
        full_name: identity.fullName.trim(),
        email,
      },
      verificationToken,
    )) as CandidateLoginResponse;
    return {
      token: res.token,
      id: res.id,
      firstName: res.first_name || identity.firstName.trim(),
      fullName: res.full_name,
      accessCode: res.access_code || identity.accessCode.trim(),
    };
  } finally {
    await supabaseOtp.auth.signOut({ scope: 'local' });
  }
}

export function persistCandidateSession(session: CandidateSession): void {
  localStorage.setItem('candidateToken', session.token);
  localStorage.setItem('candidateId', session.id);
  localStorage.setItem('candidateName', session.fullName);
  localStorage.setItem('candidateFirstName', session.firstName);
  localStorage.setItem('candidateAccessCode', session.accessCode);
}
