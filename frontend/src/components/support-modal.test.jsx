import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SupportModal from './SupportModal';

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

async function openModal(user) {
  await user.click(screen.getByRole('button', { name: /technical support/i }));
}

describe('SupportModal', () => {
  it('shows a friendly quick-report layout without the support checklist', async () => {
    localStorage.setItem('candidateName', 'Ada Lovelace');
    localStorage.setItem('candidateAccessCode', 'HM-ABCDEF-1');
    render(<SupportModal />);

    await openModal(userEvent.setup());

    expect(screen.getByText('Need Help?')).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Briefly describe the issue you're facing...")).toBeInTheDocument();
    for (const label of ['Full Name', 'Package Code', 'Applied Role', 'Device / Browser info', 'Screenshots of the issue']) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    const cta = screen.getByRole('link', { name: /or email us directly at support@mindqtalent\.com/i });
    const href = cta.getAttribute('href') ?? '';
    expect(href.startsWith('mailto:support@mindqtalent.com?')).toBe(true);
    const body = new URL(href).searchParams.get('body') ?? '';
    expect(body).toContain('Full Name: Ada Lovelace');
    expect(body).toContain('Package Code: HM-ABCDEF-1');
    expect(body).not.toContain('Applied Role');
  });

  it('keeps the quick report disabled until the candidate types something', async () => {
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    const send = screen.getByRole('button', { name: /send quick report/i });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText(/describe the issue/i), 'Timer froze');
    expect(send).toBeEnabled();
  });

  it('auto-attaches metadata and shows the success state on a 200 response', async () => {
    localStorage.setItem('candidateId', 'c1');
    localStorage.setItem('candidateAccessCode', 'HM-ABCDEF-1');
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    await user.type(screen.getByLabelText(/describe the issue/i), 'Timer froze');
    await user.click(screen.getByRole('button', { name: /send quick report/i }));

    expect(await screen.findByText('Thanks! Our team will look into this.')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/support\/submit$/);
    expect(JSON.parse(init.body)).toEqual({
      details: 'Timer froze',
      candidate_id: 'c1',
      package_code: 'HM-ABCDEF-1',
      path: '/',
      user_agent: navigator.userAgent,
    });
  });

  it('falls back to the invite code in the URL before sign-in', async () => {
    window.history.replaceState(null, '', '/portal?code=HM-URL-9');
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    await user.type(screen.getByLabelText(/describe the issue/i), 'Cannot start');
    await user.click(screen.getByRole('button', { name: /send quick report/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).package_code).toBe('HM-URL-9');
  });

  it('shows a friendly error and preserves the report when the fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    const textarea = screen.getByLabelText(/describe the issue/i);
    await user.type(textarea, 'Page froze');
    await user.click(screen.getByRole('button', { name: /send quick report/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't reach our support team/i);
    expect(textarea).toHaveValue('Page froze');
    expect(screen.getByRole('button', { name: /send quick report/i })).toBeEnabled();
  });

  it('surfaces the server detail on a non-OK response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, json: async () => ({ detail: 'Too many requests' }) }),
    );
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    await user.type(screen.getByLabelText(/describe the issue/i), 'Spammy clicks');
    await user.click(screen.getByRole('button', { name: /send quick report/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests');
  });
});
