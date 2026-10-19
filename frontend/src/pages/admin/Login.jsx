import React, { useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, ArrowRight, ArrowLeft } from 'lucide-react';
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';
import Button from '../../components/ui/Button';
import BrandLogo from '../../components/BrandLogo';
import { useAuth } from '../../context/useAuth';
import { isSupabaseConfigured } from '../../lib/supabaseClient';
import OtpCodeInput from '../../features/admin-auth/otp-code-input';
import { formatClock, useAdminOtpLogin } from '../../features/admin-auth/use-admin-otp-login';

export default function AdminLogin() {
  const navigate = useNavigate();
  const { refreshMembership } = useAuth();

  const finish = useCallback(async () => {
    try {
      await refreshMembership();
    } catch {
      // The session is already stored. The route guard reads it on arrival.
    }
    navigate('/admin/dashboard', { replace: true });
  }, [navigate, refreshMembership]);

  const login = useAdminOtpLogin(finish);

  return (
    <div className="min-h-screen bg-canvas flex flex-col justify-center items-center p-4">
      <div className="w-full max-w-md">
        <BrandLogo collapsed={false} className="h-10 w-auto mx-auto mb-6 object-contain" />

        <Card variant="elevated" className="p-8">
          <h1 className="text-xl font-semibold text-foreground mb-1">
            {login.step === 'otp' ? 'Verification code' : 'Admin Portal'}
          </h1>
          <p id="admin-otp-instructions" className="text-muted text-sm mb-6">
            {login.step === 'otp'
              ? 'Enter the 6-digit verification code sent to your registered email address.'
              : 'Enter your credentials to access the administrative console.'}
          </p>

          {!isSupabaseConfigured && (
            <div className="text-sm text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 mb-5">
              Supabase is not configured. Set <code>VITE_SUPABASE_URL</code> and{' '}
              <code>VITE_SUPABASE_ANON_KEY</code> in <code>frontend/.env.local</code> and restart the dev server.
            </div>
          )}

          {login.step === 'credentials' ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void login.submitCredentials();
              }}
              className="space-y-5"
            >
              <Input
                label="Email"
                type="email"
                icon={Mail}
                autoComplete="username"
                placeholder="ops@mindq.com"
                value={login.email}
                onChange={(event) => login.setEmail(event.target.value)}
                required
              />
              <Input
                label="Password"
                type="password"
                icon={Lock}
                autoComplete="current-password"
                placeholder="Your password"
                value={login.password}
                onChange={(event) => login.setPassword(event.target.value)}
                required
              />

              {login.error && (
                <div role="alert" className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
                  {login.error}
                </div>
              )}

              <Button
                type="submit"
                className="w-full"
                size="lg"
                isLoading={login.loading}
                disabled={!login.email || !login.password}
              >
                Sign In
                {!login.loading && <ArrowRight className="w-5 h-5 ml-2" />}
              </Button>
            </form>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void login.verify(login.code);
              }}
              className="space-y-5"
            >
              <OtpCodeInput
                value={login.code}
                onChange={login.setCode}
                disabled={login.loading || login.expired}
                invalid={Boolean(login.error)}
                describedBy="admin-otp-instructions admin-otp-timer"
              />
              <p id="admin-otp-timer" className="font-mono text-sm tabular-nums text-muted">
                Code expires in {formatClock(login.secondsRemaining)}
              </p>

              {login.error && (
                <div role="alert" className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
                  {login.error}
                </div>
              )}

              <Button
                type="button"
                variant="secondary"
                className="w-full"
                size="lg"
                disabled={!login.canResend || login.loading}
                onClick={() => {
                  void login.resend();
                }}
              >
                {login.resendCooldown > 0 ? `Resend code in ${formatClock(login.resendCooldown)}` : 'Resend code'}
              </Button>
              <button
                type="button"
                onClick={login.backToCredentials}
                disabled={login.loading}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-md py-1 text-sm text-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                Use a different account
              </button>
            </form>
          )}
        </Card>

        <p className="mt-6 text-center text-sm text-neutral-400">
          Looking for candidate or client access?{' '}
          <Link
            to="/portal"
            className="text-foreground underline-offset-4 hover:underline focus:outline-none focus-visible:underline focus-visible:text-primary-text"
          >
            Candidate access
          </Link>
          <span aria-hidden className="mx-2 text-neutral-600">·</span>
          <Link
            to="/client/login"
            className="text-foreground underline-offset-4 hover:underline focus:outline-none focus-visible:underline focus-visible:text-primary-text"
          >
            Client access
          </Link>
        </p>
      </div>
    </div>
  );
}
