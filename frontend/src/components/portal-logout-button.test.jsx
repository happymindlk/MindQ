import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PortalLogoutButton from './portal-logout-button';
import { isPortalTestRunnerPath, portalLoginPathAfterLogout } from './portal-logout-path';

const clearCandidateSession = vi.fn();

vi.mock('../features/candidate-auth/candidate-otp-api', () => ({
  clearCandidateSession: (...args) => clearCandidateSession(...args),
}));

function LocationProbe() {
  const { pathname, search } = useLocation();
  return <div data-testid="location">{`${pathname}${search}`}</div>;
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <PortalLogoutButton />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('portal logout helpers', () => {
  it('detects the timed assessment runner path', () => {
    expect(isPortalTestRunnerPath('/portal/test/abc')).toBe(true);
    expect(isPortalTestRunnerPath('/portal/test')).toBe(true);
    expect(isPortalTestRunnerPath('/portal/dashboard')).toBe(false);
    expect(isPortalTestRunnerPath('/portal')).toBe(false);
  });

  it('preserves the package code on the login redirect path', () => {
    localStorage.setItem('candidateAccessCode', 'HM-ABCDEF-1');
    expect(portalLoginPathAfterLogout()).toBe('/portal?code=HM-ABCDEF-1');
    localStorage.removeItem('candidateAccessCode');
    expect(portalLoginPathAfterLogout()).toBe('/portal');
  });
});

describe('PortalLogoutButton', () => {
  beforeEach(() => {
    clearCandidateSession.mockReset();
    clearCandidateSession.mockResolvedValue(undefined);
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('renders on the portal dashboard and logs out with redirect after confirm', async () => {
    localStorage.setItem('candidateToken', 'cand-jwt');
    localStorage.setItem('candidateAccessCode', 'HM-ABCDEF-1');
    const user = userEvent.setup();
    renderAt('/portal/dashboard');

    await user.click(screen.getByRole('button', { name: 'Log out' }));
    const dialog = screen.getByRole('dialog', { name: 'Log out?' });
    expect(dialog).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Log out' }));

    await waitFor(() => {
      expect(clearCandidateSession).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/portal?code=HM-ABCDEF-1');
    });
  });

  it('is hidden during an active assessment on /portal/test/...', () => {
    localStorage.setItem('candidateToken', 'cand-jwt');
    renderAt('/portal/test/t1');
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument();
  });

  it('is hidden when the candidate is not signed in', () => {
    renderAt('/portal/dashboard');
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument();
  });
});
