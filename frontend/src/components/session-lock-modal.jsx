import React, { useId, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Lock } from 'lucide-react';
import Button from './ui/Button';
import Input from './ui/Input';
import { maskEmail } from '../lib/mask-email';

const blockDismiss = (event) => event.preventDefault();

/**
 * Non-dismissable lock shown after an idle timeout. The session tokens are already
 * cleared when this renders; the user must re-authenticate to continue.
 *
 * @param {object} props
 * @param {'password' | 'redirect'} props.variant `password` re-authenticates in place
 *   (Supabase ops portal); `redirect` sends the user to the OTP login (HR portal).
 * @param {string | null} [props.email] Account being unlocked (password variant).
 * @param {(password: string) => Promise<void>} [props.onUnlock] Rejects on bad credentials.
 * @param {() => void} [props.onContinue] Redirect variant CTA.
 * @param {() => void} [props.onSwitchAccount] Abandons the lock and opens the full login.
 */
export default function SessionLockModal({
  variant,
  email = null,
  onUnlock,
  onContinue,
  onSwitchAccount,
}) {
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const descriptionId = useId();

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!password || !onUnlock) return;
    setError(null);
    setSubmitting(true);
    try {
      await onUnlock(password);
    } catch (err) {
      setError(err?.message || 'Incorrect password. Try again.');
      setPassword('');
      setSubmitting(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={() => undefined}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] bg-canvas/90 backdrop-blur-sm" />
        <Dialog.Content
          aria-describedby={descriptionId}
          onEscapeKeyDown={blockDismiss}
          onPointerDownOutside={blockDismiss}
          onInteractOutside={blockDismiss}
          className="fixed left-1/2 top-1/2 z-[60] w-[calc(100vw-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-6 shadow-xl focus:outline-none"
        >
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">
              <Lock className="h-5 w-5" aria-hidden />
            </span>
            <div className="min-w-0">
              <Dialog.Title className="text-base font-semibold text-foreground">Session locked</Dialog.Title>
              <Dialog.Description id={descriptionId} className="text-xs text-muted">
                You were signed out after 15 minutes of inactivity.
              </Dialog.Description>
            </div>
          </div>

          {variant === 'password' ? (
            <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
              {email && (
                <p className="text-sm text-muted">
                  Re-enter the password for <span className="font-medium text-foreground">{maskEmail(email)}</span>.
                </p>
              )}
              <Input
                label="Password"
                aria-label="Password"
                type="password"
                autoComplete="current-password"
                autoFocus
                value={password}
                disabled={submitting}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={Boolean(error)}
              />
              {error && (
                <p role="alert" className="text-sm text-danger">
                  {error}
                </p>
              )}
              <Button type="submit" className="w-full" isLoading={submitting} disabled={!password}>
                Unlock
              </Button>
            </form>
          ) : (
            <div className="mt-6 space-y-4">
              <p className="text-sm text-muted">Sign in again with your email code to continue where you left off.</p>
              <Button type="button" className="w-full" onClick={onContinue}>
                Sign in again
              </Button>
            </div>
          )}

          {onSwitchAccount && (
            <button
              type="button"
              onClick={onSwitchAccount}
              className="mt-3 w-full rounded-md py-1 text-xs text-muted transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              Sign in as a different user
            </button>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
