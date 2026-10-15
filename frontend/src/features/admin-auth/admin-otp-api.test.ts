import { beforeEach, describe, expect, it, vi } from 'vitest';

const { requestJson, setSession } = vi.hoisted(() => ({
  requestJson: vi.fn(),
  setSession: vi.fn(),
}));

vi.mock('../../lib/api-request', () => ({
  requestJson,
  BAD_RESPONSE_MESSAGE: 'The server returned an unexpected response. Please try again.',
}));

vi.mock('../../lib/supabaseClient', () => ({
  supabase: { auth: { setSession } },
}));

import { establishAdminSession, requestAdminOtp, verifyAdminOtp } from './admin-otp-api';

const session = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  token_type: 'bearer' as const,
  expires_in: 3600,
  user: {
    id: 'user-1',
    email: 'ops@mindq.com',
    full_name: 'Ops Admin',
    role: 'admin',
    corporate_id: 'corp-1',
  },
};

beforeEach(() => {
  requestJson.mockReset();
  setSession.mockReset();
  setSession.mockResolvedValue({ data: { session: null }, error: null });
});

describe('requestAdminOtp', () => {
  it('returns the temp token and does not treat it as a session', async () => {
    requestJson.mockResolvedValue({ status: 'otp_required', temp_token: 't'.repeat(24), access_token: 'nope' });
    const challenge = await requestAdminOtp('ops@mindq.com', 'secret');
    expect(challenge).toEqual({ status: 'otp_required', temp_token: 't'.repeat(24) });
    expect(requestJson).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/admin/auth/login'),
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ email: 'ops@mindq.com', password: 'secret' }) }),
      expect.any(String),
    );
    expect(setSession).not.toHaveBeenCalled();
  });

  it('rejects a body that is not an otp challenge', async () => {
    requestJson.mockResolvedValue({ access_token: 'direct' });
    await expect(requestAdminOtp('ops@mindq.com', 'secret')).rejects.toThrow(/unexpected response/i);
  });
});

describe('verifyAdminOtp', () => {
  it('stores the admin session through the Supabase client', async () => {
    requestJson.mockResolvedValue(session);
    const result = await verifyAdminOtp('t'.repeat(24), '123456');
    expect(result.access_token).toBe('access-token');
    await establishAdminSession(result);
    expect(setSession).toHaveBeenCalledWith({
      access_token: 'access-token',
      refresh_token: 'refresh-token',
    });
  });

  it('rejects a verify body without a refresh token', async () => {
    requestJson.mockResolvedValue({ access_token: 'only-access' });
    await expect(verifyAdminOtp('t'.repeat(24), '123456')).rejects.toThrow(/unexpected response/i);
    expect(setSession).not.toHaveBeenCalled();
  });
});
