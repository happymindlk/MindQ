import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Login from './Login';

const { clearStale } = vi.hoisted(() => ({
  clearStale: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  api: {
    candidate: {
      getDashboard: vi.fn(),
      sendCandidateOtp: vi.fn(),
      verifyCandidateOtp: vi.fn(),
      logout: vi.fn(),
    },
  },
}));

vi.mock('../../features/candidate-auth/candidate-otp-api', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    clearStaleCandidateSessionIfExpired: (...args) => clearStale(...args),
  };
});

vi.mock('../../features/assessment-runner/preview-runner', () => ({
  PreviewRunner: () => <div>preview</div>,
}));

function renderPortalLogin(path = '/portal?code=HM-PKG001-A') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/portal" element={<Login />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  clearStale.mockReset();
  clearStale.mockImplementation(async () => {
    localStorage.removeItem('candidateToken');
    localStorage.removeItem('candidateId');
    localStorage.removeItem('candidateName');
    localStorage.removeItem('candidateFirstName');
    localStorage.removeItem('candidateAccessCode');
    return true;
  });
});

describe('portal login expired session', () => {
  it('clears an expired stored JWT and shows OTP login without the token error', async () => {
    localStorage.setItem('candidateToken', 'expired-jwt');
    localStorage.setItem('candidateAccessCode', 'HM-PKG001-A');
    localStorage.setItem('candidateId', 'c1');

    renderPortalLogin('/portal?code=HM-PKG001-A');

    await waitFor(() => {
      expect(clearStale).toHaveBeenCalledTimes(1);
    });

    expect(
      await screen.findByRole('heading', { name: /Welcome to Your Assessment/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Access Code/i)).toHaveValue('HM-PKG001-A');
    expect(screen.getByLabelText(/^Email$/i)).toBeInTheDocument();
    expect(screen.queryByText(/Invalid or expired token/i)).not.toBeInTheDocument();
    expect(localStorage.getItem('candidateToken')).toBeNull();
  });
});
