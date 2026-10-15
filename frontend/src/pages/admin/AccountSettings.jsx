import React, { useId, useState } from 'react';
import { Eye, EyeOff, KeyRound } from 'lucide-react';
import Button from '../../components/ui/Button';
import Input from '../../components/ui/Input';
import PageHeader from '../../components/ui/PageHeader';
import { useToast } from '../../components/ui/useToast';
import { friendlyErrorMessage } from '../../lib/friendly-error';
import { MIN_PASSWORD_LENGTH, useChangePassword } from './use-change-password';

function PasswordField({ label, value, onChange, error, disabled, hint }) {
  const id = useId();
  const [visible, setVisible] = useState(false);

  return (
    <div>
      <label htmlFor={id} className="metric-label mb-1.5 block">
        {label}
      </label>
      <div className="relative">
        <Input
          id={id}
          type={visible ? 'text' : 'password'}
          autoComplete="new-password"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          error={error}
          aria-invalid={Boolean(error)}
          className="pr-10!"
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          aria-pressed={visible}
          aria-controls={id}
          disabled={disabled}
          className="absolute top-0 right-0 h-9 w-9 flex items-center justify-center rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:opacity-50"
        >
          {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
      {hint && !error && <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}

export default function AccountSettings() {
  const { toast } = useToast();
  const {
    newPassword,
    confirmPassword,
    setNewPassword,
    setConfirmPassword,
    fieldErrors,
    isSubmitting,
    submit,
  } = useChangePassword();

  const handleSubmit = async (event) => {
    event.preventDefault();
    try {
      const updated = await submit();
      if (updated) {
        toast({
          variant: 'success',
          title: 'Password updated',
          description: 'Use your new password the next time you sign in.',
        });
      }
    } catch (err) {
      toast({
        variant: 'error',
        title: 'Could not update password',
        description: friendlyErrorMessage(err, 'Something went wrong. Please try again.'),
      });
    }
  };

  const canSubmit = Boolean(newPassword && confirmPassword) && !isSubmitting;

  return (
    <div className="space-y-6">
      <PageHeader title="Account Settings" description="Manage your sign-in credentials." />

      <section
        aria-labelledby="change-password-heading"
        className="max-w-md rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
      >
        <div className="flex items-center gap-3 px-4 py-4 border-b border-slate-200 dark:border-slate-800">
          <div className="p-2 rounded-md bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">
            <KeyRound className="w-4 h-4" aria-hidden="true" />
          </div>
          <div>
            <h2
              id="change-password-heading"
              className="text-sm font-semibold text-slate-900 dark:text-slate-100"
            >
              Change Password
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              You stay signed in on this device after updating.
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} noValidate className="px-4 py-4 space-y-4">
          <PasswordField
            label="New Password"
            value={newPassword}
            onChange={setNewPassword}
            error={fieldErrors.newPassword}
            disabled={isSubmitting}
            hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          />
          <PasswordField
            label="Confirm New Password"
            value={confirmPassword}
            onChange={setConfirmPassword}
            error={fieldErrors.confirmPassword}
            disabled={isSubmitting}
          />
          <div className="flex justify-end pt-2">
            <Button type="submit" variant="primary" isLoading={isSubmitting} disabled={!canSubmit}>
              Update Password
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
