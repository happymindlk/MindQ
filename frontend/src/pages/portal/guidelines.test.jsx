import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Guidelines from './Guidelines';

const navigate = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => navigate };
});

function renderGuidelines() {
  return render(
    <MemoryRouter>
      <Guidelines />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  navigate.mockReset();
  window.sessionStorage.clear();
  window.localStorage.clear();
  window.localStorage.setItem('candidateId', 'candidate-1');
});

describe('Guidelines confidentiality agreement gate', () => {
  it('renders the agreement below Assessment Deadline and blocks continuing until agreed', async () => {
    renderGuidelines();

    const deadline = screen.getByText('Assessment Deadline');
    const agreement = screen.getByText(/CANDIDATE NOTICE & ASSESSMENT CONFIDENTIALITY AGREEMENT/);
    expect(deadline.compareDocumentPosition(agreement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(/Proprietary & Confidential Material:/)).toBeInTheDocument();
    expect(screen.getByText(/Prohibition of AI & Automated Assistance:/)).toBeInTheDocument();
    expect(screen.getByText(/Active AI & Behavioral Integrity Monitoring:/)).toBeInTheDocument();
    expect(screen.getByText(/Notice of Consequences:/)).toBeInTheDocument();
    // Moved to the dashboard in the guideline reorganization.
    expect(screen.queryByText('Before You Begin')).not.toBeInTheDocument();

    const checkbox = screen.getByRole('checkbox', {
      name: 'I have read, understood, and agree to all terms mentioned above.',
    });
    const continueButton = screen.getByRole('button', { name: /I understand, continue/ });
    expect(checkbox).not.toBeChecked();
    expect(continueButton).toBeDisabled();

    const user = userEvent.setup();
    await user.click(checkbox);
    expect(checkbox).toBeChecked();
    expect(continueButton).toBeEnabled();

    await user.click(continueButton);
    expect(navigate).toHaveBeenCalledWith('/portal/dashboard');

    await user.click(checkbox);
    expect(continueButton).toBeDisabled();
  });

  it('restores the agreement from sessionStorage on remount in the same session', () => {
    const first = renderGuidelines();
    // Persist as the change handler does, then simulate revisiting the page.
    window.sessionStorage.setItem('mindq:confidentiality-agreed:candidate-1', '1');
    first.unmount();

    renderGuidelines();
    expect(
      screen.getByRole('checkbox', {
        name: 'I have read, understood, and agree to all terms mentioned above.',
      }),
    ).toBeChecked();
    expect(screen.getByRole('button', { name: /I understand, continue/ })).toBeEnabled();
  });
});
