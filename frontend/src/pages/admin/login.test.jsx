import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../lib/api-error';
import AdminLogin from './Login';

const { requestAdminOtp, verifyAdminOtp, establishAdminSession, refreshMembership } = vi.hoisted(() => ({
  requestAdminOtp: vi.fn(),
  verifyAdminOtp: vi.fn(),
  establishAdminSession: vi.fn(),
  refreshMembership: vi.fn(),
}));

vi.mock('../../features/admin-auth/admin-otp-api', () => ({
  requestAdminOtp,
  verifyAdminOtp,
  establishAdminSession,
}));

vi.mock('../../context/useAuth', () => ({
  useAuth: () => ({ refreshMembership }),
}));

vi.mock('../../lib/supabaseClient', () => ({
  isSupabaseConfigured: true,
  supabase: { auth: {} },
}));

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/admin/login']}>
      <Routes>
        <Route path="/admin/login" element={<AdminLogin />} />
        <Route path="/admin/dashboard" element={<h1>Ops dashboard</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  requestAdminOtp.mockReset();
  verifyAdminOtp.mockReset();
  establishAdminSession.mockReset();
  refreshMembership.mockReset();
  requestAdminOtp.mockResolvedValue({ status: 'otp_required', temp_token: 't'.repeat(24) });
  verifyAdminOtp.mockResolvedValue({
    access_token: 'access',
    refresh_token: 'refresh',
    expires_in: 3600,
    user: { id: '1', email: 'ops@mindq.com', full_name: null, role: 'admin', corporate_id: 'c' },
  });
  establishAdminSession.mockResolvedValue(undefined);
  refreshMembership.mockResolvedValue({ corporateId: 'c', role: 'admin' });
});

describe('AdminLogin OTP', () => {
  it('moves to the code form when the password step requires a code', async () => {
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText('Email'), 'ops@mindq.com');
    await user.type(screen.getByLabelText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Sign In' }));

    expect(await screen.findByText('Enter the 6-digit verification code sent to your registered email address.')).toBeInTheDocument();
    expect(screen.getByText(/Code expires in 05:00/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Resend code in 01:00/ })).toBeDisabled();
    expect(screen.queryByText('t'.repeat(24))).not.toBeInTheDocument();
  });

  it('verifies a pasted code and opens the admin dashboard', async () => {
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText('Email'), 'ops@mindq.com');
    await user.type(screen.getByLabelText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Sign In' }));
    await screen.findByLabelText('Digit 1 of 6');
    await user.click(screen.getByLabelText('Digit 1 of 6'));
    await user.paste('123456');

    await waitFor(() => {
      expect(verifyAdminOtp).toHaveBeenCalledWith('t'.repeat(24), '123456');
    });
    expect(await screen.findByRole('heading', { name: 'Ops dashboard' })).toBeInTheDocument();
    expect(establishAdminSession).toHaveBeenCalled();
    expect(refreshMembership).toHaveBeenCalled();
  });

  it('shows the server message for an invalid code', async () => {
    verifyAdminOtp.mockRejectedValue(new ApiError('Invalid or expired verification code', 401));
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText('Email'), 'ops@mindq.com');
    await user.type(screen.getByLabelText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Sign In' }));
    await screen.findByLabelText('Digit 1 of 6');
    await user.click(screen.getByLabelText('Digit 1 of 6'));
    await user.paste('000000');

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid or expired verification code');
    expect(screen.queryByRole('heading', { name: 'Ops dashboard' })).not.toBeInTheDocument();
  });
});
