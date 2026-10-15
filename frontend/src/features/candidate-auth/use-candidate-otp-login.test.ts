import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { sendCandidateOtp, verifyCandidateOtp, persistCandidateSession } = vi.hoisted(() => ({
  sendCandidateOtp: vi.fn(),
  verifyCandidateOtp: vi.fn(),
  persistCandidateSession: vi.fn(),
}));

vi.mock('./candidate-otp-api', () => ({
  normalizeEmail: (email: string) => email.trim().toLowerCase(),
  sendCandidateOtp,
  verifyCandidateOtp,
  persistCandidateSession,
}));

import { RESEND_COOLDOWN_SECONDS, isIdentityComplete, useCandidateOtpLogin } from './use-candidate-otp-login';

const complete = { accessCode: 'HM-1', firstName: 'Ada', fullName: 'Ada Lovelace', email: 'ada@example.com' };

function fill(result: { current: ReturnType<typeof useCandidateOtpLogin> }) {
  act(() => {
    result.current.updateField('firstName', complete.firstName);
    result.current.updateField('fullName', complete.fullName);
    result.current.updateField('email', complete.email);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('isIdentityComplete', () => {
  it.each([
    ['access code', { ...complete, accessCode: '  ' }],
    ['first name', { ...complete, firstName: '   ' }],
    ['full name', { ...complete, fullName: '' }],
    ['valid email', { ...complete, email: 'ada@' }],
  ])('requires a %s', (_label, identity) => {
    expect(isIdentityComplete(identity)).toBe(false);
  });

  it('accepts a fully filled identity', () => {
    expect(isIdentityComplete(complete)).toBe(true);
  });
});

describe('useCandidateOtpLogin', () => {
  it('prefills the invite access code and blocks sending until all fields are valid', async () => {
    const { result } = renderHook(() => useCandidateOtpLogin('HM-1', vi.fn()));
    expect(result.current.identity.accessCode).toBe('HM-1');
    expect(result.current.canSend).toBe(false);
    await act(() => result.current.sendCode());
    expect(sendCandidateOtp).not.toHaveBeenCalled();
  });

  it('moves to the code step and starts the resend cooldown after sending', async () => {
    sendCandidateOtp.mockResolvedValue(undefined);
    const { result } = renderHook(() => useCandidateOtpLogin('HM-1', vi.fn()));
    fill(result);
    await act(() => result.current.sendCode());
    expect(sendCandidateOtp).toHaveBeenCalledWith('ada@example.com');
    expect(result.current.step).toBe('code');
    expect(result.current.cooldown).toBe(RESEND_COOLDOWN_SECONDS);
  });

  it('stays on the details step and shows the error when sending fails', async () => {
    sendCandidateOtp.mockRejectedValue(new Error('Email rate limit exceeded'));
    const { result } = renderHook(() => useCandidateOtpLogin('HM-1', vi.fn()));
    fill(result);
    await act(() => result.current.sendCode());
    expect(result.current.step).toBe('details');
    expect(result.current.error).toBe('Email rate limit exceeded');
    expect(result.current.loading).toBe(false);
  });

  it('blocks resend during the cooldown and allows it once the timer elapses', async () => {
    vi.useFakeTimers();
    sendCandidateOtp.mockResolvedValue(undefined);
    const { result } = renderHook(() => useCandidateOtpLogin('HM-1', vi.fn()));
    fill(result);
    await act(() => result.current.sendCode());

    await act(() => result.current.resendCode());
    expect(sendCandidateOtp).toHaveBeenCalledTimes(1);

    for (let i = 0; i < RESEND_COOLDOWN_SECONDS; i += 1) {
      act(() => {
        vi.advanceTimersByTime(1000);
      });
    }
    expect(result.current.cooldown).toBe(0);
    await act(() => result.current.resendCode());
    expect(sendCandidateOtp).toHaveBeenCalledTimes(2);
  });

  it('strips non-digits from the code and caps its length', () => {
    const { result } = renderHook(() => useCandidateOtpLogin('HM-1', vi.fn()));
    act(() => result.current.setCode('12-34 56789x'));
    expect(result.current.code).toBe('12345678');
  });

  it('persists the session and notifies the caller on a valid code', async () => {
    sendCandidateOtp.mockResolvedValue(undefined);
    const session = { token: 't', id: 'c1', firstName: 'Ada', fullName: 'Ada Lovelace', accessCode: 'HM-1' };
    verifyCandidateOtp.mockResolvedValue(session);
    const onAuthenticated = vi.fn();
    const { result } = renderHook(() => useCandidateOtpLogin('HM-1', onAuthenticated));
    fill(result);
    await act(() => result.current.sendCode());
    act(() => result.current.setCode('123456'));
    await act(() => result.current.verifyCode());

    expect(verifyCandidateOtp).toHaveBeenCalledWith(complete, '123456');
    expect(persistCandidateSession).toHaveBeenCalledWith(session);
    expect(onAuthenticated).toHaveBeenCalledWith(session);
  });

  it('keeps the candidate on the code step with an error when verification fails', async () => {
    sendCandidateOtp.mockResolvedValue(undefined);
    verifyCandidateOtp.mockRejectedValue(new Error('Token has expired or is invalid'));
    const onAuthenticated = vi.fn();
    const { result } = renderHook(() => useCandidateOtpLogin('HM-1', onAuthenticated));
    fill(result);
    await act(() => result.current.sendCode());
    act(() => result.current.setCode('999999'));
    await act(() => result.current.verifyCode());

    expect(result.current.step).toBe('code');
    expect(result.current.error).toBe('Token has expired or is invalid');
    expect(result.current.loading).toBe(false);
    expect(persistCandidateSession).not.toHaveBeenCalled();
    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  it('does not verify a short code', async () => {
    const { result } = renderHook(() => useCandidateOtpLogin('HM-1', vi.fn()));
    act(() => result.current.setCode('123'));
    await act(() => result.current.verifyCode());
    expect(verifyCandidateOtp).not.toHaveBeenCalled();
  });

  it('returns to the details step and clears the code when editing details', async () => {
    sendCandidateOtp.mockResolvedValue(undefined);
    const { result } = renderHook(() => useCandidateOtpLogin('HM-1', vi.fn()));
    fill(result);
    await act(() => result.current.sendCode());
    act(() => result.current.setCode('123456'));
    act(() => result.current.editDetails());
    expect(result.current.step).toBe('details');
    expect(result.current.code).toBe('');
    expect(result.current.identity.firstName).toBe('Ada');
  });
});
