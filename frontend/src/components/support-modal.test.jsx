import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import SupportModal from './SupportModal';

afterEach(() => localStorage.clear());

describe('SupportModal', () => {
  it('lists every required detail and links to the support inbox', async () => {
    localStorage.setItem('candidateName', 'Ada Lovelace');
    localStorage.setItem('candidateAccessCode', 'HM-ABCDEF-1');
    render(<SupportModal />);

    await userEvent.setup().click(screen.getByRole('button', { name: /technical support/i }));

    for (const label of ['Full Name', 'Package Code', 'Applied Role', 'Device / Browser info', 'Screenshots of the issue']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    const cta = screen.getByRole('link', { name: /email support@mindqtalent\.com/i });
    const href = cta.getAttribute('href') ?? '';
    expect(href.startsWith('mailto:support@mindqtalent.com?')).toBe(true);
    const body = new URL(href).searchParams.get('body') ?? '';
    expect(body).toContain('Full Name: Ada Lovelace');
    expect(body).toContain('Package Code: HM-ABCDEF-1');
  });

  it('keeps the quick report disabled until the candidate types something', async () => {
    render(<SupportModal />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /technical support/i }));
    const send = screen.getByRole('button', { name: /send quick report/i });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText(/describe the issue/i), 'Timer froze');
    expect(send).toBeEnabled();
  });
});
