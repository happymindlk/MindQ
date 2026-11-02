import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ToastProvider from '../../components/ui/Toast';
import AccountSettings from './AccountSettings';
import { validatePasswordChange } from './use-change-password';

const { changeAdminPassword } = vi.hoisted(() => ({
  changeAdminPassword: vi.fn(),
}));

vi.mock('../../features/admin-auth/admin-password-api', () => ({
  changeAdminPassword,
}));

function renderPage() {
  return render(
    <ToastProvider>
      <AccountSettings />
    </ToastProvider>,
  );
}

async function fill(user, currentPassword, newPassword, confirmPassword) {
  await user.type(screen.getByLabelText('Current Password'), currentPassword);
  await user.type(screen.getByLabelText('New Password'), newPassword);
  await user.type(screen.getByLabelText('Confirm New Password'), confirmPassword);
}

describe('AccountSettings', () => {
  beforeEach(() => {
    changeAdminPassword.mockReset();
  });

  it('renders the Change Password form with the submit disabled until all fields are filled', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByRole('heading', { name: 'Change Password' })).toBeInTheDocument();
    const submit = screen.getByRole('button', { name: 'Update Password' });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText('Current Password'), 'old-secret1');
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText('New Password'), 'longenough1');
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText('Confirm New Password'), 'l');
    expect(submit).toBeEnabled();
  });

  it('blocks the request and shows an inline error when passwords do not match', async () => {
    const user = userEvent.setup();
    renderPage();

    await fill(user, 'old-secret1', 'correct-horse-1', 'correct-horse-2');
    await user.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(screen.getByText('Passwords do not match.')).toBeInTheDocument();
    expect(screen.getByLabelText('Confirm New Password')).toHaveAttribute('aria-invalid', 'true');
    expect(changeAdminPassword).not.toHaveBeenCalled();
  });

  it('rejects passwords shorter than the minimum length', async () => {
    const user = userEvent.setup();
    renderPage();

    await fill(user, 'old-secret1', 'short', 'short');
    await user.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(screen.getByText('Password must be at least 8 characters.')).toBeInTheDocument();
    expect(changeAdminPassword).not.toHaveBeenCalled();
  });

  it('updates the password, shows a success toast, and clears the form', async () => {
    const user = userEvent.setup();
    changeAdminPassword.mockResolvedValue(undefined);
    renderPage();

    await fill(user, 'old-secret1', 'correct-horse-1', 'correct-horse-1');
    await user.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(changeAdminPassword).toHaveBeenCalledWith('old-secret1', 'correct-horse-1');
    expect(await screen.findByText('Password updated')).toBeInTheDocument();
    expect(screen.getByLabelText('Current Password')).toHaveValue('');
    expect(screen.getByLabelText('New Password')).toHaveValue('');
    expect(screen.getByLabelText('Confirm New Password')).toHaveValue('');
  });

  it('shows an inline error when the current password is wrong', async () => {
    const user = userEvent.setup();
    changeAdminPassword.mockRejectedValue(new Error('Incorrect current password.'));
    renderPage();

    await fill(user, 'wrong-pass', 'correct-horse-1', 'correct-horse-1');
    await user.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(await screen.findByText('Incorrect current password.')).toBeInTheDocument();
    expect(screen.getByLabelText('Current Password')).toHaveValue('wrong-pass');
  });

  it('shows an error toast and keeps the input on failure', async () => {
    const user = userEvent.setup();
    changeAdminPassword.mockRejectedValue(
      new Error('New password should be different from the old password.'),
    );
    renderPage();

    await fill(user, 'old-secret1', 'correct-horse-1', 'correct-horse-1');
    await user.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(await screen.findByText('Could not update password')).toBeInTheDocument();
    expect(
      screen.getByText('New password should be different from the old password.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('New Password')).toHaveValue('correct-horse-1');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Update Password' })).toBeEnabled(),
    );
  });

  it('falls back to a generic message when the request throws a network error', async () => {
    const user = userEvent.setup();
    changeAdminPassword.mockRejectedValue(new Error('Failed to fetch'));
    renderPage();

    await fill(user, 'old-secret1', 'correct-horse-1', 'correct-horse-1');
    await user.click(screen.getByRole('button', { name: 'Update Password' }));

    expect(await screen.findByText('Something went wrong. Please try again.')).toBeInTheDocument();
  });

  it('toggles password visibility per field', async () => {
    const user = userEvent.setup();
    renderPage();

    const input = screen.getByLabelText('New Password');
    expect(input).toHaveAttribute('type', 'password');

    const toggles = screen.getAllByRole('button', { name: 'Show password' });
    await user.click(toggles[1]);
    expect(input).toHaveAttribute('type', 'text');
    expect(screen.getByLabelText('Confirm New Password')).toHaveAttribute('type', 'password');

    await user.click(screen.getByRole('button', { name: 'Hide password' }));
    expect(input).toHaveAttribute('type', 'password');
  });
});

describe('validatePasswordChange', () => {
  it.each([
    [
      undefined,
      '',
      '',
      { newPassword: 'Enter a new password.', confirmPassword: 'Confirm your new password.' },
    ],
    [undefined, 'longenough', '', { confirmPassword: 'Confirm your new password.' }],
    [undefined, 'longenough', 'different', { confirmPassword: 'Passwords do not match.' }],
    [undefined, 'abc', 'abc', { newPassword: 'Password must be at least 8 characters.' }],
    [undefined, 'longenough', 'longenough', {}],
    ['', 'longenough', 'longenough', { currentPassword: 'Enter your current password.' }],
    ['old-secret', 'longenough', 'longenough', {}],
  ])('validates %j / %j / %j', (currentPassword, newPassword, confirmPassword, expected) => {
    expect(validatePasswordChange(currentPassword, newPassword, confirmPassword)).toEqual(expected);
  });
});
