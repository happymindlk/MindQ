import { beforeEach, describe, expect, it, vi } from 'vitest';

const { auth, login } = vi.hoisted(() => ({
  auth: {
    signInWithOtp: vi.fn(),
    verifyOtp: vi.fn(),
    signOut: vi.fn(),
  },
  login: vi.fn(),
}));

vi.mock('../../lib/supabase-otp-client', () => ({ supabaseOtp: { auth } }));
vi.mock('../../api/client', () => ({ api: { candidate: { login } } }));

import { persistCandidateSession, sendCandidateOtp, verifyCandidateOtp } from './candidate-otp-api';

const identity = {
  accessCode: ' HM-ABCDEF-1 ',
  firstName: ' Ada ',
  fullName: ' Ada Lovelace ',
  email: ' Ada@Example.com ',
};

beforeEach(() => {
  vi.clearAllMocks();
  auth.signOut.mockResolvedValue({ error: null });
});

describe('sendCandidateOtp', () => {
  it('normalizes the email and allows first-time candidates', async () => {
    auth.signInWithOtp.mockResolvedValue({ error: null });
    await sendCandidateOtp(' Ada@Example.com ');
    expect(auth.signInWithOtp).toHaveBeenCalledWith({
      email: 'ada@example.com',
      options: { shouldCreateUser: true },
    });
  });

  it('surfaces Supabase rate-limit errors verbatim', async () => {
    auth.signInWithOtp.mockResolvedValue({
      error: { message: 'For security purposes, you can only request this after 42 seconds.' },
    });
    await expect(sendCandidateOtp('ada@example.com')).rejects.toThrow('after 42 seconds');
  });
});

describe('verifyCandidateOtp', () => {
  it('exchanges the Supabase token for a candidate session with trimmed identity', async () => {
    auth.verifyOtp.mockResolvedValue({ data: { session: { access_token: 'sb-token' } }, error: null });
    login.mockResolvedValue({
      token: 'cand-jwt',
      id: 'c1',
      first_name: 'Ada',
      full_name: 'Ada Lovelace',
      access_code: 'HM-ABCDEF-1',
    });

    const session = await verifyCandidateOtp(identity, '123456');

    expect(auth.verifyOtp).toHaveBeenCalledWith({ email: 'ada@example.com', token: '123456', type: 'email' });
    expect(login).toHaveBeenCalledWith(
      { access_code: 'HM-ABCDEF-1', first_name: 'Ada', full_name: 'Ada Lovelace', email: 'ada@example.com' },
      'sb-token',
    );
    expect(session).toEqual({
      token: 'cand-jwt',
      id: 'c1',
      firstName: 'Ada',
      fullName: 'Ada Lovelace',
      accessCode: 'HM-ABCDEF-1',
    });
    expect(auth.signOut).toHaveBeenCalledWith({ scope: 'local' });
  });

  it('rejects an invalid code without calling the backend', async () => {
    auth.verifyOtp.mockResolvedValue({ data: { session: null }, error: { message: 'Token has expired or is invalid' } });
    await expect(verifyCandidateOtp(identity, '000000')).rejects.toThrow('expired or is invalid');
    expect(login).not.toHaveBeenCalled();
  });

  it('fails fast when verification returns no session', async () => {
    auth.verifyOtp.mockResolvedValue({ data: { session: null }, error: null });
    await expect(verifyCandidateOtp(identity, '123456')).rejects.toThrow(/did not return a session/);
    expect(login).not.toHaveBeenCalled();
  });

  it('discards the Supabase session even when the backend rejects the access code', async () => {
    auth.verifyOtp.mockResolvedValue({ data: { session: { access_token: 'sb-token' } }, error: null });
    login.mockRejectedValue(new Error('Invalid access code'));
    await expect(verifyCandidateOtp(identity, '123456')).rejects.toThrow('Invalid access code');
    expect(auth.signOut).toHaveBeenCalledWith({ scope: 'local' });
  });

  it('falls back to the entered first name and access code when the backend omits them', async () => {
    auth.verifyOtp.mockResolvedValue({ data: { session: { access_token: 'sb-token' } }, error: null });
    login.mockResolvedValue({ token: 't', id: 'c1', first_name: null, full_name: 'Ada Lovelace' });
    const session = await verifyCandidateOtp(identity, '123456');
    expect(session.firstName).toBe('Ada');
    expect(session.accessCode).toBe('HM-ABCDEF-1');
  });
});

describe('persistCandidateSession', () => {
  it('writes every key the portal reads', () => {
    persistCandidateSession({
      token: 't',
      id: 'c1',
      firstName: 'Ada',
      fullName: 'Ada Lovelace',
      accessCode: 'HM-ABCDEF-1',
    });
    expect(localStorage.getItem('candidateAccessCode')).toBe('HM-ABCDEF-1');
    expect(localStorage.getItem('candidateToken')).toBe('t');
    expect(localStorage.getItem('candidateId')).toBe('c1');
    expect(localStorage.getItem('candidateName')).toBe('Ada Lovelace');
    expect(localStorage.getItem('candidateFirstName')).toBe('Ada');
  });
});
