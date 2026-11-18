import { afterEach, describe, expect, it } from 'vitest';
import {
  getDeviceContext,
  getDeviceHeaders,
  persistLoginDraft,
  readAccessCode,
  readLoginDraftEmail,
} from './device';

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState(null, '', '/');
});

describe('getDeviceContext', () => {
  it('persists a stable mindq_device_id in localStorage', () => {
    const first = getDeviceContext();
    const second = getDeviceContext();
    expect(first.device_id).toBe(second.device_id);
    expect(localStorage.getItem('mindq_device_id')).toBe(first.device_id);
    expect(first.browser).toBe(navigator.userAgent);
    expect(first.page_url).toContain(window.location.origin);
  });

  it('exposes X-Device-Id and X-Browser-Info headers', () => {
    localStorage.setItem('mindq_device_id', 'fixed-device');
    const headers = getDeviceHeaders();
    expect(headers['X-Device-Id']).toBe('fixed-device');
    expect(headers['X-Browser-Info']).toBe(navigator.userAgent);
  });
});

describe('login draft helpers', () => {
  it('reads email and access code from draft / URL', () => {
    persistLoginDraft({ email: 'you@example.com', accessCode: 'HM-DRAFT' });
    expect(readLoginDraftEmail()).toBe('you@example.com');
    expect(readAccessCode()).toBe('HM-DRAFT');

    window.history.replaceState(null, '', '/portal?code=HM-URL');
    expect(readAccessCode()).toBe('HM-URL');
  });
});
