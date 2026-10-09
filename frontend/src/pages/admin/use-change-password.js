import { useCallback, useState } from 'react';
import { supabase } from '../../lib/supabaseClient';

export const MIN_PASSWORD_LENGTH = 8;

/**
 * @typedef {object} PasswordFieldErrors
 * @property {string} [newPassword]
 * @property {string} [confirmPassword]
 */

/**
 * Validate a password change before it reaches Supabase.
 *
 * @param {string} newPassword
 * @param {string} confirmPassword
 * @returns {PasswordFieldErrors} Empty object when valid.
 */
export function validatePasswordChange(newPassword, confirmPassword) {
  /** @type {PasswordFieldErrors} */
  const errors = {};
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
 * `submit` resolves `true` on success (and clears the form), `false` when
 * client-side validation fails, and throws the Supabase error otherwise.
 *
 * @returns {{
 *   newPassword: string,
 *   confirmPassword: string,
 *   setNewPassword: (value: string) => void,
 *   setConfirmPassword: (value: string) => void,
 *   fieldErrors: PasswordFieldErrors,
 *   isSubmitting: boolean,
 *   submit: () => Promise<boolean>,
 * }}
 */
export function useChangePassword() {
  const [newPassword, setNewPasswordState] = useState('');
  const [confirmPassword, setConfirmPasswordState] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [isSubmitting, setIsSubmitting] = useState(false);

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
    const errors = validatePasswordChange(newPassword, confirmPassword);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return false;

    setIsSubmitting(true);
    try {
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) throw error;
      setNewPasswordState('');
      setConfirmPasswordState('');
      return true;
    } finally {
      setIsSubmitting(false);
    }
  }, [newPassword, confirmPassword]);

  return {
    newPassword,
    confirmPassword,
    setNewPassword,
    setConfirmPassword,
    fieldErrors,
    isSubmitting,
    submit,
  };
}
