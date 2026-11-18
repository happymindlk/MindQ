import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SupportModal from './SupportModal';

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

async function openModal(user) {
  await user.click(screen.getByRole('button', { name: /technical support/i }));
}

async function fillRequiredFields(user, { email = 'you@example.com', phone = '+94 77 123 4567', details = 'Timer froze' } = {}) {
  await user.type(screen.getByLabelText(/email address/i), email);
  await user.type(screen.getByLabelText(/contact number/i), phone);
  await user.type(screen.getByLabelText(/describe the issue/i), details);
}

describe('SupportModal', () => {
  it('shows a friendly quick-report layout without the support checklist', async () => {
    localStorage.setItem('candidateName', 'Ada Lovelace');
    localStorage.setItem('candidateAccessCode', 'HM-ABCDEF-1');
    render(<SupportModal />);

    await openModal(userEvent.setup());

    expect(screen.getByText('Need Help?')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('you@example.com')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('+94 77 123 4567')).toBeInTheDocument();
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

  it('keeps the quick report disabled until email, phone, and description are valid', async () => {
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    const send = screen.getByRole('button', { name: /send quick report/i });
    expect(send).toBeDisabled();

    await user.type(screen.getByLabelText(/describe the issue/i), 'Timer froze');
    expect(send).toBeDisabled();

    await user.type(screen.getByLabelText(/email address/i), 'not-an-email');
    await user.type(screen.getByLabelText(/contact number/i), '123');
    expect(send).toBeDisabled();

    await user.clear(screen.getByLabelText(/email address/i));
    await user.type(screen.getByLabelText(/email address/i), 'you@example.com');
    await user.clear(screen.getByLabelText(/contact number/i));
    await user.type(screen.getByLabelText(/contact number/i), '+94 77 123 4567');
    expect(send).toBeEnabled();
  });

  it('prefills email from the login draft in session storage', async () => {
    sessionStorage.setItem('mindq_login_email', 'draft@example.com');
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    expect(screen.getByLabelText(/email address/i)).toHaveValue('draft@example.com');
  });

  it('auto-attaches metadata and shows the success state on a 200 response', async () => {
    localStorage.setItem('candidateId', 'c1');
    localStorage.setItem('candidateAccessCode', 'HM-ABCDEF-1');
    localStorage.setItem('mindq_device_id', 'device-fixed-1');
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    await fillRequiredFields(user);

    await user.click(screen.getByRole('button', { name: /send quick report/i }));

    expect(await screen.findByText('Thanks! Our team will look into this.')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/support\/submit$/);
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({
      email: 'you@example.com',
      contact_number: '+94 77 123 4567',
      details: 'Timer froze',
      description: 'Timer froze',
      candidate_id: 'c1',
      package_code: 'HM-ABCDEF-1',
      access_code: 'HM-ABCDEF-1',
      device_id: 'device-fixed-1',
      path: '/',
      user_agent: navigator.userAgent,
    });
    expect(body.browser).toBe(navigator.userAgent);
    expect(body.page_url).toContain(window.location.origin);
  });

  it('falls back to the invite code in the URL before sign-in', async () => {
    window.history.replaceState(null, '', '/portal?code=HM-URL-9');
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    await fillRequiredFields(user, { details: 'Cannot start' });
    await user.click(screen.getByRole('button', { name: /send quick report/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.package_code).toBe('HM-URL-9');
    expect(body.access_code).toBe('HM-URL-9');
  });

  it('shows a friendly error and preserves the report when the fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    render(<SupportModal />);
    const user = userEvent.setup();
    await openModal(user);
    await fillRequiredFields(user, { details: 'Page froze' });
    await user.click(screen.getByRole('button', { name: /send quick report/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn't reach our support team/i);
    expect(screen.getByLabelText(/describe the issue/i)).toHaveValue('Page froze');
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
    await fillRequiredFields(user, { details: 'Spammy clicks' });
    await user.click(screen.getByRole('button', { name: /send quick report/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many requests');
  });
});
