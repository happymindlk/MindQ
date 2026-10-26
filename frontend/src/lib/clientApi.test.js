import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clientApi } from './clientApi';
import { clearClientSession, readClientSession } from '../pages/client/client-session';

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

beforeEach(() => {
  clearClientSession();
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('clientApi.requestOtp', () => {
  it('posts the email to the FastAPI HR OTP send endpoint and returns the temp token', async () => {
    fetch.mockResolvedValue(jsonResponse({ status: 'otp_required', temp_token: 'temp-token-value' }));

    await expect(clientApi.requestOtp('hr@acme.test')).resolves.toBe('temp-token-value');

    const otpCall = fetch.mock.calls.find(([url]) =>
      String(url).includes('/api/v1/hr/auth/otp/send'),
    );
    expect(otpCall).toBeTruthy();
    const [url, init] = otpCall;
    expect(url).toMatch(/\/api\/v1\/hr\/auth\/otp\/send$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ email: 'hr@acme.test' });
  });

  it('fails fast when the challenge response has no temp token', async () => {
    fetch.mockResolvedValue(jsonResponse({ status: 'otp_required' }));
    await expect(clientApi.requestOtp('hr@acme.test')).rejects.toThrow(/did not return a session/);
  });

  it('surfaces backend errors verbatim', async () => {
    fetch.mockResolvedValue(
      jsonResponse(
        { detail: 'This email is not registered for the client portal' },
        { ok: false, status: 403 },
      ),
    );
    await expect(clientApi.requestOtp('ghost@acme.test')).rejects.toThrow('not registered');
  });
});

describe('clientApi.verifyOtp', () => {
  it('posts email, code, and temp token to verify and stores the backend client session', async () => {
    fetch.mockResolvedValue(
      jsonResponse({
        access_token: 'client-jwt',
        token_type: 'bearer',
        expires_in: 3600,
        corporate: { id: 'corp-1', name: 'Acme', logo_url: null },
        user: { id: 'u1', email: 'hr@acme.test', full_name: 'Harriet', role: 'hr', corporate_id: 'corp-1' },
      }),
    );

    const session = await clientApi.verifyOtp('hr@acme.test', '123456', 'temp-token-value');

    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/hr\/auth\/otp\/verify$/);
    expect(JSON.parse(init.body)).toEqual({
      email: 'hr@acme.test',
      otp_code: '123456',
      temp_token: 'temp-token-value',
    });
    expect(session.token).toBe('client-jwt');
    expect(session.corporate).toEqual({ id: 'corp-1', name: 'Acme', logo_url: null });
    expect(readClientSession()?.token).toBe('client-jwt');
  });

  it('does not store a session when the code is rejected', async () => {
    fetch.mockResolvedValue(
      jsonResponse({ detail: 'Invalid or expired verification code' }, { ok: false, status: 401 }),
    );
    await expect(clientApi.verifyOtp('hr@acme.test', '000000', 'temp-token-value')).rejects.toThrow(
      'Invalid or expired verification code',
    );
    expect(readClientSession()).toBeNull();
  });
});
