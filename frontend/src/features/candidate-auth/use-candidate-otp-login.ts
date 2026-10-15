import { useCallback, useEffect, useState } from 'react';
import {
  normalizeEmail,
  persistCandidateSession,
  sendCandidateOtp,
  verifyCandidateOtp,
  type CandidateIdentity,
  type CandidateSession,
} from './candidate-otp-api';

export type CandidateLoginStep = 'details' | 'code';

export const OTP_MIN_LENGTH = 6;
export const OTP_MAX_LENGTH = 8;
/** Matches Supabase's per-email resend window so the button never invites a 429. */
export const RESEND_COOLDOWN_SECONDS = 60;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function message(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export function isIdentityComplete(identity: CandidateIdentity): boolean {
  return (
    identity.accessCode.trim().length > 0 &&
    identity.firstName.trim().length > 0 &&
    identity.fullName.trim().length > 0 &&
    EMAIL_PATTERN.test(normalizeEmail(identity.email))
  );
}

/**
 * Two-step candidate sign-in: identity + access code, then email OTP.
 *
 * @param initialAccessCode Code from the invite link (`?code=`), if any.
 * @param onAuthenticated Called once the candidate session is persisted.
 */
export function useCandidateOtpLogin(
  initialAccessCode: string,
  onAuthenticated: (session: CandidateSession) => void,
) {
  const [step, setStep] = useState<CandidateLoginStep>('details');
  const [identity, setIdentity] = useState<CandidateIdentity>({
    accessCode: initialAccessCode,
    firstName: '',
    fullName: '',
    email: '',
  });
  const [code, setCodeState] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (initialAccessCode) setIdentity((prev) => ({ ...prev, accessCode: initialAccessCode }));
  }, [initialAccessCode]);

  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const id = window.setInterval(() => setCooldown((s) => Math.max(0, s - 1)), 1000);
    return () => window.clearInterval(id);
  }, [cooldown]);

  const updateField = useCallback((field: keyof CandidateIdentity, value: string) => {
    setIdentity((prev) => ({ ...prev, [field]: field === 'accessCode' ? value.trim() : value }));
  }, []);

  const setCode = useCallback((value: string) => {
    setCodeState(value.replace(/\D/g, '').slice(0, OTP_MAX_LENGTH));
  }, []);

  const sendCode = useCallback(async () => {
    if (!isIdentityComplete(identity) || loading) return;
    setLoading(true);
    setError(null);
    try {
      await sendCandidateOtp(identity.email);
      setCodeState('');
      setStep('code');
      setCooldown(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      setError(message(err, 'Could not send the verification code'));
    } finally {
      setLoading(false);
    }
  }, [identity, loading]);

  const resendCode = useCallback(async () => {
    if (cooldown > 0 || loading) return;
    await sendCode();
  }, [cooldown, loading, sendCode]);

  const verifyCode = useCallback(async () => {
    if (code.length < OTP_MIN_LENGTH || loading) return;
    setLoading(true);
    setError(null);
    try {
      const session = await verifyCandidateOtp(identity, code);
      persistCandidateSession(session);
      onAuthenticated(session);
    } catch (err) {
      setError(message(err, 'Invalid or expired code'));
      setLoading(false);
    }
  }, [code, identity, loading, onAuthenticated]);

  const editDetails = useCallback(() => {
    setStep('details');
    setCodeState('');
    setError(null);
  }, []);

  return {
    step,
    identity,
    code,
    loading,
    error,
    cooldown,
    canSend: isIdentityComplete(identity),
    canVerify: code.length >= OTP_MIN_LENGTH,
    updateField,
    setCode,
    sendCode,
    resendCode,
    verifyCode,
    editDetails,
  };
}
