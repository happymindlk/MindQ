import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Mail, ShieldCheck } from 'lucide-react';
import { clientApi } from '../../lib/clientApi';
import { isSupabaseConfigured } from '../../lib/supabaseClient';
import { useClientSession } from './use-client-session';

const CODE_LENGTH = 6;

function ErrorBanner({ message }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300"
    >
      {message}
    </p>
  );
}

function SubmitButton({ loading, disabled, children }) {
  return (
    <button
      type="submit"
      disabled={disabled || loading}
      className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-indigo-600 px-4 text-sm font-semibold text-white transition-colors hover:bg-indigo-700 active:bg-indigo-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas disabled:cursor-not-allowed disabled:bg-surface-raised disabled:text-muted"
    >
      {loading ? (
        <span
          aria-hidden="true"
          className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
        />
      ) : null}
      {children}
    </button>
  );
}

const inputClass =
  'h-10 w-full rounded-md border border-border bg-surface-raised px-3 text-sm text-foreground placeholder:text-muted transition-colors focus:border-indigo-600 focus:outline-none focus:ring-1 focus:ring-indigo-600 disabled:opacity-50';

export default function ClientLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, signIn } = useClientSession();
  const fromPath = location.state?.from?.pathname;
  const returnTo = fromPath && fromPath.startsWith('/client/') && fromPath !== '/client/login'
    ? fromPath
    : '/client/dashboard';
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState('email');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isAuthenticated) navigate(returnTo, { replace: true });
  }, [isAuthenticated, navigate, returnTo]);

  const sendCode = async (event) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await clientApi.requestOtp(email.trim().toLowerCase());
      setStep('code');
    } catch (err) {
      setError(err.message || 'Could not send code');
    } finally {
      setLoading(false);
    }
  };

  const verify = async (event) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const session = await clientApi.verifyOtp(email.trim().toLowerCase(), code);
      signIn(session);
      navigate(returnTo, { replace: true });
    } catch (err) {
      setError(err.message || 'Invalid code');
      setLoading(false);
    }
  };

  const resetEmail = () => {
    setStep('email');
    setCode('');
    setError(null);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-8">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-md border border-indigo-600/40 bg-indigo-600/10 text-indigo-600 dark:text-indigo-400">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          </span>
          <span className="text-sm font-semibold tracking-tight text-foreground">
            MindQ <span className="font-normal text-muted">Client Portal</span>
          </span>
        </div>

        <div className="rounded-lg border border-border bg-surface p-6 shadow-[0_0_0_1px_rgba(0,0,0,0.4)]">
          <div className="mb-6 flex items-center gap-2 text-xs font-medium text-muted">
            <span className={step === 'email' ? 'text-indigo-600 dark:text-indigo-400' : 'text-muted'}>1 Email</span>
            <span aria-hidden="true" className="h-px w-6 bg-surface-raised" />
            <span className={step === 'code' ? 'text-indigo-600 dark:text-indigo-400' : 'text-muted'}>2 Verify</span>
          </div>

          {!isSupabaseConfigured && (
            <p className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
              Supabase is not configured.
            </p>
          )}

          {step === 'email' ? (
            <form onSubmit={sendCode} className="space-y-4" noValidate>
              <div>
                <h1 className="text-lg font-semibold text-foreground">Sign in</h1>
                <p className="mt-1 text-sm text-muted">
                  Enter your registered corporate email to receive a one-time code.
                </p>
              </div>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted">Corporate email</span>
                <span className="relative block">
                  <Mail
                    aria-hidden="true"
                    className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
                  />
                  <input
                    type="email"
                    required
                    autoFocus
                    autoComplete="email"
                    placeholder="hr@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={loading}
                    className={`${inputClass} pl-9`}
                  />
                </span>
              </label>
              <ErrorBanner message={error} />
              <SubmitButton loading={loading} disabled={!email.includes('@')}>
                Send code
                {!loading && <ArrowRight className="h-4 w-4" aria-hidden="true" />}
              </SubmitButton>
            </form>
          ) : (
            <form onSubmit={verify} className="space-y-4" noValidate>
              <div>
                <h1 className="text-lg font-semibold text-foreground">Enter code</h1>
                <p className="mt-1 text-sm text-muted">
                  We sent a {CODE_LENGTH}-digit code to{' '}
                  <span className="font-medium text-foreground">{email}</span>.
                </p>
              </div>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-muted">One-time code</span>
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  placeholder="000000"
                  maxLength={8}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                  disabled={loading}
                  className={`${inputClass} text-center font-mono text-base tracking-[0.4em] tabular-nums`}
                />
              </label>
              <ErrorBanner message={error} />
              <SubmitButton loading={loading} disabled={code.length < CODE_LENGTH}>
                Verify and continue
              </SubmitButton>
              <button
                type="button"
                onClick={resetEmail}
                disabled={loading}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-md py-1 text-xs text-muted transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600 disabled:opacity-50"
              >
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                Use a different email
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
