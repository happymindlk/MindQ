import { beforeEach, describe, expect, it, vi } from 'vitest';

const { sendCandidateOtp: sendCandidateOtpMock, verifyCandidateOtp: verifyCandidateOtpMock } =
  vi.hoisted(() => ({
    sendCandidateOtp: vi.fn(),
    verifyCandidateOtp: vi.fn(),
  }));

vi.mock('../../api/client', () => ({
  api: { candidate: { sendCandidateOtp: sendCandidateOtpMock, verifyCandidateOtp: verifyCandidateOtpMock } },
}));

import { persistCandidateSession, sendCandidateOtp, verifyCandidateOtp } from './candidate-otp-api';

const identity = {
  accessCode: ' HM-ABCDEF-1 ',
  firstName: ' Ada ',
  lastName: ' Lovelace ',
  email: ' Ada@Example.com ',
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('sendCandidateOtp', () => {
  it('requests a backend code with trimmed identity and normalized email', async () => {
    sendCandidateOtpMock.mockResolvedValue({ status: 'otp_required', temp_token: 'temp-token-value' });
    await expect(sendCandidateOtp(identity)).resolves.toBe('temp-token-value');
    expect(sendCandidateOtpMock).toHaveBeenCalledWith({
      access_code: 'HM-ABCDEF-1',
      email: 'ada@example.com',
      first_name: 'Ada',
      full_name: 'Ada Lovelace',
    });
  });

  it('surfaces backend rate-limit errors verbatim', async () => {
    sendCandidateOtpMock.mockRejectedValue(
      new Error('A verification code was just sent. Wait a minute before requesting another.'),
    );
    await expect(sendCandidateOtp(identity)).rejects.toThrow('Wait a minute');
  });

  it('fails fast when the challenge response has no temp token', async () => {
    sendCandidateOtpMock.mockResolvedValue({ status: 'otp_required' });
    await expect(sendCandidateOtp(identity)).rejects.toThrow(/did not return a session/);
    expect(verifyCandidateOtpMock).not.toHaveBeenCalled();
  });
});

describe('verifyCandidateOtp', () => {
  it('completes verification with the temp token and derived full name, without any Supabase token', async () => {
    verifyCandidateOtpMock.mockResolvedValue({
      token: 'cand-jwt',
      id: 'c1',
      first_name: 'Ada',
      full_name: 'Ada Lovelace',
      access_code: 'HM-ABCDEF-1',
    });

    const session = await verifyCandidateOtp(identity, '123456', 'temp-token-value');

    expect(verifyCandidateOtpMock).toHaveBeenCalledWith({
      access_code: 'HM-ABCDEF-1',
      first_name: 'Ada',
      full_name: 'Ada Lovelace',
      email: 'ada@example.com',
      temp_token: 'temp-token-value',
      otp_code: '123456',
    });
    expect(session).toEqual({
      token: 'cand-jwt',
      id: 'c1',
      firstName: 'Ada',
      fullName: 'Ada Lovelace',
      accessCode: 'HM-ABCDEF-1',
    });
  });

  it('propagates backend rejection of an invalid code', async () => {
    verifyCandidateOtpMock.mockRejectedValue(new Error('Invalid or expired verification code'));
    await expect(verifyCandidateOtp(identity, '000000', 'temp-token-value')).rejects.toThrow(
      'Invalid or expired verification code',
    );
  });

  it('maps omitted optional response fields to empty strings', async () => {
    verifyCandidateOtpMock.mockResolvedValue({ token: 't', id: 'c1', first_name: null, full_name: 'Ada Lovelace' });
    const session = await verifyCandidateOtp(identity, '123456', 'temp-token-value');
    expect(session.firstName).toBe('');
    expect(session.accessCode).toBe('');
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
