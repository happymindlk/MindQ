import { useCallback, useState } from 'react';
import { changeAdminPassword } from '../../features/admin-auth/admin-password-api';

export const MIN_PASSWORD_LENGTH = 8;

/**
 * @typedef {object} PasswordFieldErrors
 * @property {string} [currentPassword]
 * @property {string} [newPassword]
 * @property {string} [confirmPassword]
 */

/**
 * Validate a password change before it reaches the API.
 *
 * @param {string} currentPassword
 * @param {string} newPassword
 * @param {string} confirmPassword
 * @returns {PasswordFieldErrors} Empty object when valid.
 */
export function validatePasswordChange(currentPassword, newPassword, confirmPassword) {
  /** @type {PasswordFieldErrors} */
  const errors = {};

  // Reset-password form reuses this helper without a current-password field.
  if (currentPassword !== undefined) {
    if (!currentPassword) {
      errors.currentPassword = 'Enter your current password.';
    }
  }

  if (!newPassword) {
    errors.newPassword = 'Enter a new password.';
  } else if (newPassword.length < MIN_PASSWORD_LENGTH) {
    errors.newPassword = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (!confirmPassword) {
    errors.confirmPassword = 'Confirm your new password.';
  } else if (newPassword && confirmPassword !== newPassword) {
    errors.confirmPassword = 'Passwords do not match.';
  }
  return errors;
}

/**
 * Form state and submission for changing the signed-in user's password.
 *
 * Re-authenticates via ``POST /api/v1/admin/auth/change-password`` so the
 * current password must match before Supabase Auth is updated.
 *
 * `submit` resolves `true` on success (and clears the form), `false` when
 * client-side validation fails, and throws the API error otherwise.
 *
 * @returns {{
 *   currentPassword: string,
 *   newPassword: string,
 *   confirmPassword: string,
 *   setCurrentPassword: (value: string) => void,
 *   setNewPassword: (value: string) => void,
 *   setConfirmPassword: (value: string) => void,
 *   fieldErrors: PasswordFieldErrors,
 *   isSubmitting: boolean,
 *   submit: () => Promise<boolean>,
 * }}
 */
export function useChangePassword() {
  const [currentPassword, setCurrentPasswordState] = useState('');
  const [newPassword, setNewPasswordState] = useState('');
  const [confirmPassword, setConfirmPasswordState] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const setCurrentPassword = useCallback((value) => {
    setCurrentPasswordState(value);
    setFieldErrors((prev) =>
      prev.currentPassword ? { ...prev, currentPassword: undefined } : prev,
    );
  }, []);

  const setNewPassword = useCallback((value) => {
    setNewPasswordState(value);
    setFieldErrors((prev) => (prev.newPassword ? { ...prev, newPassword: undefined } : prev));
  }, []);

  const setConfirmPassword = useCallback((value) => {
    setConfirmPasswordState(value);
    setFieldErrors((prev) =>
      prev.confirmPassword ? { ...prev, confirmPassword: undefined } : prev,
    );
  }, []);

  const submit = useCallback(async () => {
    const errors = validatePasswordChange(currentPassword, newPassword, confirmPassword);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return false;

    setIsSubmitting(true);
    try {
      await changeAdminPassword(currentPassword, newPassword);
      setCurrentPasswordState('');
      setNewPasswordState('');
      setConfirmPasswordState('');
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : '';
      if (/incorrect current password/i.test(message)) {
        setFieldErrors({ currentPassword: 'Incorrect current password.' });
        return false;
      }
      throw err;
    } finally {
      setIsSubmitting(false);
    }
  }, [currentPassword, newPassword, confirmPassword]);

  return {
    currentPassword,
    newPassword,
    confirmPassword,
    setCurrentPassword,
    setNewPassword,
    setConfirmPassword,
    fieldErrors,
    isSubmitting,
    submit,
  };
}
