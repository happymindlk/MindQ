import React, { useEffect, useId, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, Eye, EyeOff, Lock } from 'lucide-react';
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';
import Button from '../../components/ui/Button';
import BrandLogo from '../../components/BrandLogo';
import ToastProvider from '../../components/ui/Toast';
import { useToast } from '../../components/ui/useToast';
import { friendlyErrorMessage } from '../../lib/friendly-error';
import { supabase } from '../../lib/supabaseClient';
import { MIN_PASSWORD_LENGTH, validatePasswordChange } from './use-change-password';

/**
 * Completes a recovery session from the email link and sets a new password.
 *
 * Supabase delivers tokens in the URL hash; ``detectSessionInUrl`` establishes
 * the recovery session. We then call ``updateUser({ password })``.
 */
function ResetPasswordForm() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [ready, setReady] = useState(false);
  const [sessionError, setSessionError] = useState(null);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const newId = useId();
  const confirmId = useId();

  useEffect(() => {
    let cancelled = false;
    let timerId = 0;

    const { data: sub } = supabase.auth.onAuthStateChange((event, next) => {
      if (cancelled) return;
      if (event === 'PASSWORD_RECOVERY' || (event === 'SIGNED_IN' && next)) {
        setReady(true);
        setSessionError(null);
      }
    });

    void supabase.auth.getSession().then(({ data }) => {
      if (cancelled) return;
      if (data.session) {
        setReady(true);
        return;
      }
      // Hash tokens may still be processing after redirect from GoTrue.
      timerId = window.setTimeout(() => {
        void supabase.auth.getSession().then(({ data: again }) => {
          if (cancelled) return;
          if (again.session) {
            setReady(true);
          } else {
            setSessionError(
              'This reset link is invalid or has expired. Request a new one from the sign-in page.',
            );
          }
        });
      }, 1200);
    });

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
      sub.subscription.unsubscribe();
    };
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    const errors = validatePasswordChange(undefined, newPassword, confirmPassword);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setIsSubmitting(true);
    try {
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) throw error;
      await supabase.auth.signOut({ scope: 'local' });
      toast({
        variant: 'success',
        title: 'Password updated',
        description: 'Sign in with your new password.',
      });
      navigate('/admin/login', { replace: true });
    } catch (err) {
      toast({
        variant: 'error',
        title: 'Could not reset password',
        description: friendlyErrorMessage(err, 'Something went wrong. Please try again.'),
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex flex-col justify-center items-center p-4">
      <div className="w-full max-w-md">
        <BrandLogo collapsed={false} className="h-10 w-auto mx-auto mb-6 object-contain" />

        <Card variant="elevated" className="p-8">
          <h1 className="mb-2 text-center font-display text-2xl font-bold tracking-normal text-slate-900 dark:text-slate-100">
            Choose a new password
          </h1>
          <p className="mb-6 text-center text-sm text-muted">
            Enter a new password for your Admin Portal account.
          </p>

          {sessionError ? (
            <div className="space-y-5">
              <div
                role="alert"
                className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2"
              >
                {sessionError}
              </div>
              <Link
                to="/admin/forgot-password"
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-md py-2 text-sm text-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                Request a new reset link
              </Link>
            </div>
          ) : !ready ? (
            <p className="text-center text-sm text-muted" role="status">
              Verifying reset link…
            </p>
          ) : (
            <form onSubmit={handleSubmit} noValidate className="space-y-5">
              <div>
                <label htmlFor={newId} className="metric-label mb-1.5 block">
                  New password
                </label>
                <div className="relative">
                  <Input
                    id={newId}
                    type={showNew ? 'text' : 'password'}
                    icon={Lock}
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(event) => {
                      setNewPassword(event.target.value);
                      setFieldErrors((prev) =>
                        prev.newPassword ? { ...prev, newPassword: undefined } : prev,
                      );
                    }}
                    error={fieldErrors.newPassword}
                    disabled={isSubmitting}
                    className="pr-10!"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNew((v) => !v)}
                    aria-label={showNew ? 'Hide password' : 'Show password'}
                    className="absolute top-0 right-0 h-9 w-9 flex items-center justify-center rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                  >
                    {showNew ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {!fieldErrors.newPassword && (
                  <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">
                    At least {MIN_PASSWORD_LENGTH} characters.
                  </p>
                )}
              </div>

              <div>
                <label htmlFor={confirmId} className="metric-label mb-1.5 block">
                  Confirm password
                </label>
                <div className="relative">
                  <Input
                    id={confirmId}
                    type={showConfirm ? 'text' : 'password'}
                    icon={Lock}
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(event) => {
                      setConfirmPassword(event.target.value);
                      setFieldErrors((prev) =>
                        prev.confirmPassword ? { ...prev, confirmPassword: undefined } : prev,
                      );
                    }}
                    error={fieldErrors.confirmPassword}
                    disabled={isSubmitting}
                    className="pr-10!"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirm((v) => !v)}
                    aria-label={showConfirm ? 'Hide password' : 'Show password'}
                    className="absolute top-0 right-0 h-9 w-9 flex items-center justify-center rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                  >
                    {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <Button
                type="submit"
                className="w-full"
                size="lg"
                isLoading={isSubmitting}
                disabled={!newPassword || !confirmPassword}
              >
                Update password
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

export default function ResetPassword() {
  return (
    <ToastProvider>
      <ResetPasswordForm />
    </ToastProvider>
  );
}
