import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../lib/api-error';

const { requestAdminOtp, verifyAdminOtp, establishAdminSession } = vi.hoisted(() => ({
  requestAdminOtp: vi.fn(),
  verifyAdminOtp: vi.fn(),
  establishAdminSession: vi.fn(),
}));

vi.mock('./admin-otp-api', () => ({
  requestAdminOtp,
  verifyAdminOtp,
  establishAdminSession,
}));

import { formatClock, useAdminOtpLogin } from './use-admin-otp-login';

const TOKEN = 't'.repeat(24);

describe('formatClock', () => {
  it('renders the five-minute countdown as mm:ss', () => {
    expect(formatClock(299)).toBe('04:59');
    expect(formatClock(300)).toBe('05:00');
    expect(formatClock(0)).toBe('00:00');
  });
});

describe('useAdminOtpLogin', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-14T10:00:00Z'));
    requestAdminOtp.mockReset();
    verifyAdminOtp.mockReset();
    establishAdminSession.mockReset();
    requestAdminOtp.mockResolvedValue({ status: 'otp_required', temp_token: TOKEN });
    establishAdminSession.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function reachOtp(onAuthenticated = vi.fn()) {
    const hook = renderHook(() => useAdminOtpLogin(onAuthenticated));
    act(() => {
      hook.result.current.setEmail('ops@mindq.com');
      hook.result.current.setPassword('secret');
    });
    await act(async () => {
      await hook.result.current.submitCredentials();
    });
    return hook;
  }

  it('keeps the temp token in memory and starts both clocks', async () => {
    const { result } = await reachOtp();
    expect(result.current.step).toBe('otp');
    expect(result.current.secondsRemaining).toBe(300);
    expect(result.current.resendCooldown).toBe(60);
    expect(result.current.canResend).toBe(false);
    expect(formatClock(result.current.secondsRemaining)).toBe('05:00');
  });

  it('enables resend only after 60 seconds and resets the code on success', async () => {
    const { result } = await reachOtp();
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(result.current.canResend).toBe(true);
    expect(result.current.secondsRemaining).toBe(240);
    requestAdminOtp.mockResolvedValueOnce({ status: 'otp_required', temp_token: 'n'.repeat(24) });
    await act(async () => {
      await result.current.resend();
    });
    expect(requestAdminOtp).toHaveBeenCalledTimes(2);
    expect(result.current.resendCooldown).toBe(60);
    expect(result.current.secondsRemaining).toBe(300);
    expect(result.current.code).toBe('');
  });

  it('submits the six-digit code once and redirects through the session callback', async () => {
    const onAuthenticated = vi.fn();
    verifyAdminOtp.mockResolvedValue({ access_token: 'a', refresh_token: 'r' });
    const { result } = await reachOtp(onAuthenticated);
    await act(async () => {
      result.current.setCode('123456');
    });
    expect(verifyAdminOtp).toHaveBeenCalledTimes(1);
    expect(verifyAdminOtp).toHaveBeenCalledWith(TOKEN, '123456');
    expect(establishAdminSession).toHaveBeenCalledTimes(1);
    expect(onAuthenticated).toHaveBeenCalledTimes(1);
  });

  it('clears a wrong code and stays on the otp step', async () => {
    verifyAdminOtp.mockRejectedValue(new ApiError('Invalid or expired verification code', 401));
    const { result } = await reachOtp();
    await act(async () => {
      result.current.setCode('000000');
    });
    expect(result.current.step).toBe('otp');
    expect(result.current.code).toBe('');
    expect(result.current.error).toBe('Invalid or expired verification code');
  });

  it('returns to credentials when the verification session expired', async () => {
    verifyAdminOtp.mockRejectedValue(new ApiError('Invalid or expired verification session', 401));
    const { result } = await reachOtp();
    await act(async () => {
      result.current.setCode('123456');
    });
    expect(result.current.step).toBe('credentials');
    expect(result.current.password).toBe('');
    expect(result.current.error).toMatch(/session expired/i);
    expect(establishAdminSession).not.toHaveBeenCalled();
  });

  it('shows an expiry message when the five minutes elapse', async () => {
    const { result } = await reachOtp();
    await act(async () => {
      vi.advanceTimersByTime(5 * 60 * 1000);
    });
    expect(result.current.expired).toBe(true);
    expect(result.current.error).toBe('This code has expired. Resend a new code.');
    expect(result.current.canResend).toBe(true);
  });
});
