import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../lib/api-error';
import {
  establishAdminSession,
  requestAdminOtp,
  verifyAdminOtp,
} from './admin-otp-api';

export const OTP_LENGTH = 6;
export const OTP_TTL_SECONDS = 5 * 60;
export const RESEND_COOLDOWN_SECONDS = 60;

export type AdminLoginStep = 'credentials' | 'otp';

function message(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

function isExpiredSession(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401 && /verification session/i.test(err.message);
}

/**
 * Format a countdown as `mm:ss`.
 *
 * @param totalSeconds - Remaining whole seconds.
 * @returns Zero-padded clock, never negative.
 */
export function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

/**
 * Admin sign-in: password, then a 6-digit email code.
 *
 * The temp token and password stay in component state so a resend can repeat
 * the password grant. Neither is written to web storage.
 *
 * @param onAuthenticated - Called after the admin session is stored.
 */
export function useAdminOtpLogin(onAuthenticated: () => Promise<void> | void) {
  const [step, setStep] = useState<AdminLoginStep>('credentials');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [tempToken, setTempToken] = useState<string | null>(null);
  const [code, setCodeState] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [resendAt, setResendAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const submitted = useRef<string | null>(null);
  const onAuthenticatedRef = useRef(onAuthenticated);
  onAuthenticatedRef.current = onAuthenticated;

  useEffect(() => {
    if (step !== 'otp') return undefined;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [step]);

  const secondsRemaining =
    expiresAt === null ? OTP_TTL_SECONDS : Math.max(0, Math.ceil((expiresAt - now) / 1000));
  const resendCooldown =
    resendAt === null ? RESEND_COOLDOWN_SECONDS : Math.max(0, Math.ceil((resendAt - now) / 1000));
  const expired = step === 'otp' && expiresAt !== null && secondsRemaining === 0;
  const canResend = step === 'otp' && !loading && resendCooldown === 0 && password.length > 0;

  const applyChallenge = useCallback((token: string) => {
    const started = Date.now();
    setTempToken(token);
    setCodeState('');
    submitted.current = null;
    setExpiresAt(started + OTP_TTL_SECONDS * 1000);
    setResendAt(started + RESEND_COOLDOWN_SECONDS * 1000);
    setNow(started);
    setStep('otp');
  }, []);

  const setCode = useCallback((value: string) => {
    setCodeState(value.replace(/\D/g, '').slice(0, OTP_LENGTH));
    setError(null);
  }, []);

  const submitCredentials = useCallback(async () => {
    if (loading || !email.trim() || !password) return;
    setLoading(true);
    setError(null);
    try {
      const challenge = await requestAdminOtp(email.trim(), password);
      applyChallenge(challenge.temp_token);
    } catch (err) {
      setError(message(err, 'Sign-in failed. Try again.'));
    } finally {
      setLoading(false);
    }
  }, [applyChallenge, email, loading, password]);

  const verify = useCallback(
    async (otp: string) => {
      if (!tempToken || loading || otp.length !== OTP_LENGTH || expired) return;
      if (submitted.current === otp) return;
      submitted.current = otp;
      setLoading(true);
      setError(null);
      try {
        const session = await verifyAdminOtp(tempToken, otp);
        await establishAdminSession(session);
        setPassword('');
      } catch (err) {
        submitted.current = null;
        if (isExpiredSession(err)) {
          setStep('credentials');
          setTempToken(null);
          setPassword('');
          setCodeState('');
          setExpiresAt(null);
          setResendAt(null);
          setError('This verification session expired. Sign in again.');
          return;
        }
        setCodeState('');
        setError(message(err, 'That code is not valid. Try again.'));
        return;
      } finally {
        setLoading(false);
      }
      try {
        await onAuthenticatedRef.current();
      } catch (err) {
        setError(message(err, 'Signed in, but the workspace could not be opened.'));
      }
    },
    [expired, loading, tempToken],
  );

  useEffect(() => {
    if (code.length !== OTP_LENGTH || step !== 'otp' || loading || expired) return;
    void verify(code);
  }, [code, expired, loading, step, verify]);

  const resend = useCallback(async () => {
    if (!canResend) return;
    setLoading(true);
    setError(null);
    try {
      const challenge = await requestAdminOtp(email.trim(), password);
      applyChallenge(challenge.temp_token);
    } catch (err) {
      setError(message(err, 'Could not resend the code. Try again.'));
    } finally {
      setLoading(false);
    }
  }, [applyChallenge, canResend, email, password]);

  const backToCredentials = useCallback(() => {
    setStep('credentials');
    setTempToken(null);
    setCodeState('');
    setPassword('');
    setError(null);
    setExpiresAt(null);
    setResendAt(null);
    submitted.current = null;
  }, []);

  return {
    step,
    email,
    setEmail,
    password,
    setPassword,
    code,
    setCode,
    error: error ?? (expired ? 'This code has expired. Resend a new code.' : null),
    loading,
    secondsRemaining,
    resendCooldown,
    expired,
    canResend,
    submitCredentials,
    verify,
    resend,
    backToCredentials,
  };
}
