<<<<<<< HEAD
import React, { useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, ArrowRight, ArrowLeft, Package } from 'lucide-react';
=======
import React, { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { Mail, Lock, ArrowRight, Package } from 'lucide-react';
>>>>>>> f2ea5da40ec4de18df112e656d9be4777af7d5a7
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';
import Button from '../../components/ui/Button';
import { useAuth } from '../../context/useAuth';
<<<<<<< HEAD
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
=======
import { isOpsRole, resolveRole } from '../../lib/auth-role';
import { isSupabaseConfigured, supabase } from '../../lib/supabaseClient';

export default function AdminLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  const { signIn, refreshMembership } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const from = location.state?.from?.pathname || '/admin/history';

  const handleLogin = async (e) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      const { error: signInError } = await signIn(email, password);
      if (signInError) throw signInError;
      const membership = await refreshMembership();
      if (!membership?.corporateId) {
        navigate('/pending-approval', { replace: true });
        return;
      }
      const { data } = await supabase.auth.getSession();
      const role = membership.role || resolveRole(data.session, null);
      if (!isOpsRole(role)) {
        navigate('/client/dashboard', { replace: true });
        return;
      }
      navigate(from.startsWith('/admin') ? from : '/admin/history', { replace: true });
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setIsLoading(false);
    }
  };
>>>>>>> f2ea5da40ec4de18df112e656d9be4777af7d5a7

  return (
    <div className="min-h-screen bg-canvas flex flex-col justify-center items-center p-4">
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-2 text-primary-text mb-8">
          <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
            <Package className="w-5 h-5" />
          </div>
          <span className="font-semibold text-xl text-foreground">MindQ</span>
        </div>

        <Card variant="elevated" className="p-8">
<<<<<<< HEAD
          <h1 className="text-xl font-semibold text-foreground mb-1">
            {login.step === 'otp' ? 'Verification code' : 'Admin Portal'}
          </h1>
          <p id="admin-otp-instructions" className="text-muted text-sm mb-6">
            {login.step === 'otp'
              ? 'Enter the 6-digit verification code sent to your registered email address.'
              : 'Enter your credentials to access the administrative console.'}
=======
          <h1 className="text-xl font-semibold text-foreground mb-1">Admin Portal</h1>
          <p className="text-neutral-400 text-sm mb-6">
            Enter your credentials to access the administrative console.
>>>>>>> f2ea5da40ec4de18df112e656d9be4777af7d5a7
          </p>

          {!isSupabaseConfigured && (
            <div className="text-sm text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 mb-5">
              Supabase is not configured. Set <code>VITE_SUPABASE_URL</code> and{' '}
              <code>VITE_SUPABASE_ANON_KEY</code> in <code>frontend/.env.local</code> and restart the dev server.
            </div>
          )}

<<<<<<< HEAD
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
=======
          <form onSubmit={handleLogin} className="space-y-5">
            <Input
              label="Email"
              type="email"
              icon={Mail}
              placeholder="ops@mindq.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <Input
              label="Password"
              type="password"
              icon={Lock}
              placeholder="Your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />

            {error && (
              <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" size="lg" isLoading={isLoading} disabled={!email || !password}>
              Sign In
              {!isLoading && <ArrowRight className="w-5 h-5 ml-2" />}
            </Button>
          </form>
>>>>>>> f2ea5da40ec4de18df112e656d9be4777af7d5a7
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
