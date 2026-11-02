import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Mail } from 'lucide-react';
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';
import Button from '../../components/ui/Button';
import BrandLogo from '../../components/BrandLogo';
import { friendlyErrorMessage } from '../../lib/friendly-error';
import {
  DEFAULT_RESET_CONFIRMATION,
  requestAdminPasswordReset,
} from '../../features/admin-auth/admin-password-api';

/**
 * Self-serve admin forgot-password screen.
 * Always shows a generic confirmation after submit to avoid account enumeration.
 */
export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [confirmation, setConfirmation] = useState(null);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError(null);
    setConfirmation(null);
    setLoading(true);
    try {
      const detail = await requestAdminPasswordReset(email);
      setConfirmation(detail || DEFAULT_RESET_CONFIRMATION);
    } catch (err) {
      setError(friendlyErrorMessage(err, 'Could not send a reset link. Try again.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex flex-col justify-center items-center p-4">
      <div className="w-full max-w-md">
        <BrandLogo collapsed={false} className="h-10 w-auto mx-auto mb-6 object-contain" />

        <Card variant="elevated" className="p-8">
          <h1 className="mb-2 text-center font-display text-2xl font-bold tracking-normal text-slate-900 dark:text-slate-100">
            Forgot password
          </h1>
          <p className="mb-6 text-center text-sm text-muted">
            Enter your admin email and we will send a reset link if an account exists.
          </p>

          {confirmation ? (
            <div className="space-y-5">
              <div
                role="status"
                className="text-sm text-success bg-success/10 border border-success/20 rounded-lg px-3 py-2"
              >
                {confirmation}
              </div>
              <Link
                to="/admin/login"
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-md py-2 text-sm text-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <Input
                label="Email"
                type="email"
                icon={Mail}
                autoComplete="username"
                placeholder="ops@mindq.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />

              {error && (
                <div
                  role="alert"
                  className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2"
                >
                  {error}
                </div>
              )}

              <Button
                type="submit"
                className="w-full"
                size="lg"
                isLoading={loading}
                disabled={!email.trim()}
              >
                Send Reset Link
              </Button>

              <Link
                to="/admin/login"
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-md py-1 text-sm text-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                Back to sign in
              </Link>
            </form>
          )}
        </Card>
      </div>
    </div>
  );
}
