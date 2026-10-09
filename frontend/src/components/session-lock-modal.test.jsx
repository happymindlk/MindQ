import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import SessionLockModal from './session-lock-modal';
import { maskEmail } from '../lib/mask-email';

describe('SessionLockModal (password variant)', () => {
  it('shows the masked account and unlocks with the correct password', async () => {
    const user = userEvent.setup();
    const onUnlock = vi.fn().mockResolvedValue(undefined);
    render(<SessionLockModal variant="password" email="jane@acme.com" onUnlock={onUnlock} />);

    expect(screen.getByRole('dialog', { name: 'Session locked' })).toBeInTheDocument();
    expect(screen.getByText('j***@acme.com')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Password'), 'correct-horse');
    await user.click(screen.getByRole('button', { name: 'Unlock' }));

    expect(onUnlock).toHaveBeenCalledWith('correct-horse');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps the lock up, clears the field, and shows the error on a wrong password', async () => {
    const user = userEvent.setup();
    const onUnlock = vi.fn().mockRejectedValue(new Error('Invalid login credentials'));
    render(<SessionLockModal variant="password" email="jane@acme.com" onUnlock={onUnlock} />);

    const input = screen.getByLabelText('Password');
    await user.type(input, 'wrong');
    await user.click(screen.getByRole('button', { name: 'Unlock' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid login credentials');
    expect(screen.getByRole('dialog', { name: 'Session locked' })).toBeInTheDocument();
    expect(input).toHaveValue('');
    await waitFor(() => expect(input).not.toBeDisabled());
  });

  it('falls back to a generic message when the auth error has none', async () => {
    const user = userEvent.setup();
    const onUnlock = vi.fn().mockRejectedValue({});
    render(<SessionLockModal variant="password" email="jane@acme.com" onUnlock={onUnlock} />);

    await user.type(screen.getByLabelText('Password'), 'x');
    await user.click(screen.getByRole('button', { name: 'Unlock' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect password. Try again.');
  });

  it('does not submit an empty password', async () => {
    const user = userEvent.setup();
    const onUnlock = vi.fn();
    render(<SessionLockModal variant="password" email="jane@acme.com" onUnlock={onUnlock} />);

    expect(screen.getByRole('button', { name: 'Unlock' })).toBeDisabled();
    await user.type(screen.getByLabelText('Password'), '{enter}');
    expect(onUnlock).not.toHaveBeenCalled();
  });

  it('cannot be dismissed with Escape and has no close button', async () => {
    const user = userEvent.setup();
    render(<SessionLockModal variant="password" email="jane@acme.com" onUnlock={vi.fn()} />);

    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', { name: 'Session locked' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
  });

  it('offers switching account', async () => {
    const user = userEvent.setup();
    const onSwitchAccount = vi.fn();
    render(
      <SessionLockModal
        variant="password"
        email="jane@acme.com"
        onUnlock={vi.fn()}
        onSwitchAccount={onSwitchAccount}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Sign in as a different user' }));
    expect(onSwitchAccount).toHaveBeenCalledTimes(1);
  });
});

describe('SessionLockModal (redirect variant)', () => {
  it('routes the user to sign in again instead of asking for a password', async () => {
    const user = userEvent.setup();
    const onContinue = vi.fn();
    render(<SessionLockModal variant="redirect" onContinue={onContinue} />);

    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Sign in again' }));
    expect(onContinue).toHaveBeenCalledTimes(1);
  });
});

describe('maskEmail', () => {
  it.each([
    ['jane@acme.com', 'j***@acme.com'],
    ['a@b.io', 'a**@b.io'],
    ['first.last+tag@sub.example.org', 'f*************@sub.example.org'],
    ['not-an-email', 'not-an-email'],
    [null, ''],
    [undefined, ''],
  ])('masks %s', (input, expected) => {
    expect(maskEmail(input)).toBe(expected);
  });
});
